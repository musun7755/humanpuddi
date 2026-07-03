"""產生一則 Threads 限時貼文候選，送到 Discord 等待人工發布或略過。"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import requests
from dotenv import load_dotenv

from gemini_client import GeminiAPIError, GeminiClient
from telegram_notify import send_telegram_ghost


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"
CONFIG_DIR: Final = PROJECT_ROOT / "config"
DATA_DIR: Final = PROJECT_ROOT / "data" / "ghost_candidates"
SLOTS: Final = {
    "noon": "中午 12:30",
    "evening": "晚上 20:00",
}
SCHEMA: Final = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["互動", "搞笑", "日常 murmur"],
        },
    },
    "required": ["text", "category"],
}
SYSTEM: Final = """你是赫湦的 Threads 限時貼文編輯器。只產生一則供人工審核的候選，不得宣稱已發布。文字必須自然、口語、具體，像本人當下忍不住說一句話；避免 AI 腔、雞湯、硬塞問句、抽象升華與傷害性笑點。嚴格輸出 JSON。"""


def _read_context() -> str:
    files = ("bot_profile.md", "character_hexing.md", "social_rules.md")
    return "\n\n".join(
        f"--- {name} ---\n{(CONFIG_DIR / name).read_text(encoding='utf-8').strip()}"
        for name in files
    )


def _recent_candidates() -> str:
    if not DATA_DIR.exists():
        return ""
    texts: list[str] = []
    for path in sorted(DATA_DIR.glob("*.json"), reverse=True)[:14]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = str(data.get("text", "")).strip()
            if text:
                texts.append(text)
        except (OSError, ValueError, TypeError):
            continue
    return "\n".join(f"- {text}" for text in texts)


def _generate(slot: str) -> dict[str, str]:
    recent = _recent_candidates() or "（沒有近期候選）"
    prompt = f"""現在是 {SLOTS[slot]}，請為赫湦產生一則純文字 Threads 限時貼文候選。

方向只能從「互動、搞笑、日常 murmur」選一種，但要自然輪替，不必每次提問。適合 24 小時後消失的即時小念頭，例如被呱鬆咬、路上看到溫暖互動、工作空檔的怪念頭或可接話的生活觀察。

可以創作符合角色世界的低風險微型日常，但不要捏造新聞、熱門事件、名人互動、重大經歷或他人的私事。不要每次都使用呱鬆、戀愛、食物或「剛剛」。

要求：
- 繁體中文，15～180 字，可自然分行。
- 像當下碎念，不像正式貼文或社群小編。
- 有具體觀察或反應，不使用通用雞湯與抽象文青句。
- 若選互動，留下自然可回應空間，不用「大家覺得呢」等制式問句。
- 不得重複近期候選的主角、場景、句型或笑點。

近期候選：
{recent}

角色設定：
{_read_context()}
"""
    result = GeminiClient().generate_json(prompt, SCHEMA, SYSTEM)
    text = str(result.get("text", "")).strip()
    category = str(result.get("category", "")).strip()
    if not text or not 15 <= len(text) <= 180:
        raise GeminiAPIError("限時貼文候選必須介於 15～180 字。")
    if category not in {"互動", "搞笑", "日常 murmur"}:
        raise GeminiAPIError("限時貼文分類無效。")
    return {"text": text, "category": category}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _send(candidate_id: str, data: dict[str, Any]) -> str:
    load_dotenv(ENV_FILE, override=False)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if not token or not channel_id.isdigit():
        raise RuntimeError("Discord Bot Token 或 review 頻道尚未設定。")
    response = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={
            "embeds": [{
                "title": f"限時貼文候選｜{data['slot_label']}",
                "description": data["text"],
                "color": 0xF2A7C6,
                "fields": [{"name": "方向", "value": data["category"], "inline": True}],
                "footer": {"text": "24 小時後自動消失｜按發布才會送出"},
            }],
            "components": [{
                "type": 1,
                "components": [
                    {"type": 2, "style": 3, "label": "發布限時貼文", "custom_id": f"hexing:ghost:publish:{candidate_id}"},
                    {"type": 2, "style": 2, "label": "略過", "custom_id": f"hexing:ghost:skip:{candidate_id}"},
                ],
            }],
        },
        timeout=20,
    )
    if not response.ok:
        raise RuntimeError(f"Discord 候選通知失敗。HTTP {response.status_code}：{response.text}")
    return str(response.json()["id"])


def main() -> int:
    slot = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    if slot not in SLOTS:
        print("用法：python generate_ghost_candidate.py noon|evening")
        return 1
    candidate_id = f"{date.today().isoformat()}-{slot}"
    path = DATA_DIR / f"{candidate_id}.json"
    if path.exists():
        print(f"[略過] 此時段候選已存在：{path}")
        return 0
    try:
        result = _generate(slot)
        data: dict[str, Any] = {
            "id": candidate_id,
            "slot": slot,
            "slot_label": SLOTS[slot],
            "created_at": datetime.now().astimezone().isoformat(),
            "status": "pending",
            **result,
        }
        _write(path, data)
        notification_errors = []
        try:
            data["telegram_message_id"] = send_telegram_ghost(candidate_id, data)
        except Exception as exc:
            notification_errors.append(f"Telegram: {exc}")
        _write(path, data)
        if notification_errors:
            raise RuntimeError("；".join(notification_errors))
        for error in notification_errors:
            print(f"[通知警告] {error}")
    except (OSError, RuntimeError, GeminiAPIError, requests.RequestException) as exc:
        print(f"[失敗] {exc}")
        return 1
    print(f"[完成] 已送出限時貼文候選：{candidate_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
