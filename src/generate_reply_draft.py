"""依赫湦角色設定產生 Threads 公開留言短回覆草稿。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from gemini_client import GeminiClient

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
    previous_draft: str = "",
) -> dict[str, object]:
    character = CHARACTER_FILE.read_text(encoding="utf-8")
    retry = ""
    if previous_draft.strip():
        retry = f"\n上一版草稿：{previous_draft.strip()}\n請改用不同句型、反應角度與笑點，不要只換同義詞。\n"
    original = post_text.strip() or "（未取得原貼文，禁止自行補背景）"
    internet_language = _recent_internet_language()
    prompt = f"""原貼文：{original}
留言作者：{author}
留言內容：{comment_text}
{retry}

判斷這則公開留言是否適合產生草稿。普通稱讚、玩笑、輕問題可以；爭議、攻擊、色情、政治、新聞、醫療、法律、金融或危險內容不可。

適合時寫一則台灣 Threads 口吻的赫湦短回覆：
- 通常 8～60 字，最多兩個短句，不要比簡短原留言長很多。
- 必須同時理解原貼文與留言，回覆兩者真正形成的上下文；不能只抓留言表面，也不能新增原文沒有的背景。
- 回覆必須明確接住留言的關鍵物件、動作或意思，讓人一眼看得出是在回這句；再給一個自然反應。沒有好笑點就不要硬演。
- 少用完整標點。不要句號，避免逗號與連續驚嘆號；用自然留白或換行呈現台灣聊天節奏。
- 一個反應用單行；真的有前後兩個節拍時才分成兩行。最多兩行，不要為排版硬切碎句。
- 使用剛好一個符合語氣的常見 Emoji，不要堆 Emoji。
- 可以適量使用台灣 2026 網路口語、梗語或諧音梗，但必須貼合當下內容、讀起來像真的會講；沒有適合的梗就用自然口語，禁止硬塞、過時裝年輕或捏造流行語。
- 禁止戲劇化開場、浮誇自責、客服語氣、制式問句、解釋笑點與假裝很熟。
- 禁止新增原留言沒有的事實、建議或因果。不要把對方當私人戀愛對象。

節奏校準：
留言「下次吃泡麵比較不容易噴喔」時，可用「這次先算我繳學費了🥲」這種短反應；不要寫成「糟糕，我罪孽深重！但我先說……」這種完整表演。校準句只示範節奏，不可固定套用。
留言「好可愛」可用「被你看到了🫣」；留言「笑死」可用「先不要笑 我還在收拾😭」。不要複製範例，保留這種短、直覺、接得到原話的節奏。

最近 14 天社群語言參考（只在真的適合時使用，不得照抄）：
{internet_language}

不適合時 safe_to_draft=false、draft_reply 留空，reason 簡述需要人工處理的原因。不要新增留言中沒有的事實。"""
    result = GeminiClient().generate_json(
        prompt=prompt,
        response_schema=SCHEMA,
        system_instruction=f"""最高優先規則：你寫的是一則台灣 Threads 留言回覆，不是貼文、段子或角色獨白。必須先理解原貼文與留言的完整上下文，再用短、口語、自然留白或換行、少標點、剛好一個 Emoji 的方式直接回應；禁止硬演、浮誇自責、憑空建議與無關反應。角色設定只能調整語氣，不得覆蓋以上規則。

以下是角色設定：
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
