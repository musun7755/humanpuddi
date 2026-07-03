"""HexingBot Telegram 通知與審核訊息工具。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

import requests
from dotenv import load_dotenv

ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = ROOT / ".env"


def _config() -> tuple[str, str]:
    load_dotenv(ENV_FILE, override=False)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("尚未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID。")
    return token, chat_id


def send_telegram_message(text: str, reply_markup: dict[str, Any] | None = None) -> int:
    token, chat_id = _config()
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4096]}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=20
    )
    if not response.ok:
        raise RuntimeError(f"Telegram 通知失敗 HTTP {response.status_code}: {response.text}")
    return int(response.json()["result"]["message_id"])


def send_telegram_long_message(text: str) -> int:
    remaining = text.strip()
    count = 0
    while remaining:
        chunk = remaining[:3900]
        if len(remaining) > 3900 and "\n" in chunk:
            split = chunk.rfind("\n")
            chunk = chunk[:split]
        send_telegram_message(chunk)
        remaining = remaining[len(chunk):].lstrip()
        count += 1
    return count


def send_telegram_candidates(result: dict[str, Any], day: str, round_label: str) -> None:
    send_telegram_message(f"HexingBot 今日候選｜{day}｜{round_label}")
    for candidate in result.get("candidates", []):
        send_telegram_message(
            f"候選 {candidate.get('candidate_id', '?')}\n\n"
            f"文案｜可直接複製貼上\n{candidate.get('thread_text', '')}\n\n"
            f"Flow prompt\n{candidate.get('flow_prompt', '')}\n\n"
            f"文案分類標籤\n{candidate.get('content_category', '')}\n\n"
            f"靈感／流行方向\n{candidate.get('inspiration_source', '')}\n\n"
            f"{day}｜{round_label}｜僅供人工審核"
        )


def send_telegram_control() -> None:
    send_telegram_message(
        "HexingBot 今日候選已完成。\n不滿意就按「重新發想」，我會重新生成 3 則候選。",
        {"inline_keyboard": [[{"text": "重新發想", "callback_data": "tg:daily:regenerate:today"}]]},
    )


def send_telegram_ghost(candidate_id: str, data: dict[str, Any]) -> int:
    return send_telegram_message(
        f"限時貼文候選｜{data['slot_label']}\n\n{data['text']}\n\n"
        f"方向：{data['category']}\n24 小時後自動消失｜按發布才會送出",
        {"inline_keyboard": [[
            {"text": "發布限時貼文", "callback_data": f"tg:ghost:publish:{candidate_id}"},
            {"text": "略過", "callback_data": f"tg:ghost:skip:{candidate_id}"},
        ]]},
    )
