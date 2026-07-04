"""Telegram Threads 留言審核 Bot（本機 long polling）。"""

from __future__ import annotations

import json
import os
import ctypes
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

import requests
import pystray
from dotenv import load_dotenv
from PIL import Image

from generate_reply_draft import generate_reply_draft
from content_chat import accept as accept_content, end_session as end_content_session
from content_chat import generate as generate_content, load_session as load_content_session
from telegram_notify import send_telegram_message
from threads_publish import publish_ghost_post, publish_reply

ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = ROOT / ".env"
DATA_DIR: Final = ROOT / "data" / "reply_drafts"
GHOST_DIR: Final = ROOT / "data" / "ghost_candidates"
TRAY_ICON_FILE: Final = ROOT / "assets" / "telegram_bot.png"
LOG_FILE: Final = ROOT / "logs" / "telegram_bot.log"
MUTEX_NAME: Final = "Local\\HexingBotTelegramBot"
POLL_TIMEOUT: Final = 25


def config(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"尚未設定 {name}")
    return value


def api(method: str, **payload: Any) -> dict[str, Any]:
    response = requests.post(
        f"https://api.telegram.org/bot{config('TELEGRAM_BOT_TOKEN')}/{method}",
        json=payload,
        timeout=POLL_TIMEOUT + 10,
    )
    if not response.ok:
        raise RuntimeError(f"Telegram {method} HTTP {response.status_code}: {response.text}")
    return response.json().get("result", {})


def path_for(reply_id: str) -> Path:
    return DATA_DIR / f"{reply_id}.json"


