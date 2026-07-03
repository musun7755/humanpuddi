"""HexingBot 的 Discord Webhook 通知工具。"""

from pathlib import Path
from typing import Final
import os
import time

import requests
from dotenv import load_dotenv


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"

WEBHOOK_ENV_NAMES: Final = {
    "log": "DISCORD_WEBHOOK_LOG",
    "error": "DISCORD_WEBHOOK_ERROR",
    "published": "DISCORD_WEBHOOK_PUBLISHED",
    "review": "DISCORD_WEBHOOK_REVIEW",
}

DISCORD_MESSAGE_LIMIT: Final = 2000
DISCORD_CHUNK_SIZE: Final = 1800
CONTROL_MESSAGE: Final = (
    "HexingBot 今日候選已完成。\n"
    "不滿意就按「重新發想」，我會重新生成 3 則候選。\n"
    "本流程不會自動發布、不會自動回覆留言、不會上傳圖片。"
)
REGENERATE_CUSTOM_ID: Final = "hexing:regenerate_today"


def send_discord_message(channel: str, content: str) -> None:
    """相容舊呼叫名稱；通知現在只送 Telegram。"""
    normalized_channel = channel.strip().lower()
    if normalized_channel not in WEBHOOK_ENV_NAMES:
        supported = ", ".join(WEBHOOK_ENV_NAMES)
        raise ValueError(
            f"不支援的 channel：{channel!r}。支援的值為：{supported}。"
        )

    from telegram_notify import send_telegram_long_message
    send_telegram_long_message(f"[{normalized_channel.upper()}]\n{content}")


def split_discord_message(content: str) -> list[str]:
    """依 Discord 字數限制，優先在換行處切割長訊息。"""
    remaining = content.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= DISCORD_CHUNK_SIZE:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, DISCORD_CHUNK_SIZE + 1)
        if split_at < DISCORD_CHUNK_SIZE // 2:
            split_at = remaining.rfind(" ", 0, DISCORD_CHUNK_SIZE + 1)
        if split_at < DISCORD_CHUNK_SIZE // 2:
            split_at = DISCORD_CHUNK_SIZE

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


def send_discord_long_message(channel: str, content: str) -> int:
    """將完整長內容分段送到 Discord，回傳送出的訊息數。"""
    chunks = split_discord_message(content)
    if not chunks:
        raise ValueError("Discord 訊息不可為空白。")

    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        prefix = f"【{index}/{total}】\n" if total > 1 else ""
        send_discord_message(channel, prefix + chunk)
    return total


def _embed_field(name: str, value: str, inline: bool = False) -> dict[str, object]:
    text = str(value).strip() or "（未提供）"
    if len(text) > 1024:
        raise ValueError(f"Discord Embed 欄位「{name}」超過 1024 字。")
    return {"name": name, "value": text, "inline": inline}


def send_review_candidates(result: dict, day: str, round_label: str) -> None:
    """相容舊呼叫名稱；三則候選現在只送 Telegram。"""
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise ValueError("Discord review 必須收到剛好 3 則候選。")

    from telegram_notify import send_telegram_candidates
    send_telegram_candidates(result, day, round_label)




def send_review_control() -> None:
    """相容舊呼叫名稱；重新發想控制現在只送 Telegram。"""
    from telegram_notify import send_telegram_control
    send_telegram_control()


if __name__ == "__main__":
    raise SystemExit("請執行 test_discord.py 測試 Discord 通知。")
