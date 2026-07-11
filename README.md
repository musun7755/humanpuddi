# HexingBot 正式使用方式

HexingBot 是 `@humanpuddi` 的半自動 Threads 角色產文與留言通知工具。Telegram 負責候選、留言審核、重新發想、發布結果與錯誤通知；Discord 只保留人工圖片／限時貼文發布指令。

## 第一次設定

1. 安裝 Python，並勾選 **Add Python to PATH**。
2. 在專案根目錄執行：

   ```bat
   python -m pip install -r requirements.txt
   copy .env.example .env
   ```

3. 編輯 `.env`：

   ```dotenv
   DISCORD_BOT_TOKEN=
   DISCORD_REVIEW_CHANNEL_ID=
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_CHAT_ID=
   GEMINI_API_KEY=
   THREADS_APP_SECRET=
   THREADS_WEBHOOK_VERIFY_TOKEN=
   ```

Discord Bot Token 只供 `/發布threads`、`/發布限時threads` 使用。Telegram Bot Token、Discord Bot Token 與 API Key 都不可公開。

自動回覆由 Render webhook 執行，不需要本機 Discord Bot 常駐。Discord 只提供 `/自動回覆開啟`、`/自動回覆關閉`、`/自動回覆狀態` 控制 Render 狀態。本機與 Render Environment 必須設定相同的 `AUTO_REPLY_CONTROL_SECRET`；服務啟動、無狀態或重新部署時預設開啟，敏感或不確定留言仍送 Telegram 人工處理。若真的要讓服務啟動時不要自動開啟，可在 Render 設 `AUTO_REPLY_START_ENABLED=0`。

自動回覆預設不延遲，收到安全留言會立即嘗試回覆。若之後需要限速，可在 Render Environment 設 `AUTO_REPLY_INTERVAL_SECONDS=60` 之類的秒數。

## Threads 留言通知

正式留言通知流程：

```text
Threads replies webhook → Render → Telegram

本機執行
`bat\啟動TelegramBot.bat` 後可使用「產生回覆草稿／批准發布／重想一個／手動輸入／略過」。
每日三則候選、重新發想、限時貼文候選、留言審核及所有 log/error/published/review 通知都只送 Telegram。
```

Render 服務網址：

```text
https://humanpuddi.onrender.com
```

Meta Developer 的設定：

```text
Callback URL: https://humanpuddi.onrender.com/webhook
Verify Token: hexing_threads_webhook_2026
Moderate subscription: replies
Mutual TLS: No
```

Render 的設定：

```text
Build Command: pip install -r requirements.txt
Start Command: python -u src/threads_webhook_server.py
```

Render Environment 必須設定 `THREADS_APP_SECRET`、`THREADS_WEBHOOK_VERIFY_TOKEN`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`GEMINI_API_KEY`、`THREADS_ACCESS_TOKEN`、`THREADS_USER_ID` 與 `AUTO_REPLY_CONTROL_SECRET`。秘密資料只放在 Render Environment 或本機 `.env`，不可上傳 GitHub。

收到新留言後，Render 會先嘗試安全自動回覆。若模型判定不適合自動回覆，或產生/發布失敗，才改送 Telegram 人工處理。

若使用 Render 免費方案，服務閒置約 15 分鐘可能休眠，第一則留言可能遇到冷啟動延遲。雙擊 `bat\設定Render保活排程.bat` 可建立每 10 分鐘喚醒一次 Render 的 Windows 排程；紀錄寫在 `logs\render_keepalive.log`。這只能在電腦開機且可連網時保活。

## Discord 人工批准發布 Threads 圖片貼文

本機 Discord Bot 提供 `/發布threads` 指令。於 review 頻道輸入指令並依序附加 1～20 張 JPG 或 PNG，接著在彈出的輸入框貼上最終文章，並可選填一個 Threads 主題；原始換行會保留。單張圖片會發布為一般圖片貼文，多張圖片會發布為 carousel。Bot 會先顯示文字、主題與全部圖片預覽，只有按下「批准發布」後，本機才會呼叫 Threads API；按「取消」不會發布。

此功能需要在本機 `.env` 設定 `THREADS_ACCESS_TOKEN` 與 `THREADS_USER_ID`，且 Discord Bot 必須正在執行。圖片會由 Meta 透過 Discord CDN 的公開 HTTPS 網址下載，Discord 網址不會顯示在 Threads 貼文中。預覽按鈕有效 15 分鐘，Bot 重啟後尚未處理的預覽會失效。

## Threads 限時貼文

在 review 頻道使用 `/發布限時threads`，可輸入純文字與選填主題；確認預覽後按「發布限時貼文」才會送出。此功能使用 Threads Ghost post，貼文會在 24 小時後自動消失。

`HexingBot限時候選-中午` 與 `HexingBot限時候選-晚上` Windows 排程會在每天 12:30、20:00 各產生一則候選。Telegram 提供「發布限時貼文」與「略過」；略過不會呼叫 Threads API。

## 每日正式流程

