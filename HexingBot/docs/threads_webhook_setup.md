# Threads Webhook 即時留言通知設定

本功能只接收 Threads webhook 的 replies / mentions 事件，並將作者與留言內容通知到 Discord。不會呼叫 Gemini 產生草稿、不會呼叫 Threads API 回覆、不會定時檢查、不會讀取追蹤者貼文，也不處理私訊。

## 事前準備

1. 在 Meta for Developers 建立支援 Threads API 的 app，完成 Threads 使用者授權，取得具備讀取回覆、管理回覆所需權限的 long-lived access token。
2. 將 `.env.example` 的設定補入 `.env`：

   ```dotenv
   THREADS_APP_SECRET=
   THREADS_WEBHOOK_VERIFY_TOKEN=請自行設定一段難猜的字串
   THREADS_WEBHOOK_PORT=8787
   DISCORD_BOT_TOKEN=
   DISCORD_REVIEW_CHANNEL_ID=
   ```

   Discord Bot 必須能在 review 頻道檢視頻道、傳送訊息、嵌入連結與使用應用程式命令。錯誤通知沿用既有 `DISCORD_WEBHOOK_ERROR`。

## Windows 與 Cloudflare Tunnel

本機 webhook 沒有公開 HTTPS 位址，因此需安裝 `cloudflared`。啟動順序如下：

1. 執行 `bat\啟動DiscordBot.bat`。
2. 執行 `bat\啟動ThreadsWebhook.bat`。
3. 另開終端機執行：

   ```powershell
   cloudflared tunnel --url http://localhost:8787
   ```

4. 複製 Cloudflare 顯示的 `https://...trycloudflare.com`，在 Meta Developer 後台將 webhook callback URL 設為 `https://...trycloudflare.com/webhook`，verify token 填入與 `THREADS_WEBHOOK_VERIFY_TOKEN` 完全相同的值。
5. 在 Meta 後台訂閱 Threads 的 replies / mentions 相關 webhook 欄位並完成驗證。

Quick Tunnel URL 每次重啟可能改變；正式長期運行建議建立 named tunnel 與固定網域。Cloudflare Tunnel 必須指向 `.env` 中 `THREADS_WEBHOOK_PORT` 的同一個 port。

## 驗收

驗證 callback 時 server 應回傳 Meta 傳入的 challenge。驗證完成後，@humanpuddi 的 Threads 貼文有新留言時，Discord review 頻道會收到作者與可直接複製的留言內容，不附回覆按鈕。

處理紀錄位於 `data\reply_log.csv`，成功通知的狀態為 `notified`。相同 reply ID 只通知一次。若 webhook 簽章驗證或 Discord 呼叫失敗，會送到 Discord error 頻道；請確認 `DISCORD_WEBHOOK_ERROR` 已設定。
