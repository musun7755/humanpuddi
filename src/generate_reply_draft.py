"""依赫湦角色設定產生 Threads 公開留言短回覆草稿。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from gemini_client import GeminiClient
from memory_store import recent_approved_reply_examples

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
CHARACTER_FILE: Final = PROJECT_ROOT / "config" / "character_hexing.md"
ECOSYSTEM_FILE: Final = PROJECT_ROOT / "data" / "ecosystem_signals.csv"

SCHEMA = {
    "type": "object",
    "properties": {
        "safe_to_draft": {"type": "boolean"},
        "draft_reply": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["safe_to_draft", "draft_reply", "reason"],
}


def _recent_internet_language() -> str:
    """讀取最近 14 天的本機社群訊號；缺檔時不影響回覆。"""
    if not ECOSYSTEM_FILE.is_file():
        return "（沒有可靠的近期社群訊號，不要自行捏造流行語）"
    cutoff = date.today() - timedelta(days=13)
    lines: list[str] = []
    try:
        with ECOSYSTEM_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    if date.fromisoformat(row.get("date", "")) < cutoff:
                        continue
                except ValueError:
                    continue
                parts = [
                    row.get("label", ""), row.get("keywords", ""),
                    row.get("vibe", ""), row.get("notes", ""),
                ]
                line = "｜".join(part.strip() for part in parts if part and part.strip())
                if line:
                    lines.append(line)
    except OSError:
        return "（近期社群訊號讀取失敗，不要自行捏造流行語）"
    return "\n".join(f"- {line}" for line in lines[-12:]) or "（沒有可靠的近期社群訊號，不要自行捏造流行語）"


def generate_reply_draft(
    author: str,
    comment_text: str,
    post_text: str = "",
    conversation_text: str = "",
    previous_draft: str = "",
) -> dict[str, object]:
    character = CHARACTER_FILE.read_text(encoding="utf-8")
    retry = ""
    if previous_draft.strip():
        retry = f"\nPrevious draft: {previous_draft.strip()}\nUse a different sentence pattern, reaction angle, and joke mechanism. Do not merely replace words with synonyms.\n"
    original = post_text.strip() or "(Original post unavailable. Do not invent context.)"
    conversation = conversation_text.strip() or "(No earlier messages in this reply branch.)"
    internet_language = _recent_internet_language()
    approved_examples = recent_approved_reply_examples()
    prompt = f"""Original post: {original[:3000]}
Earlier messages in this same reply branch, oldest to newest:
{conversation[:3000]}

Comment author: {author}
Comment: {comment_text}
{retry}

Decide whether this public comment is safe for an automatic draft. Ordinary praise, jokes, and light questions are allowed. Controversy, attacks, sexual content, politics, news, medical, legal, financial, or dangerous content requires manual handling.

When safe, write one short reply from 赫湦 in natural Taiwanese Threads voice:
- Usually 8–60 Traditional Chinese characters and no more than two short sentences. Do not greatly exceed a short source comment.
- Understand the original post, earlier messages in this same reply branch, and the latest comment. Reply to their combined context. Do not react only to the surface wording and do not invent background.
- Clearly catch the comment's key object, action, or meaning so the target is obvious, then add one natural reaction. Do not force a joke when none fits.
- Use sparse punctuation. Avoid periods, excessive commas, and repeated exclamation marks. Use natural spacing or a line break for Taiwanese chat rhythm.
- Use one line for one reaction. Use two lines only when there are genuinely two beats. Never fragment a sentence merely for layout.
- Use exactly one common Emoji that fits the tone. Do not stack Emoji.
- Taiwanese 2026 internet language, meme phrasing, sound-based puns, or Taiwanese Hokkien may appear only when it fits the context, remains understandable, and sounds natural. Otherwise use ordinary Taiwanese speech. Never force slang or Hokkien, imitate youth language, use stale slang, invent uncertain Hokkien wording, or fabricate a trend.
- Do not use a theatrical opening, exaggerated self-blame, customer-service voice, formulaic question, explained joke, or false intimacy.
- Do not add facts, advice, or causality absent from the source. Never treat the commenter as a private romantic partner.

Rhythm calibration:
For `下次吃泡麵比較不容易噴喔`, a short reaction such as `這次先算我繳學費了🥲` fits. Do not turn it into a full performance such as `糟糕，我罪孽深重！但我先說……`. These examples demonstrate rhythm only and must not become templates.
For `好可愛`, `被你看到了🫣` shows the target rhythm. For `笑死`, `先不要笑 我還在收拾😭` does the same. Do not copy these examples.

Recent 14-day social-language reference (use only when genuinely relevant; never copy directly):
{internet_language}

Recent human-approved reply examples (style calibration only):
{approved_examples}
Do not copy these replies, infer character facts from commenters, or force their joke patterns into the current context.

When unsafe, set safe_to_draft=false, leave draft_reply empty, and briefly explain the manual-review reason in Traditional Chinese. Do not add facts absent from the comment."""
    result = GeminiClient().generate_json(
        prompt=prompt,
        response_schema=SCHEMA,
        system_instruction=f"""Highest-priority rule: Write one Taiwanese Threads comment reply, not a standalone post, comedy routine, or character monologue. Understand the full context formed by the original post and comment before replying. Respond directly in short, spoken Taiwanese Traditional Chinese with natural spacing or line breaks, sparse punctuation, and exactly one Emoji. Never overperform, use exaggerated self-blame, invent advice, or give an unrelated reaction. Character settings may adjust tone but cannot override these rules.

Character configuration:
{character}""",
    )
    safe = bool(result.get("safe_to_draft"))
    draft = str(result.get("draft_reply", "")).strip()
    if not safe:
        draft = ""
    elif not draft:
        raise RuntimeError("草稿模型判定可回覆，但沒有提供草稿。")
    elif len(draft) > 80:
        raise RuntimeError("回覆草稿超過 80 字，請重新產生。")
    return {"safe_to_draft": safe, "draft_reply": draft, "reason": str(result.get("reason", "")).strip()}
