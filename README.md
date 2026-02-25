# YunTech Course Bot

> 一個專為國立雲林科技大學 (NYUST) 學生設計的搶課機器人

## 功能特色
- **自動監控名額**：定時查詢目標課程是否釋出名額。
- **自動加選**：一發現有餘額，自動登入系統並加選。
- **Discord 通知**：透過 Webhook 傳送通知。
- **多帳號管理**：支援同時設定多位使用者的帳號與其對應的課程清單。
- **熱更新支援**：修改 `users.json` 後無需重啟容器，系統會自動在下次檢查時套用新設定。

## 系統需求
- Docker 與 Docker Compose (推薦)
- 或是 Python 3.12 以上版本 (若於本地端執行)

## 安裝與設定方式

### 1. 環境變數設定 (`.env`)
複製 `.env.example` 並重新命名為 `.env`
```bash
cp .env.example .env
```

編輯 `.env` 檔案：
```env
# Discord Webhook (選填)
DISCORD_WEBHOOK_URL=your_discord_webhook_url_here

# 課程查詢間隔（秒）
CRON_INTERVAL_SECONDS=30
```
> 系統會根據是否有填寫 Webhook 自動決定是否啟動通知。

### 2. 使用者與課程設定 (`users.json`)
在專案跟目錄新增 `users.json` 檔案，設定單一帳號以及要監控的課程代碼：
```json
[
    {
        "account": "B11112159",
        "password": "your_password",
        "courses": [
            "0249",
            "2176"
        ]
    }
]
```
- `account`: 單一帳/學號
- `password`: 單一密碼
- `courses`: 加選課程代碼

> 程式會自動定期重新讀取 `users.json`。在系統運行期間可直接修改，無需重啟。

## 使用方式

### 使用 Docker (建議)
1. 在專案根目錄下執行背景啟動容器：
   ```bash
   docker compose up -d --build
   ```
2. 檢查機器人運行日誌：
   ```bash
   docker compose logs -f bot
   ```
3. 停止系統：
   ```bash
   docker compose down
   ```

### 本地執行 (Python)
建議使用 `uv` 進行管理：
1. 安裝依賴套件：
   ```bash
   uv sync
   ```
2. 執行系統：
   ```bash
   uv run python -m app.main
   ```

## 注意事項
- **驗證碼辨識**：專案內含 OCR 模組，會自動辨識登入與加選時的驗證碼。若辨識失敗系統會自動重讀圖片嘗試，直到成功辨識為止。
- **加選成功後自動移除監控**：課程加選成功後，系統會自動從 `users.json` 中移除該課程，重啟 bot 後也不會重複加選。
