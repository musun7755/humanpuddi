"""Threads Webhook server、事件去重、Discord 留言審核與 Threads 回覆 API。"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import threading
import time
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
AUTO_STATE_FILE: Final = PROJECT_ROOT / "data" / "auto_reply_state.json"
WEBHOOK_INBOX_FILE: Final = PROJECT_ROOT / "data" / "webhook_inbox.jsonl"
FIELDS: Final = ["event_id", "reply_id", "thread_id", "author", "comment_text", "post_text", "conversation_text", "draft_reply", "status", "created_at", "handled_at"]
GRAPH_BASE: Final = "https://graph.threads.net/v1.0"
BUILD_VERSION: Final = "2026-07-11-signature-inbox"
LOCK = threading.RLock()
AUTO_REPLY_LOCK = threading.Lock()
AUTO_REPLY_DAILY_LIMIT: Final = 20
AUTO_REPLY_PER_AUTHOR_THREAD_LIMIT: Final = 3
LAST_AUTO_REPLY_AT = 0.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config(name: str) -> str:
    load_dotenv(ENV_FILE, override=False)
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"尚未設定 {name}。")
    return value


def _float_config(name: str, default: float) -> float:
    load_dotenv(ENV_FILE, override=False)
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        raise RuntimeError(f"{name} 必須是秒數。")


def _auto_state() -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    # Render 的暫存檔在重新部署後可能消失；依使用者設定，無狀態時預設開啟。
    default: dict[str, Any] = {"enabled": True, "date": today, "daily_count": 0}
    try:
        state = json.loads(AUTO_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict): return default
    except (OSError, json.JSONDecodeError):
        return default
    if state.get("date") != today:
        state["date"], state["daily_count"] = today, 0
    state["enabled"] = bool(state.get("enabled", True))
    state["daily_count"] = int(state.get("daily_count", 0))
    return state


def _save_auto_state(state: dict[str, Any]) -> None:
    AUTO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTO_STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(AUTO_STATE_FILE)


def _enable_auto_reply_on_startup() -> None:
    """Render starts in auto-reply mode unless explicitly disabled by env."""
    if os.getenv("AUTO_REPLY_START_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    with LOCK:
        state = _auto_state()
        if not state.get("enabled"):
            state["enabled"] = True
            _save_auto_state(state)
            print("[自動回覆] 服務啟動時已預設開啟。")


def _control_authorized(headers: Any) -> bool:
    secret = os.getenv("AUTO_REPLY_CONTROL_SECRET", "").strip()
    return bool(secret) and hmac.compare_digest(str(headers.get("Authorization", "")), f"Bearer {secret}")


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


def _remember_webhook(payload: dict[str, Any], status: str = "accepted", note: str = "") -> None:
    WEBHOOK_INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "received_at": now(),
        "status": status,
        "note": note,
        "object": payload.get("object"),
        "entry_count": len(payload.get("entry", [])) if isinstance(payload.get("entry"), list) else 0,
        "top_level_keys": list(payload.keys()),
        "payload": payload,
    }
    with WEBHOOK_INBOX_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False) + "\n")


def _webhook_inbox(limit: int = 10) -> list[dict[str, Any]]:
    if not WEBHOOK_INBOX_FILE.exists():
        return []
    lines = WEBHOOK_INBOX_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    items: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                items.append(item)
        except json.JSONDecodeError:
            continue
    return items


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


def _telegram_status(text: str) -> None:
    token, chat_id = _config("TELEGRAM_BOT_TOKEN"), _config("TELEGRAM_CHAT_ID")
    response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text[:4096]}, timeout=15)
    if not response.ok:
        raise RuntimeError(f"Telegram 通知失敗 HTTP {response.status_code}: {response.text}")


def threads_get(reply_id: str) -> dict[str, Any]:
    response = requests.get(f"{GRAPH_BASE}/{reply_id}", params={"fields": "id,text,username,timestamp,root_post,replied_to", "access_token": _config("THREADS_ACCESS_TOKEN")}, timeout=20)
    if not response.ok:
        raise RuntimeError(f"Threads 讀取留言失敗 HTTP {response.status_code}: {response.text}")
    return response.json()


def _candidate_reply_ids(value: Any, parent_key: str = "") -> list[str]:
    """蒐集 webhook 內可能的留言 ID，排除明確的作者帳號 ID。"""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"from", "sender", "user", "author"}:
                continue
            if lowered in {"reply_id", "comment_id", "id", "media_id"} and isinstance(item, (str, int)):
                found.append(str(item).strip())
            found.extend(_candidate_reply_ids(item, lowered))
    elif isinstance(value, list):
        for item in value:
            found.extend(_candidate_reply_ids(item, parent_key))
    return list(dict.fromkeys(item for item in found if item))


def _resolve_reply_id(value: dict[str, Any]) -> str:
    """以留言文字驗證候選 ID，避免把 webhook 的使用者 ID 當 reply_to_id。"""
    expected_text = " ".join(str(value.get("text") or "").split())
    token = _config("THREADS_ACCESS_TOKEN")
    for candidate in _candidate_reply_ids(value):
        response = requests.get(
            f"{GRAPH_BASE}/{candidate}",
            params={"fields": "id,text", "access_token": token},
            timeout=20,
        )
        if not response.ok:
            continue
        actual_text = " ".join(str(response.json().get("text") or "").split())
        if actual_text and (not expected_text or actual_text == expected_text):
            return candidate
    return ""


def _id_from_reference(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("media_id") or "").strip()
    if isinstance(value, (str, int)):
        return str(value).strip()
    return ""


def _original_post(record: dict[str, str]) -> tuple[str, str]:
    """優先使用 webhook thread_id；缺少時以留言 ID 反查 root_post。"""
    candidates = [record.get("thread_id", "").strip()]
    try:
        detail = threads_get(record["reply_id"])
        candidates.extend([
            _id_from_reference(detail.get("root_post")),
            _id_from_reference(detail.get("replied_to")),
            _id_from_reference(detail.get("media")),
            str(detail.get("thread_id") or detail.get("media_id") or "").strip(),
        ])
    except Exception as exc:
        print(f"[原貼文] 留言反查失敗：{exc}")
    for post_id in dict.fromkeys(item for item in candidates if item):
        response = requests.get(
            f"{GRAPH_BASE}/{post_id}",
            params={"fields": "id,text", "access_token": _config("THREADS_ACCESS_TOKEN")},
            timeout=20,
        )
        if response.ok and str(response.json().get("text", "")).strip():
            return post_id, str(response.json()["text"]).strip()
    return "", ""


def _conversation_context(reply_id: str, root_post_id: str = "", limit: int = 5) -> str:
    """沿 replied_to 往前追同一分支，不讀取旁支留言。"""
    token = _config("THREADS_ACCESS_TOKEN")
    current_id = reply_id
    items: list[str] = []
    seen: set[str] = set()
    for _ in range(limit + 1):
        if not current_id or current_id in seen or current_id == root_post_id:
            break
        seen.add(current_id)
        response = requests.get(
            f"{GRAPH_BASE}/{current_id}",
            params={"fields": "id,text,username,replied_to", "access_token": token},
            timeout=20,
        )
        if not response.ok:
            break
        detail = response.json()
        if current_id != reply_id:
            text = " ".join(str(detail.get("text") or "").split())
            if text:
                items.append(f"@{detail.get('username') or '未知'}：{text}")
        current_id = _id_from_reference(detail.get("replied_to"))
    return "\n".join(reversed(items[-limit:]))[:3000]


def _try_auto_reply(record: dict[str, str]) -> bool:
    global LAST_AUTO_REPLY_AT
    # Webhook 事件可能並行抵達；自動發布統一排隊，避免同時呼叫 API 或寫入記憶庫。
    with AUTO_REPLY_LOCK:
        with LOCK:
            state = _auto_state()
            if not state["enabled"]:
                update_record(record["reply_id"], status="auto_disabled", handled_at=now())
                try:
                    _telegram_status(
                        f"Threads 自動回覆目前是關閉狀態，已改送人工處理\n\n"
                        f"作者：{record['author']}\n留言：{record['comment_text']}"
                    )
                except Exception:
                    pass
                return False
            if state["daily_count"] >= AUTO_REPLY_DAILY_LIMIT:
                update_record(record["reply_id"], status="auto_daily_limit", handled_at=now())
                try:
                    _telegram_status(
                        f"Threads 自動回覆達到今日上限 {AUTO_REPLY_DAILY_LIMIT} 則，已改送人工處理\n\n"
                        f"作者：{record['author']}\n留言：{record['comment_text']}"
                    )
                except Exception:
                    pass
                return False
            author = record["author"].strip().lstrip("@").casefold()
            thread_id = record.get("thread_id", "").strip()
            replied_count = sum(
                1 for row in _rows()
                if row.get("status") == "auto_replied"
                and row.get("thread_id", "").strip() == thread_id
                and row.get("author", "").strip().lstrip("@").casefold() == author
            )
            if thread_id and replied_count >= AUTO_REPLY_PER_AUTHOR_THREAD_LIMIT:
                update_record(
                    record["reply_id"], status="skipped_author_limit", handled_at=now()
                )
                return True

        interval = _float_config("AUTO_REPLY_INTERVAL_SECONDS", 0.0)
        remaining = interval - (time.monotonic() - LAST_AUTO_REPLY_AT)
        if interval > 0 and LAST_AUTO_REPLY_AT > 0 and remaining > 0:
            print(f"[自動回覆] 等待 {remaining:.1f} 秒後發布。")
            time.sleep(remaining)

        from generate_reply_draft import generate_reply_draft
        result = generate_reply_draft(
            record["author"], record["comment_text"],
            post_text=record.get("post_text", ""),
            conversation_text=record.get("conversation_text", ""),
        )
        if not result.get("safe_to_draft"):
            reason = str(result.get("reason") or "模型判定需要人工處理").strip()
            update_record(
                record["reply_id"],
                draft_reply=f"[人工處理原因] {reason}"[:500],
                status="manual_model_rejected",
                handled_at=now(),
            )
            try:
                _telegram_status(
                    f"Threads 自動回覆改送人工處理\n\n"
                    f"作者：{record['author']}\n留言：{record['comment_text']}\n\n原因：{reason}"
                )
            except Exception:
                pass
            return False
        draft = str(result["draft_reply"])
        publish_reply(record["reply_id"], draft)
        LAST_AUTO_REPLY_AT = time.monotonic()
        with LOCK:
            state = _auto_state(); state["daily_count"] += 1; _save_auto_state(state)
        update_record(record["reply_id"], draft_reply=draft, status="auto_replied", handled_at=now())
        _telegram_status(f"Threads 已自動回覆\n\n作者：{record['author']}\n留言：{record['comment_text']}\n\n回覆：{draft}")
        return True


def publish_reply(reply_id: str, text: str) -> None:
    token, user_id = _config("THREADS_ACCESS_TOKEN"), _config("THREADS_USER_ID")
    create = requests.post(f"{GRAPH_BASE}/{user_id}/threads", data={"media_type": "TEXT", "text": text, "reply_to_id": reply_id, "access_token": token}, timeout=20)
    if not create.ok or not create.json().get("id"):
        raise RuntimeError(f"Threads 建立回覆失敗 HTTP {create.status_code}: {create.text}")
    creation_id = str(create.json()["id"])
    for _ in range(12):
        status_response = requests.get(
            f"{GRAPH_BASE}/{creation_id}",
            params={"fields": "status,error_message", "access_token": token},
            timeout=20,
        )
        if not status_response.ok:
            raise RuntimeError(
                f"Threads 查詢回覆處理狀態失敗 HTTP {status_response.status_code}: {status_response.text}"
            )
        status_body = status_response.json()
        status = str(status_body.get("status", "")).upper()
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(
                f"Threads 回覆 container 處理失敗：{status_body.get('error_message') or status}"
            )
        time.sleep(5)
    else:
        raise RuntimeError("Threads 等待回覆 container 處理逾時，尚未發布。")

    for attempt in range(3):
        publish = requests.post(
            f"{GRAPH_BASE}/{user_id}/threads_publish",
            data={"creation_id": creation_id, "access_token": token},
            timeout=20,
        )
        if publish.ok:
            return
        try:
            error = publish.json().get("error", {})
            retryable = error.get("code") == 24 or error.get("error_subcode") == 4279009
        except (ValueError, AttributeError):
            retryable = False
        if retryable and attempt < 2:
            time.sleep(3)
            continue
        raise RuntimeError(f"Threads 發布回覆失敗 HTTP {publish.status_code}: {publish.text}")


def handle_event(event: dict[str, Any]) -> bool:
    value = event.get("value") if isinstance(event.get("value"), dict) else event
    reply_id = _resolve_reply_id(value)
    if not reply_id:
        print(f"[Webhook] 無法從事件確認可回覆的留言 ID；keys={list(value.keys())}")
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
                  "post_text": "", "conversation_text": "", "draft_reply": "", "status": "processing", "created_at": now(), "handled_at": ""}
        self_username = os.getenv("THREADS_USERNAME", "humanpuddi").strip().lstrip("@").casefold()
        if record["author"].strip().lstrip("@").casefold() == self_username:
            print(f"[Webhook] 略過自己的留言：reply_id={reply_id}")
            return False
        post_id, post_text = _original_post(record)
        if post_id: record["thread_id"] = post_id
        record["post_text"] = post_text
        record["conversation_text"] = _conversation_context(reply_id, post_id)
        rows = _rows(); rows.append(record); _write(rows)
    try:
        try:
            if _try_auto_reply(record):
                return True
        except Exception as exc:
            print(f"[自動回覆] 失敗，改送人工處理：{exc}")
            try:
                _telegram_status(f"Threads 自動回覆失敗，已改送人工處理\n\n作者：{record['author']}\n留言：{record['comment_text']}\n\n錯誤：{exc}")
            except Exception:
                pass
        try:
            _telegram_review(record)
        except Exception as exc:
            print(f"[Telegram] 通知失敗：{exc}")
        current = get_record(reply_id)
        if current and current.get("status") in {"auto_disabled", "auto_daily_limit", "manual_model_rejected"}:
            update_record(reply_id, handled_at=now())
        else:
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
        path = urlparse(self.path).path
        if path == "/reply-context":
            if not _control_authorized(self.headers):
                self.send_error(401); return
            reply_id = query.get("id", [""])[0].strip()
            record = get_record(reply_id) if reply_id else None
            if not record:
                self.send_error(404); return
            payload = json.dumps({
                "reply_id": reply_id,
                "post_text": record.get("post_text", ""),
                "conversation_text": record.get("conversation_text", ""),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload)
        elif path == "/auto-reply":
            if not _control_authorized(self.headers):
                self.send_error(401); return
            with LOCK:
                state = _auto_state()
                state["build_version"] = BUILD_VERSION
                payload = json.dumps(state).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)
        elif path == "/recent-replies":
            if not _control_authorized(self.headers):
                self.send_error(401); return
            try:
                limit = max(1, min(50, int(query.get("limit", ["10"])[0])))
            except ValueError:
                limit = 10
            rows = _rows()[-limit:]
            payload = json.dumps(
                {"build_version": BUILD_VERSION, "count": len(rows), "items": rows},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload)
        elif path == "/webhook-inbox":
            if not _control_authorized(self.headers):
                self.send_error(401); return
            try:
                limit = max(1, min(25, int(query.get("limit", ["10"])[0])))
            except ValueError:
                limit = 10
            items = _webhook_inbox(limit)
            payload = json.dumps(
                {"build_version": BUILD_VERSION, "count": len(items), "items": items},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload)
        elif not query and path in {"/", "/health"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"HexingBot Threads Webhook is running\n{BUILD_VERSION}".encode("utf-8"))
        elif query.get("hub.mode", [""])[0] == "subscribe" and hmac.compare_digest(query.get("hub.verify_token", [""])[0], os.getenv("THREADS_WEBHOOK_VERIFY_TOKEN", "")):
            body = query.get("hub.challenge", [""])[0].encode(); self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(body)
        else:
            self.send_error(403, "Webhook verification failed")
            send_discord_error("Meta webhook 驗證失敗：verify token 不符。")

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/auto-reply":
            if not _control_authorized(self.headers):
                self.send_error(401); return
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                data = json.loads(body)
                if not isinstance(data.get("enabled"), bool):
                    raise ValueError("enabled must be boolean")
                with LOCK:
                    state = _auto_state(); state["enabled"] = data["enabled"]; _save_auto_state(state)
                payload = json.dumps(state).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_error(400, str(exc))
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        signature = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(os.getenv("THREADS_APP_SECRET", "").encode(), body, hashlib.sha256).hexdigest()
        if not os.getenv("THREADS_APP_SECRET") or not hmac.compare_digest(signature, expected):
            try:
                raw_payload = json.loads(body)
                if isinstance(raw_payload, dict):
                    _remember_webhook(raw_payload, status="rejected", note="invalid_signature")
            except Exception:
                _remember_webhook(
                    {"raw": body.decode("utf-8", errors="replace")[:2000]},
                    status="rejected",
                    note="invalid_signature_non_json",
                )
            self.send_error(403, "Invalid signature")
            send_discord_error("Threads webhook 簽章驗證失敗，事件已拒絕。")
            return
        try:
            payload = json.loads(body)
            _remember_webhook(payload)
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
        for name in (
            "THREADS_APP_SECRET",
            "THREADS_WEBHOOK_VERIFY_TOKEN",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "GEMINI_API_KEY",
            "THREADS_ACCESS_TOKEN",
            "THREADS_USER_ID",
            "AUTO_REPLY_CONTROL_SECRET",
        ):
            _config(name)
        _enable_auto_reply_on_startup()
        # Render 等雲端平台會透過 PORT 指定對外監聽埠；本機仍使用 8787。
        port = int(os.getenv("PORT") or os.getenv("THREADS_WEBHOOK_PORT", "8787"))
        print(f"[完成] Threads Webhook server：http://127.0.0.1:{port}/webhook")
        ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler).serve_forever()
    except Exception as exc:
        send_discord_error(str(exc)); print(f"[失敗] {exc}"); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