1. 雙擊 `bat\啟動TelegramBot.bat`；需要圖片發布時才啟動 Discord Bot。
2. Windows Task Scheduler 每天執行 `bat\今日產文.bat`。
3. HexingBot 生成 3 則候選並傳送到 Telegram。
4. 完整候選後只會出現一則控制訊息，且只有「重新發想」按鈕。
5. 不滿意時在 Telegram 按「重新發想」。
6. 可依需要繼續重新發想，每次都會保留新的候選檔。
7. 滿意後，手動到 Flow 使用固定臉照生圖，再手動發布 Threads。
8. 按鈕失效時，可在電腦雙擊 `bat\重想今日.bat`。

同一天已存在原始候選時，`今日產文.bat` 會停止，避免重複花費 API。重想檔會依序存為 `YYYY-MM-DD_retry1.md`、`_retry2.md`，持續自動遞增。

## 設定每日產文排程

最簡單方式是雙擊 `bat\設定每日產文排程.bat`，輸入 `HH:mm` 格式時間。腳本會建立 `HexingBot每日產文` 工作；要改時間，重新執行腳本並輸入新時間即可覆蓋。

也可手動設定：

1. 開啟「工作排程器」→「建立基本工作」。
2. 觸發程序選「每天」，設定需要的時間。
3. 動作選「啟動程式」。
4. 程式填 `F:\HexingBot\bat\今日產文.bat`，引數填 `--scheduled`，起始位置填 `F:\HexingBot`。
5. 若專案搬家，必須改成新的完整路徑。

一般使用者權限通常足夠。若公司電腦政策拒絕建立工作，請右鍵以系統管理員身分執行設定 bat。電腦在設定時間必須已開機；可在工作內容的「條件」啟用「喚醒電腦以執行這項工作」。

## 設定 Discord Bot 登入時啟動

雙擊 `bat\設定DiscordBot開機啟動.bat`，會建立目前使用者登入時執行的 `HexingBot Discord Bot` 工作，並透過 `pythonw.exe` 在背景運行。啟動後可在 Windows 右下角看到赫湦圖示；滑鼠移上去會顯示連線狀態，右鍵可重新啟動 Bot、查看紀錄或結束。程式會阻止重複啟動。這是「登入時」啟動，不是尚未登入前的 Windows 服務；本機用途較穩定，也通常不需要系統管理員權限。

若系統政策拒絕建立工作，請以系統管理員身分執行。Bot 必須持續運行，手機上的既有按鈕才會有回應。修改程式或 `.env` 後需重新啟動 Bot。

若電腦閒置後 Bot 容易消失，雙擊 `bat\設定DiscordBot保活排程.bat`，會建立 `HexingBot Discord Bot Watchdog` 工作，每 5 分鐘嘗試啟動一次。若 Bot 已在執行，程式會安靜結束，不會重複開啟或跳提示。

## 設定 Render 保活

雙擊 `bat\設定Render保活排程.bat`，會建立 `HexingBot Render Keepalive` 工作，每 10 分鐘呼叫 Render 的 `/health`，並在有 `AUTO_REPLY_CONTROL_SECRET` 時順便檢查 `/auto-reply` 狀態。這不會自動改成開啟或關閉，只負責避免 Render 免費服務睡著。

若要手動測試，雙擊 `bat\啟動Render保活.bat`，再看 `logs\render_keepalive.log`。

## Discord 畫面規則

每輪只包含：

1. 一組完整候選內容：A／B／C 各一個 Discord Embed 框。
2. 一則固定控制訊息：

   ```text
   HexingBot 今日候選已完成。
   不滿意就按「重新發想」，我會重新生成 3 則候選。
   本流程不會自動發布、不會自動回覆留言、不會上傳圖片。
   ```

控制訊息只有「重新發想」。沒有今日產文、選 A/B/C、微調、幫我想更多、狀態、重新載入候選、slash command 或文字指令。

## 候選內容

每輪固定產生 A／B／C 三則。每框只有可直接複製貼上的分行文案、Flow prompt、文案分類標籤及靈感／流行方向。內容仍必須原創，不使用真實台灣地名、歌詞、封面、MV、名人、動漫、影劇、遊戲或他人作品；Public Mode 不戀愛、不曖昧、不營造男友感。

## 常見問題

- `今日產文.bat` 顯示候選已存在：這是防重複保護，請使用「重新發想」。
- Bot 無法登入：檢查 `DISCORD_BOT_TOKEN` 與 `DISCORD_REVIEW_CHANNEL_ID`。
- 候選有送達但沒有按鈕：檢查 Bot token、頻道權限及 Bot 是否仍在執行。
- Webhook 失敗：檢查 `.env` 對應 URL；候選 Markdown 仍會保留，不要為補通知而重跑原始產文。
- `python` 找不到或缺少套件：重新安裝 Python 並執行 `python -m pip install -r requirements.txt`。
- Threads 留言沒有通知或第一則沒有自動回覆：確認 Render 狀態為 `Live`、Environment 值均已設定，並檢查 Render logs。Render 免費方案可能休眠；可設定 `bat\設定Render保活排程.bat`。
- Meta 無法驗證 callback：先開啟 `https://humanpuddi.onrender.com/`，確認顯示 `HexingBot Threads Webhook is running`，再驗證 `/webhook`。
