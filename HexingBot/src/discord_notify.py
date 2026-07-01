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
    """將訊息傳送到指定 Discord Webhook；失敗時拋出清楚的錯誤。"""
    normalized_channel = channel.strip().lower()
    if normalized_channel not in WEBHOOK_ENV_NAMES:
        supported = ", ".join(WEBHOOK_ENV_NAMES)
        raise ValueError(
            f"不支援的 channel：{channel!r}。支援的值為：{supported}。"
        )

    load_dotenv(ENV_FILE, override=False)
    env_name = WEBHOOK_ENV_NAMES[normalized_channel]
    webhook_url = os.getenv(env_name, "").strip()

    if not webhook_url:
        raise RuntimeError(
            f"尚未設定 {env_name}。請將 .env.example 複製為 .env，"
            f"並填入 {normalized_channel} 頻道的 Discord Webhook URL。"
        )

    if not content.strip():
        raise ValueError("Discord 訊息不可為空白。")
    if len(content) > DISCORD_MESSAGE_LIMIT:
        raise ValueError(
            f"Discord 單則訊息不可超過 {DISCORD_MESSAGE_LIMIT} 字；"
            "長內容請使用 send_discord_long_message。"
        )

    response = None
    for attempt in range(3):
        try:
            response = requests.post(
                webhook_url,
                json={"content": content},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"傳送到 {normalized_channel} 失敗：無法連線到 Discord。{exc}"
            ) from exc

        if response.status_code != 429 or attempt == 2:
            break

        try:
            retry_after = float(response.json().get("retry_after", 1))
        except (ValueError, TypeError, AttributeError):
            retry_after = 1
        time.sleep(min(max(retry_after, 0.5), 10))

    if response is None or not response.ok:
        status_code = response.status_code if response is not None else "未知"
        response_body = response.text.strip() if response is not None else ""
        response_text = response_body or "（Discord 未提供錯誤內容）"
        raise RuntimeError(
            f"傳送到 {normalized_channel} 失敗。"
            f"HTTP 狀態：{status_code}；錯誤內容：{response_text}"
        )


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
    """用 review webhook 將三則候選分別送成清楚的 Discord Embed 框。"""
    load_dotenv(ENV_FILE, override=False)
    webhook_url = os.getenv("DISCORD_WEBHOOK_REVIEW", "").strip()
    if not webhook_url:
        raise RuntimeError("尚未設定 DISCORD_WEBHOOK_REVIEW。")

    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise ValueError("Discord review 必須收到剛好 3 則候選。")

    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate.get("candidate_id", "?"))
        embed = {
            "title": f"候選 {candidate_id}",
            "color": 0x5865F2,
            "fields": [
                _embed_field("文案｜可直接複製貼上", candidate.get("thread_text", "")),
                _embed_field("Flow prompt", candidate.get("flow_prompt", "")),
                _embed_field("文案分類標籤", candidate.get("content_category", "")),
                _embed_field("靈感／流行方向", candidate.get("inspiration_source", "")),
            ],
            "footer": {"text": f"{day}｜{round_label}｜僅供人工審核"},
        }
        content = f"**HexingBot 今日候選｜{day}｜{round_label}**" if index == 0 else ""
        try:
            response = requests.post(
                webhook_url,
                params={"wait": "true"},
                json={"content": content, "embeds": [embed]},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"review Embed 傳送失敗：{exc}") from exc
        if not response.ok:
            detail = response.text.strip() or "Discord 未提供錯誤內容"
            raise RuntimeError(f"review Embed 傳送失敗。HTTP {response.status_code}：{detail}")



def send_review_control() -> None:
    """以 Bot 身分傳送唯一的互動控制訊息；候選正文仍由 webhook 傳送。"""
    load_dotenv(ENV_FILE, override=False)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if not token:
        raise RuntimeError("尚未設定 DISCORD_BOT_TOKEN，無法傳送重新發想按鈕。")
    if not channel_id.isdigit():
        raise RuntimeError("DISCORD_REVIEW_CHANNEL_ID 必須是 Discord 頻道 ID。")

    try:
        response = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            json={
                "content": CONTROL_MESSAGE,
                "components": [{
                    "type": 1,
                    "components": [{
                        "type": 2,
                        "style": 1,
                        "label": "重新發想",
                        "custom_id": REGENERATE_CUSTOM_ID,
                    }],
                }],
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"控制訊息傳送失敗：無法連線到 Discord。{exc}") from exc
    if not response.ok:
        detail = response.text.strip() or "Discord 未提供錯誤內容"
        raise RuntimeError(f"控制訊息傳送失敗。HTTP {response.status_code}：{detail}")


if __name__ == "__main__":
    raise SystemExit("請執行 test_discord.py 測試 Discord 通知。")
