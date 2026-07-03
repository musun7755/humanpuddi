"""Threads Webhook server、事件去重、Discord 留言審核與 Threads 回覆 API。"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"
LOG_FILE: Final = PROJECT_ROOT / "data" / "reply_log.csv"
FIELDS: Final = ["event_id", "reply_id", "thread_id", "author", "comment_text", "draft_reply", "status", "created_at", "handled_at"]
GRAPH_BASE: Final = "https://graph.threads.net/v1.0"
LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config(name: str) -> str:
    load_dotenv(ENV_FILE, override=False)
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"尚未設定 {name}。")
    return value


def _rows() -> list[dict[str, str]]:
    with LOCK:
        if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
            return []
        with LOG_FILE.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))


def _write(rows: list[dict[str, str]]) -> None:
    with LOCK:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = LOG_FILE.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader(); writer.writerows(rows)
        temporary.replace(LOG_FILE)


def get_record(reply_id: str) -> dict[str, str] | None:
    return next((row for row in _rows() if row["reply_id"] == reply_id), None)


def update_record(reply_id: str, **changes: str) -> dict[str, str]:
    with LOCK:
        rows = _rows()
        record = next((row for row in rows if row["reply_id"] == reply_id), None)
        if record is None:
            raise KeyError(f"找不到 reply_id={reply_id}")
        record.update(changes); _write(rows)
        return record.copy()


def send_discord_error(message: str) -> None:
    try:
        from discord_notify import send_discord_message
        send_discord_message("error", f"Threads Webhook 錯誤：{message}"[:2000])
    except Exception as exc:
        print(f"[錯誤] {message}\n[Discord error 通知亦失敗] {exc}")


def _telegram_review(record: dict[str, str]) -> bool:
    """若已設定 Telegram，並行送出一則新留言測試通知。"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[Telegram] 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，略過通知。")
        return False

    text = (
        "Threads 新留言\n\n"
        f"作者：{record['author']}\n"
        f"內容：{record['comment_text']}\n\n"
        f"reply_id：{record['reply_id']}"
    )
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text[:4096],
            "reply_markup": {
                "inline_keyboard": [[{
                    "text": "產生回覆草稿",
                    "callback_data": f"tg:reply:draft:{record['reply_id']}",
                }]]
            },
        },
        timeout=15,
    )
    if not response.ok:
        raise RuntimeError(
            f"Telegram 通知失敗 HTTP {response.status_code}: {response.text}"
        )
    print(f"[Telegram] 通知成功：reply_id={record['reply_id']}")
    return True


def _discord_review(record: dict[str, str], manual_reason: str = "") -> None:
    """通知本機 Discord Bot，讓它自動產生一則待審回覆草稿。"""
    token, channel = _config("DISCORD_BOT_TOKEN"), _config("DISCORD_REVIEW_CHANNEL_ID")
    original_text = ""
    if record.get("thread_id"):
        try:
            original_text = str(threads_get(record["thread_id"]).get("text", "")).strip()
        except Exception as exc:
            print(f"[Webhook] 無法讀取原貼文，仍繼續通知：{exc}")
    fields = [
        {"name": "留言作者", "value": record["author"][:1024]},
        {"name": "留言內容", "value": record["comment_text"][:1024]},
    ]
    if original_text:
        fields.insert(0, {"name": "原貼文", "value": original_text[:1024]})
    payload = {
        "embeds": [{"title": "Threads 新留言", "color": 0x00A67E,
                    "fields": fields,
                    "footer": {"text": f"正在產生回覆草稿｜reply_id:{record['reply_id']}"}}],
    }
    response = requests.post(f"https://discord.com/api/v10/channels/{channel}/messages", headers={"Authorization": f"Bot {token}"}, json=payload, timeout=15)
    if not response.ok:
        raise RuntimeError(f"Discord review 失敗 HTTP {response.status_code}: {response.text}")


def threads_get(reply_id: str) -> dict[str, Any]:
    response = requests.get(f"{GRAPH_BASE}/{reply_id}", params={"fields": "id,text,username,timestamp,root_post,replied_to", "access_token": _config("THREADS_ACCESS_TOKEN")}, timeout=20)
    if not response.ok:
        raise RuntimeError(f"Threads 讀取留言失敗 HTTP {response.status_code}: {response.text}")
    return response.json()


def publish_reply(reply_id: str, text: str) -> None:
    token, user_id = _config("THREADS_ACCESS_TOKEN"), _config("THREADS_USER_ID")
    create = requests.post(f"{GRAPH_BASE}/{user_id}/threads", data={"media_type": "TEXT", "text": text, "reply_to_id": reply_id, "access_token": token}, timeout=20)
    if not create.ok or not create.json().get("id"):
        raise RuntimeError(f"Threads 建立回覆失敗 HTTP {create.status_code}: {create.text}")
    publish = requests.post(f"{GRAPH_BASE}/{user_id}/threads_publish", data={"creation_id": create.json()["id"], "access_token": token}, timeout=20)
    if not publish.ok:
        raise RuntimeError(f"Threads 發布回覆失敗 HTTP {publish.status_code}: {publish.text}")


