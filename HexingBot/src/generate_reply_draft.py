"""依赫湦角色設定產生 Threads 公開留言短回覆草稿。"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from gemini_client import GeminiClient

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
CHARACTER_FILE: Final = PROJECT_ROOT / "config" / "character_hexing.md"

SCHEMA = {
    "type": "object",
    "properties": {
        "safe_to_draft": {"type": "boolean"},
        "draft_reply": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["safe_to_draft", "draft_reply", "reason"],
}


def generate_reply_draft(author: str, comment_text: str) -> dict[str, object]:
    character = CHARACTER_FILE.read_text(encoding="utf-8")
    prompt = f"""留言作者：{author}
留言內容：{comment_text}

判斷這則公開留言是否適合產生草稿。普通稱讚、玩笑、輕問題可以；爭議、攻擊、色情、政治、新聞或危險內容不可。
適合時寫一則短、自然、親近、略帶幽默、像 Threads 留言的赫湦公開回覆；不要把對方當私人戀愛對象。
不適合時 safe_to_draft=false、draft_reply 留空，reason 簡述需要人工處理的原因。不要新增留言中沒有的事實。"""
    result = GeminiClient().generate_json(
        prompt=prompt,
        response_schema=SCHEMA,
        system_instruction=f"以下是角色設定，只用來掌握公開社群語氣：\n\n{character}",
    )
    safe = bool(result.get("safe_to_draft"))
    draft = str(result.get("draft_reply", "")).strip()
    if not safe:
        draft = ""
    elif not draft:
        raise RuntimeError("草稿模型判定可回覆，但沒有提供草稿。")
    return {"safe_to_draft": safe, "draft_reply": draft, "reason": str(result.get("reason", "")).strip()}
