# YunTech Course Bot

這是一個專為國立雲林科技大學 (YunTech) 學生設計的自動選課與通知機器人。
主要功能包括自動監測指定課程的剩餘名額，當有空位時自動進行加選，並透過 LINE 傳送即時通知給使用者。

## 功能特色
- **自動監控名額**：定時查詢目標課程是否釋出名額。
- **自動加選**：一發現有餘額，自動登入系統並加選。
- **LINE 機器人通知**：選課成功或系統異常時，透過 LINE 傳送通知。
- **彈性多帳號管理**：支援同時設定多位使用者的帳號與其對應的課程清單。
- **熱更新支援**：修改 `users.json` 後無需重啟容器，系統會自動在下次檢查時套用新設定。

## 系統需求
- Docker 與 Docker Compose (推薦)
- 或是 Python 3.12 以上版本 (若於本地端執行)

## 安裝與設定方式

### 1. 環境變數設定 (`.env`)
複製 `.env.example` 並重新命名為 `.env`，填寫您的 LINE Bot 憑證資訊：
```bash
cp .env.example .env
```

編輯 `.env` 檔案：
```env
# LINE Messaging API 存取權杖 (必填)
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token_here

# LINE 群組 ID (選填，若有需要廣播到群組用)
LINE_GROUP_ID=your_group_id_here

# 檢查課程的時間間隔 (秒)，預設為 30 秒
CRON_INTERVAL_SECONDS=30
```

### 2. 使用者與課程設定 (`users.json`)
編輯 `users.json` 來設定您要掛載的帳號以及目標課程：
```json
[
    {
        "account": "B11112159",
        "password": "your_password",
        "line_user_id": "U791...您的LINE_USER_ID",
        "courses": [
            "0249",
            "2176"
        ]
    }
]
```
- `account`: 雲科大單一入口學號/帳號
- `password`: 單一入口密碼
- `line_user_id`: 接收個別通知的 LINE User ID
- `courses`: 欲監測與加選的課程代碼陣列

> **提示**：程式會自動定期重新讀取 `users.json`。如果在機器人執行期間需要新增或修改課程，只需修改 `users.json` 存檔即可，無須重啟容器。

## 啟動方式

### 使用 Docker (建議)
使用 Docker 可以省去安裝套件的麻煩，並且能在背景穩定執行。

1. 在專案根目錄下執行以下指令在背景啟動容器：
   ```bash
   docker-compose up -d --build
   ```
2. 檢查機器人運行日誌：
   ```bash
   docker-compose logs -f bot
   ```
3. 若要停止機器人：
   ```bash
   docker-compose down
   ```

### 本地執行 (Python)
如果您沒有使用 Docker，也可以直接在系統中執行：

1. 使用 `uv` 或 `pip` 安裝相依套件 (基於 `pyproject.toml`)：
   ```bash
   uv sync  # 或者 pip install -r requirements.txt
   ```
2. 執行主程式：
   ```bash
   python -m app.main
   ```

## 注意事項
- **驗證碼辨識**：專案內含光學字元辨識 (OCR) 模組，來自動辨識選課系統登入時的驗證碼。
- **防封鎖機制**：若連續抓取失敗達到 3 次，系統將自動靜默 3 小時避免被學校伺服器封鎖，並會傳送 LINE 通知告知發生系統異常。
