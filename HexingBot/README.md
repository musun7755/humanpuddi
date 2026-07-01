# HexingBot 正式使用方式

HexingBot 是 Windows 本機半自動 Threads 角色產文工具，帳號為 `@humanpuddi`。系統只負責每日產生候選與 Discord 手機重新發想；不連接 Threads API、不自動發布、不回覆留言，也不上傳圖片。

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
   DISCORD_WEBHOOK_LOG=
   DISCORD_WEBHOOK_ERROR=
   DISCORD_WEBHOOK_PUBLISHED=
   DISCORD_WEBHOOK_REVIEW=
   GEMINI_API_KEY=
   ```

`DISCORD_WEBHOOK_REVIEW` 是完整候選的唯一輸出方式。Discord Bot 只傳控制訊息並處理「重新發想」。Bot 必須在 review 頻道有「檢視頻道、傳送訊息」權限。Webhook URL、Bot Token 與 API Key 都不可公開。

## 每日正式流程

1. 雙擊 `bat\啟動DiscordBot.bat`，保持 Bot 開啟。
2. Windows Task Scheduler 每天執行 `bat\今日產文.bat`。
3. HexingBot 生成 3 則候選，寫入 `posts\pending\YYYY-MM-DD.md`，並透過 review webhook 以三個 Discord Embed 框傳送文案、Flow prompt、文案分類標籤及靈感／流行方向。
4. 完整候選後只會出現一則控制訊息，且只有「重新發想」按鈕。
5. 不滿意時在手機 Discord 按「重新發想」；不需填理由。新一輪會避開既有主題、句型與笑點。
6. 每日最多重新發想 5 次。達上限後不再呼叫 LLM，Discord 會提示：`今日已重新發想 5 次，建議先挑一個方向或明天再產。`
7. 滿意後，手動到 Flow 使用固定臉照生圖，再手動發布 Threads。
8. 按鈕失效時，可在電腦雙擊 `bat\重想今日.bat`。

同一天已存在原始候選時，`今日產文.bat` 會停止，避免重複花費 API。重想檔依序存為 `YYYY-MM-DD_retry1.md` 至 `_retry5.md`。

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

雙擊 `bat\設定DiscordBot開機啟動.bat`，會建立目前使用者登入時執行的 `HexingBot Discord Bot` 工作。這是「登入時」啟動，不是尚未登入前的 Windows 服務；本機用途較穩定，也通常不需要系統管理員權限。

若系統政策拒絕建立工作，請以系統管理員身分執行。Bot 必須持續運行，手機上的既有按鈕才會有回應。修改程式或 `.env` 後需重新啟動 Bot。

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
- 本機備用 `重想今日.bat` 與 Discord 按鈕共用相同的每日 5 次上限。
