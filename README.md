# Taichung Cafes Crawler

使用 **Google Maps Platform (Places API + Details API + Photos + Geocoding)** 抓取 **台中市所有咖啡廳**的資料，輸出成 CSV。

## 功能特色

- 自動定位 **台中市邊界**，並以 **網格 + Nearby Search 分頁** 覆蓋全市
- 去重後取得唯一咖啡廳清單
- 使用 Place Details API 補齊資訊：
  - 店名 (name)
  - 地址 (address)
  - 電話 (phone)
  - 營業時間 (opening_hours)
  - 評分 (rating)
  - 特色分類 (types)
  - 圖片連結 (photo_url, Google Photos API)
  - 導航地圖連結 (maps_url)
- 最終輸出 CSV 檔

## 安裝需求

- Python 3.8+
- 安裝套件：

```bash
pip install requests pandas
```

## 取得 API Key

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立專案並啟用以下 API：
   - Places API
   - Geocoding API
   - Place Details API
   - Place Photos API
3. 建立 **API Key** 並綁定計費帳號。
4. 建議將金鑰存成環境變數：

Linux / macOS:

```bash
export GOOGLE_API_KEY="你的API金鑰"
```

Windows PowerShell:

```powershell
setx GOOGLE_API_KEY "你的API金鑰"
```

## 使用方式

執行 `main.py`：

```bash
python main.py \
  --city "台中市" \
  --radius 1500 \
  --overlap 0.6 \
  --lang zh-TW \
  --out taichung_cafes.csv
```

### 參數說明

| 參數        | 預設值             | 說明                                                        |
| ----------- | ------------------ | ----------------------------------------------------------- |
| `--city`    | 台中市             | 要抓取的城市名稱                                            |
| `--radius`  | 1500               | 每個網格點的搜尋半徑（公尺）                                |
| `--overlap` | 0.6                | 網格重疊比例（越小 → 網格越密 → 覆蓋更完整但 API 次數增加） |
| `--lang`    | zh-TW              | API 回傳語言                                                |
| `--out`     | taichung_cafes.csv | 輸出檔名                                                    |

## 輸出欄位

輸出 CSV 內容包含以下欄位：

| 欄位          | 說明                      |
| ------------- | ------------------------- |
| name          | 店名                      |
| address       | 地址                      |
| phone         | 電話                      |
| opening_hours | 營業時間 (一週七天文字串) |
| rating        | Google Maps 評分          |
| types         | 特色分類                  |
| photo_url     | Google Maps 照片 API URL  |
| maps_url      | Google Maps 導航連結      |

## 注意事項

- API Key 請務必設 **使用限制**，避免被盜用
- 首次建議先抓取「都會區」測試，觀察 API 回傳結果
- `photo_url` 只是一個帶金鑰的 API URL，瀏覽器請求時會轉址到實際圖片檔案
