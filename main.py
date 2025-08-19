#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Taichung Cafes Crawler (Google Maps Platform)
- Covers Taichung City via grid + Nearby Search pagination
- Dedupes by place_id
- Enriches with Place Details (phone, opening hours, maps url, photos)
Outputs: CSV with columns:
  name, address, phone, opening_hours, rating, types, photo_url, maps_url
"""

import os
import time
import math
import csv
import requests
import argparse
from typing import Dict, Any, List, Tuple

API_KEY = os.getenv("GOOGLE_API_KEY")

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"

# ---------- Helpers ----------


def geocode_city_bounds(
    city: str, region: str = "tw", language: str = "zh-TW"
) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]:
    """Return (northeast(lat,lng), southwest(lat,lng), center(lat,lng)) via Geocoding bounds/viewport."""
    params = {
        "address": city,
        "key": API_KEY,
        "language": language,
        "region": region,
    }
    r = requests.get(GEOCODE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        raise RuntimeError(f"Geocoding '{city}' 無結果: {data}")
    res = data["results"][0]
    geometry = res["geometry"]
    viewport = geometry.get("viewport")
    bounds = geometry.get("bounds") or viewport  # 有些城市只有 viewport
    ne = (bounds["northeast"]["lat"], bounds["northeast"]["lng"])
    sw = (bounds["southwest"]["lat"], bounds["southwest"]["lng"])
    center = (geometry["location"]["lat"], geometry["location"]["lng"])
    return ne, sw, center


def degree_steps_for_radius_m(radius_m: int, at_lat: float) -> Tuple[float, float]:
    """
    Convert a search radius in meters to approx degree steps (lat_step, lng_step).
    Add overlap factor (<1) when generating grid to avoid holes.
    """
    km_per_deg_lat = 110.574  # ~
    km_per_deg_lng = 111.320 * math.cos(math.radians(at_lat))
    lat_step_deg = (radius_m / 1000) / km_per_deg_lat
    lng_step_deg = (radius_m / 1000) / km_per_deg_lng
    return lat_step_deg, lng_step_deg


def build_photo_url(photo_reference: str, maxwidth: int = 800) -> str:
    """Build a public photo URL. (Note: serves a redirect on request)"""
    return f"{PHOTO_URL}?maxwidth={maxwidth}&photo_reference={photo_reference}&key={API_KEY}"


def maps_place_url_from_id(place_id: str) -> str:
    """Portable Google Maps link by place_id."""
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def safe_get(d: Dict, path: List[str], default=None):
    for k in path:
        d = d.get(k, {})
    return d or default


def clean_types(types: List[str]) -> List[str]:
    ignore = {"establishment", "point_of_interest", "food"}
    return [t for t in types or [] if t not in ignore]


# ---------- Places Fetchers ----------


def nearby_search_all(
    lat: float, lng: float, radius_m: int, language="zh-TW", type_="cafe"
) -> List[Dict[str, Any]]:
    """
    Run Nearby Search at a single lat/lng with pagination (up to 60 results).
    Returns list of basic place results (no phone/opening hours yet).
    """
    all_results: List[Dict[str, Any]] = []
    params = {
        "key": API_KEY,
        "location": f"{lat},{lng}",
        "radius": radius_m,
        "type": type_,
        "language": language,
    }
    next_token = None
    page = 0

    while True:
        p = dict(params)
        if next_token:
            p["pagetoken"] = next_token
            # next_page_token 需延遲才能生效
            time.sleep(2)

        resp = requests.get(NEARBY_URL, params=p, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            # 有時為 INVALID_REQUEST（通常是 pagetoken 還沒就緒），稍等再試
            if status == "INVALID_REQUEST":
                time.sleep(2)
                continue
            raise RuntimeError(f"NearbySearch 失敗: {status} {data}")

        results = data.get("results", [])
        all_results.extend(results)

        next_token = data.get("next_page_token")
        page += 1
        if not next_token:
            break

        # 對 API 友善一點，避免 QPS 過高
        time.sleep(1)

        # Nearby Search 最多 3 頁
        if page >= 3:
            break

    return all_results


def fetch_details(place_id: str, language="zh-TW") -> Dict[str, Any]:
    """
    Fetch detail fields for a place.
    """
    fields = [
        "place_id",
        "name",
        "formatted_address",
        "formatted_phone_number",
        "international_phone_number",
        "opening_hours/weekday_text",
        "rating",
        "types",
        "url",
        "website",
        "photos",
    ]
    params = {
        "key": API_KEY,
        "place_id": place_id,
        "language": language,
        "fields": ",".join(fields),
    }
    r = requests.get(DETAILS_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        # 某些店家可能無法取回 details，回傳空 dict 不中斷
        return {}
    return data["result"]


# ---------- Main Flow ----------


def crawl_taichung_cafes(
    city_name: str = "台中市",
    radius_m: int = 1500,
    overlap: float = 0.6,
    language: str = "zh-TW",
) -> List[Dict[str, Any]]:
    """
    - Geocode city bounds
    - Build grid with given radius & overlap
    - NearbySearch each grid point (type=cafe) with pagination
    - Deduplicate by place_id
    - Enrich with Place Details
    """
    if not API_KEY:
        raise RuntimeError("請先設定環境變數 GOOGLE_API_KEY")

    ne, sw, center = geocode_city_bounds(city_name, language=language)
    ne_lat, ne_lng = ne
    sw_lat, sw_lng = sw

    # 以城市中心緯度估計經緯度步長
    lat_step, lng_step = degree_steps_for_radius_m(radius_m, center[0])
    lat_step *= overlap
    lng_step *= overlap

    # 產生網格點
    lat_points: List[float] = []
    lng_points: List[float] = []

    lat = sw_lat
    while lat <= ne_lat:
        lat_points.append(lat)
        lat += lat_step

    lng = sw_lng
    while lng <= ne_lng:
        lng_points.append(lng)
        lng += lng_step

    print(
        f"Geocoded '{city_name}' bounds NE={ne} SW={sw}, grid={len(lat_points)}x{len(lng_points)}"
    )

    # 逐點搜集
    basic_places: Dict[str, Dict[str, Any]] = {}
    for i, la in enumerate(lat_points):
        for j, ln in enumerate(lng_points):
            results = nearby_search_all(
                la, ln, radius_m, language=language, type_="cafe"
            )
            for r in results:
                pid = r.get("place_id")
                if not pid:
                    continue
                # 僅保留最早抓到的（附近點資料相同）
                if pid not in basic_places:
                    basic_places[pid] = r
            # 控制頻率，避免過快
            time.sleep(0.5)

    print(f"Found unique places: {len(basic_places)}")

    # 補齊 Details
    output_rows: List[Dict[str, Any]] = []
    for idx, pid in enumerate(basic_places.keys(), 1):
        d = fetch_details(pid, language=language) or {}
        name = d.get("name") or basic_places[pid].get("name")
        address = d.get("formatted_address") or basic_places[pid].get("vicinity")
        phone = (
            d.get("formatted_phone_number") or d.get("international_phone_number") or ""
        )
        rating = d.get("rating", basic_places[pid].get("rating", ""))
        types = clean_types(d.get("types") or basic_places[pid].get("types") or [])
        opening_hours = ""
        oh = safe_get(d, ["opening_hours", "weekday_text"])
        if isinstance(oh, list):
            opening_hours = " | ".join(oh)

        # 圖片（取第一張）
        photos = d.get("photos") or basic_places[pid].get("photos") or []
        photo_url = ""
        if photos:
            ref = photos[0].get("photo_reference")
            if ref:
                photo_url = build_photo_url(ref, maxwidth=800)

        maps_url = d.get("url") or maps_place_url_from_id(pid)

        row = {
            "name": name or "",
            "address": address or "",
            "phone": phone or "",
            "opening_hours": opening_hours,
            "rating": rating if rating is not None else "",
            "types": ", ".join(types),
            "photo_url": photo_url,
            "maps_url": maps_url,
        }
        output_rows.append(row)

        # 對 API 友善一點
        time.sleep(0.25)
        if idx % 50 == 0:
            print(f"Enriched {idx}/{len(basic_places)}")

    return output_rows


def save_csv(rows: List[Dict[str, Any]], out_path: str):
    if not rows:
        print("No data to save.")
        return
    cols = [
        "name",
        "address",
        "phone",
        "opening_hours",
        "rating",
        "types",
        "photo_url",
        "maps_url",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {out_path} ({len(rows)} rows)")


def parse_args():
    ap = argparse.ArgumentParser(
        description="Crawl Taichung City cafes via Google Maps APIs"
    )
    ap.add_argument(
        "--city", default="台中市", help="City name for geocoding (default: 台中市)"
    )
    ap.add_argument(
        "--radius",
        type=int,
        default=1500,
        help="Nearby Search radius in meters (default: 1500)",
    )
    ap.add_argument(
        "--overlap",
        type=float,
        default=0.6,
        help="Grid overlap factor <1 (default: 0.6)",
    )
    ap.add_argument(
        "--lang", default="zh-TW", help="Language for API responses (default: zh-TW)"
    )
    ap.add_argument(
        "--out",
        default="taichung_cafes.csv",
        help="Output CSV path (default: taichung_cafes.csv)",
    )
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    rows = crawl_taichung_cafes(
        city_name=args.city,
        radius_m=args.radius,
        overlap=args.overlap,
        language=args.lang,
    )
    save_csv(rows, args.out)