def save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = path_for(str(data["reply_id"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load(reply_id: str) -> dict[str, Any]:
    return json.loads(path_for(reply_id).read_text(encoding="utf-8"))


def keyboard(reply_id: str) -> dict[str, Any]:
    prefix = f"tg:reply:"
    return {"inline_keyboard": [
        [{"text": "批准發布", "callback_data": f"{prefix}publish:{reply_id}"},
         {"text": "重想一個", "callback_data": f"{prefix}redo:{reply_id}"}],
        [{"text": "手動輸入", "callback_data": f"{prefix}manual:{reply_id}"},
         {"text": "略過", "callback_data": f"{prefix}skip:{reply_id}"}],
    ]}


def render(data: dict[str, Any], status: str = "尚未發布") -> str:
    return (
        "Threads 留言回覆草稿\n\n"
        f"作者：{data.get('author', '未知')}\n"
        f"留言：{data.get('comment_text', '')}\n\n"
        f"建議回覆：\n{data.get('draft_reply', '')}\n\n"
        f"狀態：{status}\nreply_id：{data['reply_id']}"
    )[:4096]


def edit(chat_id: int, message_id: int, data: dict[str, Any], status: str, buttons: bool = True) -> None:
    api("editMessageText", chat_id=chat_id, message_id=message_id,
        text=render(data, status), reply_markup=keyboard(str(data["reply_id"])) if buttons else {"inline_keyboard": []})


def parse_source(text: str, reply_id: str) -> tuple[str, str, str]:
    author = "未知"
    comment = ""
    post_text = ""
    for line in text.splitlines():
        if line.startswith("作者："):
            author = line.split("：", 1)[1].strip()
        elif line.startswith("內容："):
            comment = line.split("：", 1)[1].strip()
        elif line.startswith("原貼文："):
            post_text = line.split("：", 1)[1].strip()
    return author, comment, post_text


def fetch_reply_context(reply_id: str) -> tuple[str, str]:
    url = os.getenv("RENDER_CONTROL_URL", "https://humanpuddi.onrender.com").strip().rstrip("/")
    secret = os.getenv("AUTO_REPLY_CONTROL_SECRET", "").strip()
    if not secret:
        return "", ""
    response = requests.get(
        f"{url}/reply-context",
        params={"id": reply_id},
        headers={"Authorization": f"Bearer {secret}"},
        timeout=30,
    )
    if not response.ok:
        return "", ""
    data = response.json()
    return str(data.get("post_text", "")).strip(), str(data.get("conversation_text", "")).strip()


def answer(callback_id: str, text: str = "") -> None:
    api("answerCallbackQuery", callback_query_id=callback_id, text=text[:200], show_alert=False)


def content_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[
        {"text": "重想一版", "callback_data": "tg:content:rethink:current"},
        {"text": "採用存檔", "callback_data": "tg:content:accept:current"},
    ], [{"text": "結束討論", "callback_data": "tg:content:end:current"}]]}


def content_text(data: dict[str, Any]) -> str:
    return (f"文案討論｜{data['topic']}\n\n文案\n{data['thread_text']}\n\nFlow prompt\n{data['flow_prompt']}\n\n方向：{data['note']}\n\n直接傳訊息即可繼續修改")[:4096]


def handle_callback(query: dict[str, Any], manual: dict[int, str]) -> None:
    callback_id = str(query.get("id", ""))
    parts = str(query.get("data", "")).split(":", 3)
    message = query.get("message") or {}
    chat_id = int((message.get("chat") or {}).get("id", 0))
    message_id = int(message.get("message_id", 0))
    if len(parts) != 4 or parts[0] != "tg":
        answer(callback_id, "無效操作"); return
    section, action, item_id = parts[1], parts[2], parts[3]
    if str(chat_id) != config("TELEGRAM_CHAT_ID"):
        answer(callback_id, "未授權"); return
    if section == "content":
        try:
            if action == "rethink":
                answer(callback_id, "正在重想…")
                api("editMessageText", chat_id=chat_id, message_id=message_id, text="正在重想文案與 Flow prompt…")
                data = generate_content(chat_id, rethink=True)
                api("editMessageText", chat_id=chat_id, message_id=message_id, text=content_text(data), reply_markup=content_keyboard())
            elif action == "accept":
                path = accept_content(chat_id); answer(callback_id, "已採用存檔")
                api("editMessageText", chat_id=chat_id, message_id=message_id, text=f"已採用並存檔\n{path.name}")
            elif action == "end":
                end_content_session(chat_id); answer(callback_id, "已結束")
                api("editMessageText", chat_id=chat_id, message_id=message_id, text="文案討論已結束，不會發布。")
            else: answer(callback_id, "不支援的操作")
        except Exception as exc:
            try: answer(callback_id, f"失敗：{exc}")
            except Exception: pass
            api("sendMessage", chat_id=chat_id, text=f"文案處理失敗：{exc}")
        return
    if section == "daily" and action == "regenerate":
        answer(callback_id, "正在重新產生今日候選…")
        api("editMessageText", chat_id=chat_id, message_id=message_id,
            text="正在重新產生今日 3 則候選…", reply_markup={"inline_keyboard": []})
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "regenerate_today.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        status = "已重新產生 3 則候選。" if result.returncode in {0, 2} else f"重新產生失敗：{(result.stderr or result.stdout)[-500:]}"
        api("editMessageText", chat_id=chat_id, message_id=message_id, text=status)
        return
    if section == "ghost":
        answer(callback_id, "正在處理…")
        path = GHOST_DIR / f"{item_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != "pending":
            api("editMessageText", chat_id=chat_id, message_id=message_id,
                text=f"此限時貼文已處理：{data.get('status')}")
            return
        if action == "skip":
            data["status"] = "skipped"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            api("editMessageText", chat_id=chat_id, message_id=message_id,
                text=f"限時貼文已略過\n\n{data.get('text', '')}")
            return
        if action == "publish":
            api("editMessageText", chat_id=chat_id, message_id=message_id,
                text=f"正在發布限時貼文…\n\n{data.get('text', '')}")
            post_id = publish_ghost_post(str(data.get("text", "")))
            data["status"] = "published"; data["threads_post_id"] = post_id
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            api("editMessageText", chat_id=chat_id, message_id=message_id,
                text=f"限時貼文已發布｜ID：{post_id}\n\n{data.get('text', '')}")
            return
    if section != "reply" or not item_id.isdigit():
        answer(callback_id, "無效操作"); return
    reply_id = item_id
    try:
        if action == "draft":
            answer(callback_id, "正在產生草稿…")
            path = path_for(reply_id)
            if path.exists():
                data = load(reply_id)
            else:
                author, comment, post_text = parse_source(str(message.get("text", "")), reply_id)
                conversation_text = ""
                if not post_text:
                    post_text, conversation_text = fetch_reply_context(reply_id)
                result = generate_reply_draft(author, comment, post_text=post_text, conversation_text=conversation_text)
                if not result.get("safe_to_draft"):
                    api("sendMessage", chat_id=chat_id,
                        text=f"這則留言建議人工判斷：{result.get('reason', '請手動處理')}")
                    return
                data = {"reply_id": reply_id, "author": author, "comment_text": comment, "post_text": post_text, "conversation_text": conversation_text,
                        "draft_reply": str(result["draft_reply"]), "status": "pending"}
                save(data)
            edit(chat_id, message_id, data, "尚未發布")
            return
        data = load(reply_id)
        if data.get("status") != "pending":
            answer(callback_id, f"已處理：{data.get('status')}"); return
        if action == "redo":
            answer(callback_id, "正在重新產生草稿…")
            edit(chat_id, message_id, data, "正在重新產生草稿…", False)
            result = generate_reply_draft(str(data.get("author", "未知")), str(data.get("comment_text", "")),
                                          post_text=str(data.get("post_text", "")),
                                          conversation_text=str(data.get("conversation_text", "")),
                                          previous_draft=str(data.get("draft_reply", "")))
            if not result.get("safe_to_draft"):
                edit(chat_id, message_id, data, str(result.get("reason", "建議人工判斷")), True); return
            data["draft_reply"] = str(result["draft_reply"]); save(data)
            edit(chat_id, message_id, data, "已重想｜尚未發布"); return
        if action == "manual":
            manual[chat_id] = reply_id
            answer(callback_id, "請直接傳送你要使用的回覆文字"); return
        if action == "skip":
            data["status"] = "skipped"; save(data)
            edit(chat_id, message_id, data, "已略過，不會發布", False); answer(callback_id, "已略過"); return
        if action == "publish":
            answer(callback_id, "正在發布到 Threads…")
            data["status"] = "publishing"; save(data)
            edit(chat_id, message_id, data, "正在發布到 Threads…", False)
            try:
                post_id = publish_reply(
                    reply_id,
                    str(data.get("draft_reply", "")),
                    author=str(data.get("author", "")),
                    comment_text=str(data.get("comment_text", "")),
                    post_text=str(data.get("post_text", "")),
                    conversation_text=str(data.get("conversation_text", "")),
                    source="telegram_human_approved",
                )
            except Exception:
                data["status"] = "pending"; save(data)
                edit(chat_id, message_id, data, "發布失敗，可再次操作", True)
                raise
            data["status"] = "published"; data["threads_reply_id"] = post_id; save(data)
            edit(chat_id, message_id, data, f"已發布到 Threads｜回覆 ID：{post_id}", False); return
        answer(callback_id, "不支援的操作")
    except Exception as exc:
        try: answer(callback_id, f"失敗：{exc}")
        except Exception: pass


def handle_message(message: dict[str, Any], manual: dict[int, str]) -> None:
    chat_id = int((message.get("chat") or {}).get("id", 0))
    if str(chat_id) != config("TELEGRAM_CHAT_ID"):
        return
    text = str(message.get("text", "")).strip()
    if not text:
        return
    if text in {"/結束文案", "/endcopy"}:
        end_content_session(chat_id); api("sendMessage", chat_id=chat_id, text="文案討論已結束，不會發布。"); return
    if text.startswith("/文案") or text.startswith("/copy"):
        topic = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
        if not topic:
            api("sendMessage", chat_id=chat_id, text="請這樣輸入：\n/文案 赫湦第一次自己煮泡麵，結果水加太少"); return
        api("sendMessage", chat_id=chat_id, text="正在依題材產生文案與 Flow prompt…")
        try:
            data = generate_content(chat_id, topic=topic)
            api("sendMessage", chat_id=chat_id, text=content_text(data), reply_markup=content_keyboard())
        except Exception as exc: api("sendMessage", chat_id=chat_id, text=f"產生失敗：{exc}")
        return
    if load_content_session(chat_id) and chat_id not in manual:
        api("sendMessage", chat_id=chat_id, text="正在依你的意見修改…")
        try:
            data = generate_content(chat_id, feedback=text)
            api("sendMessage", chat_id=chat_id, text=content_text(data), reply_markup=content_keyboard())
        except Exception as exc: api("sendMessage", chat_id=chat_id, text=f"修改失敗：{exc}")
        return
    if chat_id not in manual:
        return
    reply_id = manual.pop(chat_id)
    data = load(reply_id)
    if data.get("status") != "pending":
        api("sendMessage", chat_id=chat_id, text="這則留言已經處理。"); return
    data["draft_reply"] = text; save(data)
    api("sendMessage", chat_id=chat_id, text=render(data, "已手動修改｜尚未發布"), reply_markup=keyboard(reply_id))


def poll_updates(stop_event: threading.Event) -> None:
    offset = 0
    manual: dict[int, str] = {}
    while not stop_event.is_set():
        try:
            result = api("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                         allowed_updates=["message", "callback_query"])
            for update in result if isinstance(result, list) else []:
                offset = max(offset, int(update["update_id"]) + 1)
                if update.get("callback_query"):
                    handle_callback(update["callback_query"], manual)
                elif update.get("message"):
                    handle_message(update["message"], manual)
        except KeyboardInterrupt:
            stop_event.set()
            return
        except Exception as exc:
            message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [Telegram] {exc}\n"
            print(message, end="")
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as file:
                file.write(message)
            stop_event.wait(5)


class TrayController:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.restart_requested = False
        image = Image.open(TRAY_ICON_FILE).convert("RGBA")
        self.icon = pystray.Icon(
            "HexingTelegramBot",
            image,
            "HexingBot Telegram｜已連線",
            menu=pystray.Menu(
                pystray.MenuItem("狀態：已連線", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("重新啟動 Bot", self.restart),
                pystray.MenuItem("查看執行紀錄", self.open_log),
                pystray.MenuItem("結束", self.exit),
            ),
        )

    def restart(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        self.restart_requested = True
        self.stop_event.set()
        self.icon.stop()

    def open_log(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.touch(exist_ok=True)
        os.startfile(LOG_FILE)

    def exit(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        self.stop_event.set()
        self.icon.stop()


def main() -> int:
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(
            None, "Telegram Bot 已經在右下角執行中。", "HexingBot", 0x40
        )
        ctypes.windll.kernel32.CloseHandle(mutex)
        return 0
    load_dotenv(ENV_FILE, override=True)
    config("TELEGRAM_BOT_TOKEN"); config("TELEGRAM_CHAT_ID")
    if not TRAY_ICON_FILE.exists():
        print(f"[失敗] 找不到系統匣圖示：{TRAY_ICON_FILE}")
        return 1
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    tray = TrayController(stop_event)
    worker = threading.Thread(target=poll_updates, args=(stop_event,), daemon=True)
    worker.start()
    print("[完成] Telegram 審核 Bot 已啟動；右下角系統匣可查看狀態。")
    try:
        send_telegram_message(
            "HexingBot Telegram Bot 已啟動。\n"
            "候選、留言審核、文案討論、重新發想及系統通知服務已連線。\n"
            "傳送 /文案 加上題材，即可開始多輪討論。"
        )
    except Exception as exc:
        print(f"[Telegram] 啟動通知失敗：{exc}")
    threading.Timer(
        1.0,
        lambda: tray.icon.notify("Telegram Bot 已連線。", "HexingBot"),
    ).start()
    tray.icon.run()
    stop_event.set()
    worker.join(timeout=POLL_TIMEOUT + 2)
    ctypes.windll.kernel32.CloseHandle(mutex)
    if tray.restart_requested:
        os.execl(sys.executable, sys.executable, str(Path(__file__).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
