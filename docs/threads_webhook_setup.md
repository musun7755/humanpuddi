# Threads Webhook 即時留言通知設定

本功能接收 Threads Moderate webhook 的 `replies` 事件。正式環境由 Render 先嘗試安全自動回覆；敏感、不確定、模型失敗或 Threads API 發布失敗時，才改送 Telegram 人工處理。系統不處理私訊。

若 Render 與本機 `.env` 同時設定 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，
可另外啟動 `bat\啟動TelegramBot.bat` 處理人工審核。已自動回覆、發布或略過的留言不能再次處理。Render webhook 每次啟動時會預設開啟自動回覆；若真的要停用這個啟動預設，可在 Render 設 `AUTO_REPLY_START_ENABLED=0`。自動回覆預設不延遲；若需要限速，可在 Render 設 `AUTO_REPLY_INTERVAL_SECONDS` 秒數。

## 事前準備

1. 在 Meta for Developers 建立支援 Threads Webhooks 的 app，將 app 發布為 Live，並訂閱 Moderate 物件的 `replies` 欄位。
2. 將 `.env.example` 的設定補入 `.env`：

   ```dotenv
THREADS_APP_SECRET=
THREADS_WEBHOOK_VERIFY_TOKEN=請自行設定一段難猜的字串
THREADS_WEBHOOK_PORT=8787
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=
THREADS_ACCESS_TOKEN=
THREADS_USER_ID=
AUTO_REPLY_CONTROL_SECRET=
   ```

   `AUTO_REPLY_CONTROL_SECRET` 在本機與 Render 必須相同，供 Discord 指令查詢或切換 Render 的自動回覆狀態。

## Render 正式部署（目前使用方式）

正式環境部署於 Render：

```text
https://humanpuddi.onrender.com
```

GitHub repository 只需包含 webhook 執行所需檔案；不得上傳 `.env`。若 repository 最外層還有一層 `HexingBot`，Render 的 `Root Directory` 設為 `HexingBot`。

Render 設定：

```text
Build Command: pip install -r requirements.txt
Start Command: python src/threads_webhook_server.py
```

在 Render 的 Environment 頁面設定，不要寫入 GitHub：

```dotenv
THREADS_APP_SECRET=
THREADS_WEBHOOK_VERIFY_TOKEN=hexing_threads_webhook_2026
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=
THREADS_ACCESS_TOKEN=
THREADS_USER_ID=
AUTO_REPLY_CONTROL_SECRET=
```

部署顯示 `Live` 後，開啟 `https://humanpuddi.onrender.com/`，應看到 `HexingBot Threads Webhook is running`。Meta Developer 後台填入：

```text
Callback URL: https://humanpuddi.onrender.com/webhook
Verify Token: hexing_threads_webhook_2026
Mutual TLS: No
```

Render 會透過 `PORT` 指定監聽埠，程式已自動支援，不需要在 Render 設定 `THREADS_WEBHOOK_PORT`。

### Render 免費方案限制與保活

- 連續 15 分鐘沒有請求會休眠；下一次 webhook 喚醒服務時可能延遲約一分鐘。
- 免費 workspace 每月共用 750 小時執行時間。
- 本機檔案系統不是永久儲存。服務休眠、重啟或重新部署後，`data/reply_log.csv` 的新增紀錄可能消失，因此 Meta 重送舊事件時可能再次通知。
- 若需要穩定即時通知與永久去重，應升級常駐方案並將紀錄改存持久化資料庫。
- 可雙擊 `bat\設定Render保活排程.bat` 建立每 10 分鐘喚醒一次的 Windows 排程；紀錄位於 `logs\render_keepalive.log`。這只能在電腦開機且可連網時保活。

## Windows 與 Cloudflare Tunnel（僅供本機測試）

本機 webhook 沒有公開 HTTPS 位址，因此需安裝 `cloudflared`。啟動順序如下：

1. 執行 `bat\啟動ThreadsWebhook.bat`。
2. 另開終端機執行：

   ```powershell
   cloudflared tunnel --url http://localhost:8787
   ```

3. 複製 Cloudflare 顯示的 `https://...trycloudflare.com`，在 Meta Developer 後台將 webhook callback URL 設為 `https://...trycloudflare.com/webhook`，verify token 填入與 `THREADS_WEBHOOK_VERIFY_TOKEN` 完全相同的值。
4. 在 Meta 後台訂閱 Moderate 物件的 `replies` 欄位並完成驗證。

Quick Tunnel URL 每次重啟可能改變，只用於本機測試。正式 callback 應維持 Render 網址。Cloudflare Tunnel 必須指向 `.env` 中 `THREADS_WEBHOOK_PORT` 的同一個 port。

## 驗收

驗證 callback 時 server 應回傳 Meta 傳入的 challenge。驗證完成後，@humanpuddi 的 Threads 貼文有新留言時，Render 會先嘗試安全自動回覆；不適合自動回覆時，Telegram 會收到作者、留言內容與「產生回覆草稿」按鈕。

處理紀錄位於 `data\reply_log.csv`，成功自動回覆的狀態為 `auto_replied`，改送人工處理的狀態為 `notified`。相同 reply ID 只處理一次。若 webhook 簽章驗證失敗，會送到 Discord error 頻道；請確認 `DISCORD_WEBHOOK_ERROR` 已設定。
