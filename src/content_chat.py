"""Telegram 多輪文案與 Flow prompt 討論。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from gemini_client import GeminiClient
from run_daily import normalize_thread_text, read_settings

ROOT: Final = Path(__file__).resolve().parent.parent
SESSIONS: Final = ROOT / "data" / "content_chat"
ACCEPTED: Final = ROOT / "posts" / "discussed"

SCHEMA: Final = {
    "type": "object",
    "properties": {
        "thread_text": {"type": "string"},
        "flow_prompt": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["thread_text", "flow_prompt", "note"],
}


def _path(chat_id: int) -> Path:
    return SESSIONS / f"{chat_id}.json"


def load_session(chat_id: int) -> dict[str, Any] | None:
    path = _path(chat_id)
    if not path.is_file(): return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(chat_id: int, data: dict[str, Any]) -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    path = _path(chat_id); temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def end_session(chat_id: int) -> None:
    _path(chat_id).unlink(missing_ok=True)


def generate(chat_id: int, topic: str = "", feedback: str = "", rethink: bool = False) -> dict[str, Any]:
    previous = load_session(chat_id)
    if not previous and not topic.strip():
        raise ValueError("請先提供題材")
    topic = topic.strip() or str(previous["topic"])
    settings = read_settings()
    config_text = "\n\n".join(f"--- {name} ---\n{value}" for name, value in settings.items())
    previous_text = ""
    if previous:
        previous_text = f"""Previous version:
Thread copy:
{previous.get('thread_text', '')}

Flow prompt:
{previous.get('flow_prompt', '')}
"""
    request = feedback.strip()
    if rethink:
        request = "Create a substantially different execution while preserving the topic and character. Change the angle, wording, visual action, clothing, and setting."
    prompt = f"""Create or revise one Threads post and its matching Flow image prompt through an ongoing editor conversation.

Topic supplied by the operator:
{topic}

Latest operator request:
{request or 'Create the first version.'}

{previous_text}

Follow all supplied project configuration. Treat the latest operator request as an edit instruction when a previous version exists. Preserve unspecified parts only when they still fit.
Write thread_text in natural Taiwanese Traditional Chinese as 赫湦: warm, lively, lightly funny, and suitable for Taiwanese Threads. Do not force a joke. Use appropriate line spacing and sparse punctuation.
Write a detailed, concrete Flow prompt beginning with `赫湦`. It must visibly match this exact post and specify clothing, expression, action, setting, props, lighting, atmosphere, visual style, shot, camera, and composition. Avoid abstract mood-only wording.
Write note as one short Traditional Chinese sentence explaining the main creative direction or revision. Return JSON only.

Configuration:
{config_text}
"""
    result = GeminiClient().generate_json(
        prompt=prompt,
        response_schema=SCHEMA,
        system_instruction="You are HexingBot's Taiwanese social copy editor and visual prompt designer. Maintain conversational revision context. Never publish anything.",
    )
    data = {
        "topic": topic,
        "thread_text": normalize_thread_text(str(result["thread_text"])),
        "flow_prompt": str(result["flow_prompt"]).strip(),
        "note": str(result["note"]).strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_session(chat_id, data)
    return data


def accept(chat_id: int) -> Path:
    data = load_session(chat_id)
    if not data: raise ValueError("目前沒有討論中的文案")
    ACCEPTED.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = ACCEPTED / f"{stamp}.md"
    content = f"# 討論採用文案\n\n## 題材\n\n{data['topic']}\n\n## 文案\n\n{data['thread_text']}\n\n## Flow prompt\n\n{data['flow_prompt']}\n\n## 備註\n\n{data['note']}\n"
    path.write_text(content, encoding="utf-8")
    end_session(chat_id)
    return path