def handle_event(event: dict[str, Any]) -> bool:
    value = event.get("value") if isinstance(event.get("value"), dict) else event
    reply_id = str(value.get("reply_id") or value.get("comment_id") or value.get("id") or "").strip()
    if not reply_id:
        return False
    with LOCK:
        if get_record(reply_id):
            return False
        # 正式 Moderate webhook 已包含作者與留言；純通知模式不補打 Threads API。
        detail = value
        sender = detail.get("from") if isinstance(detail.get("from"), dict) else {}
        media = detail.get("media") if isinstance(detail.get("media"), dict) else {}
        root_post = detail.get("root_post") if isinstance(detail.get("root_post"), dict) else {}
        replied_to = detail.get("replied_to") if isinstance(detail.get("replied_to"), dict) else {}
        record = {"event_id": str(event.get("id") or value.get("event_id") or reply_id), "reply_id": reply_id,
                  "thread_id": str(detail.get("thread_id") or root_post.get("id") or replied_to.get("id") or detail.get("media_id") or media.get("id") or ""),
                  "author": str(detail.get("username") or detail.get("author") or sender.get("username") or "未知"), "comment_text": str(detail.get("text") or ""),
                  "draft_reply": "", "status": "processing", "created_at": now(), "handled_at": ""}
        self_username = os.getenv("THREADS_USERNAME", "humanpuddi").strip().lstrip("@").casefold()
        if record["author"].strip().lstrip("@").casefold() == self_username:
            print(f"[Webhook] 略過自己的留言：reply_id={reply_id}")
            return False
        rows = _rows(); rows.append(record); _write(rows)
    try:
        try:
            _telegram_review(record)
        except Exception as exc:
            print(f"[Telegram] 通知失敗：{exc}")
        update_record(reply_id, status="notified", handled_at=now())
        return True
    except Exception as exc:
        update_record(reply_id, status="error", handled_at=now())
        send_discord_error(str(exc)); return False


def process_payload(payload: dict[str, Any]) -> None:
    found = 0
    for entry in payload.get("entry", []):
        for event in entry.get("changes", entry.get("messaging", [])):
            field = str(event.get("field", "")).lower()
            if not field or "repl" in field or "mention" in field:
                found += 1
                handle_event(event)
    # Meta 測試工具及不同 API 版本偶爾會把 changes 放在頂層。
    if not found:
        for event in payload.get("changes", []):
            if isinstance(event, dict):
                found += 1
                handle_event(event)
    # Threads Moderate webhook 的正式事件格式使用頂層 values。
    if not found:
        for event in payload.get("values", []):
            if not isinstance(event, dict):
                continue
            field = str(event.get("field", "")).lower()
            if not field or "repl" in field or "mention" in field:
                found += 1
                handle_event(event)
    if not found:
        print(f"[Webhook] 收到事件但找不到 replies/mentions changes：{json.dumps(payload, ensure_ascii=False)[:3000]}")


class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        if not query and urlparse(self.path).path in {"/", "/health"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"HexingBot Threads Webhook is running")
        elif query.get("hub.mode", [""])[0] == "subscribe" and hmac.compare_digest(query.get("hub.verify_token", [""])[0], os.getenv("THREADS_WEBHOOK_VERIFY_TOKEN", "")):
            body = query.get("hub.challenge", [""])[0].encode(); self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(body)
        else:
            self.send_error(403, "Webhook verification failed")
            send_discord_error("Meta webhook 驗證失敗：verify token 不符。")

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        signature = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(os.getenv("THREADS_APP_SECRET", "").encode(), body, hashlib.sha256).hexdigest()
        if not os.getenv("THREADS_APP_SECRET") or not hmac.compare_digest(signature, expected):
            self.send_error(403, "Invalid signature")
            send_discord_error("Threads webhook 簽章驗證失敗，事件已拒絕。")
            return
        try:
            payload = json.loads(body)
            print(f"[Webhook] 收到 POST：object={payload.get('object', '未知')}，entry={len(payload.get('entry', []))}")
            self.send_response(200); self.end_headers(); self.wfile.write(b"EVENT_RECEIVED")
            threading.Thread(target=process_payload, args=(payload,), daemon=True).start()
        except Exception as exc:
            self.send_error(400, "Invalid JSON"); send_discord_error(str(exc))

    def log_message(self, format: str, *args: object) -> None:
        print("[Webhook] " + format % args)


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    try:
        for name in ("THREADS_APP_SECRET", "THREADS_WEBHOOK_VERIFY_TOKEN", "DISCORD_BOT_TOKEN", "DISCORD_REVIEW_CHANNEL_ID"):
            _config(name)
        # Render 等雲端平台會透過 PORT 指定對外監聽埠；本機仍使用 8787。
        port = int(os.getenv("PORT") or os.getenv("THREADS_WEBHOOK_PORT", "8787"))
        print(f"[完成] Threads Webhook server：http://127.0.0.1:{port}/webhook")
        ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()
    except Exception as exc:
        send_discord_error(str(exc)); print(f"[失敗] {exc}"); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
