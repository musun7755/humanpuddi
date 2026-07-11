"""產生今日三則 Threads 候選貼文，但不會發布。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Final

from discord_notify import send_discord_message, send_review_candidates, send_review_control
from gemini_client import GeminiAPIError, GeminiClient


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
CONFIG_DIR: Final = PROJECT_ROOT / "config"
PENDING_DIR: Final = PROJECT_ROOT / "posts" / "pending"

CONFIG_FILES: Final = (
    "character_hexing.md",
    "content_strategy.md",
    "threads_format_rules.md",
    "social_rules.md",
    "image_rules.md",
    "trend_keywords.txt",
)

SYSTEM_INSTRUCTION: Final = """You are HexingBot's original social content editor.
Create candidates for human review only. Never claim or request automatic publishing.
Follow the supplied configuration by priority: social_rules.md > character_hexing.md > content_strategy.md > threads_format_rules.md > image_rules.md > trend context.
Return exactly the required JSON. Write public copy, category labels, summaries, and inspiration notes in natural Taiwanese Traditional Chinese. Write Flow prompts as image-generation instructions beginning with `赫湦`."""

CANDIDATE_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "trend_summary": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "enum": ["A", "B", "C"]},
                    "thread_text": {"type": "string"},
                    "flow_prompt": {"type": "string"},
                    "content_category": {"type": "string"},
                    "inspiration_source": {"type": "string"},
                },
                "required": [
                    "candidate_id",
                    "thread_text",
                    "flow_prompt",
                    "content_category",
                    "inspiration_source",
                ],
            },
        },
    },
    "required": ["trend_summary", "candidates"],
}

REQUIRED_CANDIDATE_FIELDS: Final = (
    "candidate_id",
    "thread_text",
    "flow_prompt",
    "content_category",
    "inspiration_source",
)
LONG_THREAD_SENTENCE: Final = 28


def read_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    for filename in CONFIG_FILES:
        path = CONFIG_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"缺少設定檔：{path}")
        settings[filename] = path.read_text(encoding="utf-8").strip()
    return settings


def build_prompt(
    settings: dict[str, str],
    previous_rounds: str = "",
    feedback: str = "",
) -> str:
    config_text = "\n\n".join(
        f"--- {filename} ---\n{content or '(No content provided.)'}"
        for filename, content in settings.items()
    )
    retry_text = ""
    if previous_rounds:
        retry_text = f"""

## Regeneration Rules
Use all previous candidates and operator feedback. All three new candidates must avoid earlier topics, sentence patterns, joke mechanisms, and settings. Do not merely replace words with synonyms.

Previous candidates:
{previous_rounds}

Operator feedback:
{feedback}
"""

    return f"""Create exactly three Threads candidates for @humanpuddi for human review.

Generation date: {date.today().isoformat()}. Use this date and the visible setting to keep clothing seasonally and climatically plausible; assume Taiwan-like subtropical weather unless the concept clearly establishes another environment.

1. Select one daily brief from trend_keywords.txt. First decide whether it is text-led or photo-led, then define one core topic, primary content pillar, intended audience response, and primary post function. Photo-led is a complete post function: the image may carry the post while the caption stays minimal. Summarize the brief in trend_summary. Never fabricate a trend or event; state `原創角色發想` when reliable recent evidence is unavailable.
2. Produce candidate_id A, B, and C in order. Follow content_strategy.md so they remain comparable versions of the same brief.
3. Write thread_text in natural Taiwanese Traditional Chinese. Follow character_hexing.md for personality and voice, and threads_format_rules.md for length, punctuation, sentence length, line breaks, and spacing. Do not assume every post needs an article. For a photo-led brief, thread_text may be one short phrase, one sentence, a fragment, or a few fitting characters; do not add setup, explanation, moral, or punchline unless the concept needs it. Do not output analysis or formatting notes.
4. Write flow_prompt as visual direction, not a list of attributes. Begin with `赫湦`, define one dominant visual thesis and an exact captured moment, then use one strong source of tension, a few consequential scene details, and camera/light/composition choices that support the moment. Dress him for the generation date, Taiwan-like climate, activity, and visible environment according to his bright, playful, contemporary Korean-inspired wardrobe identity. Pale green is his recurring favorite color. He may wear original duck, pudding, avocado, retro American, collegiate, food, animal, stripe, check, or abstract patterns; a generic banana, hot-dog, animal, or object costume for comedy; or an original non-franchise cosplay when the concept fits. Vary color, silhouette, texture, layering, and accessories. Never default to a neutral blazer over a plain T-shirt or repeat one outfit formula across the three candidates. Allow the image model to add plausible details that increase depth, motion, texture, and narrative energy without changing the character or story logic. Do not force handsome posing, fashion-editorial presentation, exaggerated acting, or technical filler. Follow image_rules.md exactly.
5. Write content_category in Traditional Chinese as `內容支柱／貼文功能／情緒`, at most 30 characters. All three candidates share the selected pillar and function; emotional treatment may vary.
6. Write inspiration_source in Traditional Chinese, at most 180 characters. Identify the actual idea source or ideation method without inventing cultural evidence.
7. Perform two silent checks: verify character and social boundaries; then verify natural Taiwanese copy, comparable candidates, and a complete concrete Flow prompt. Return JSON only.

## Configuration
{config_text}
{retry_text}
"""


def validate_result(result: dict[str, Any]) -> None:
    for field in ("trend_summary",):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise GeminiAPIError(f"Gemini 回應缺少有效欄位：{field}")

    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise GeminiAPIError("Gemini 必須回傳剛好 3 則候選。")

    candidate_ids = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise GeminiAPIError(f"第 {index + 1} 則候選格式錯誤。")
        for field in REQUIRED_CANDIDATE_FIELDS:
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise GeminiAPIError(f"第 {index + 1} 則候選缺少有效欄位：{field}")
        candidate_ids.append(candidate["candidate_id"])

    if candidate_ids != ["A", "B", "C"]:
        raise GeminiAPIError("Gemini 候選編號必須依序為 A、B、C。")


def normalize_thread_text(text: str) -> str:
    """移除慣用句點；長句獨立成段，短句可連續換行。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = re.split(r"\n\s*\n", normalized)
    output_blocks: list[str] = []
    for paragraph in paragraphs:
        source_lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        sentences: list[str] = []
        for line in source_lines:
            sentences.extend(
                part.strip()
                for part in re.split(r"。|(?<=[！？!?])", line)
                if part.strip()
            )
        if not sentences:
            continue
        short_run: list[str] = []
        for sentence in sentences:
            visible_length = len(re.sub(r"[\s，、！？!?～~…]", "", sentence))
            if visible_length >= LONG_THREAD_SENTENCE:
                if short_run:
                    output_blocks.append("\n".join(short_run))
                    short_run = []
                output_blocks.append(sentence)
            else:
                short_run.append(sentence)
        if short_run:
            output_blocks.append("\n".join(short_run))
    return "\n\n".join(output_blocks).replace("。", "").strip()



def generate_candidates(
    settings: dict[str, str],
    previous_rounds: str = "",
    feedback: str = "",
) -> dict[str, Any]:
    client = GeminiClient()
    result = client.generate_json(
        prompt=build_prompt(settings, previous_rounds, feedback),
        response_schema=CANDIDATE_SCHEMA,
        system_instruction=SYSTEM_INSTRUCTION,
    )
    for candidate in result.get("candidates", []):
        if isinstance(candidate, dict) and isinstance(candidate.get("thread_text"), str):
            candidate["thread_text"] = normalize_thread_text(candidate["thread_text"])
    validate_result(result)
    return result


def render_markdown(result: dict[str, Any], day: str, round_label: str) -> str:
    lines = [
        f"# HexingBot 每日候選貼文｜{day}",
        "",
        f"> 生成輪次：{round_label}",
        "> 帳號：@humanpuddi",
        "> 發布狀態：僅供人工審核，未自動發布",
        "",
    ]

    for candidate in result["candidates"]:
        lines.extend(
            [
                "",
                f"## 候選 {candidate['candidate_id']}",
                "",
                "- 文案",
                "",
                candidate["thread_text"].strip(),
                "",
                "- Flow prompt",
                "",
                candidate["flow_prompt"].strip(),
                "",
                "- 文案分類標籤",
                "",
                candidate["content_category"].strip(),
                "",
                "- 靈感／流行方向",
                "",
                candidate["inspiration_source"].strip(),
            ]
        )

    lines.extend(
        [
            "",
            "-# 本檔案不會觸發 Threads 發布、留言回覆或圖片上傳。",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def notify(channel: str, message: str) -> str | None:
    try:
        send_discord_message(channel, message)
    except (RuntimeError, ValueError) as exc:
        return f"{channel}: {exc}"
    return None


def notify_review(result: dict[str, Any], day: str, round_label: str) -> str | None:
    try:
        send_review_candidates(result, day, round_label)
    except (RuntimeError, ValueError) as exc:
        return f"review: {exc}"
    return None


def notify_control() -> str | None:
    try:
        send_review_control()
    except (RuntimeError, ValueError) as exc:
        return f"review control: {exc}"
    return None


def report_fatal_error(message: str) -> None:
    print(f"[失敗] {message}")
    notification_error = notify("error", f"HexingBot 今日產文失敗：{message}")
    if notification_error:
        print(f"[通知警告] {notification_error}")


def main() -> int:
    day = date.today().isoformat()
    output_path = PENDING_DIR / f"{day}.md"
    if output_path.exists():
        report_fatal_error(
            f"今天的候選已存在：{output_path}。若要重做，請先寫 feedback 再執行重想今日.bat。"
        )
        return 1

    try:
        settings = read_settings()
        result = generate_candidates(settings)
        markdown = render_markdown(result, day, "原始候選")
        write_markdown(output_path, markdown)
    except (OSError, GeminiAPIError) as exc:
        report_fatal_error(str(exc))
        return 1

    notification_errors = [
        error
        for error in (
            notify_review(result, day, "原始候選"),
            notify_control(),
            notify("log", f"HexingBot 今日 3 則候選產生成功：{day}。"),
        )
        if error
    ]

    print(f"[完成] 今日 3 則候選已寫入：{output_path}")
    print("[下一步] 查看三則文案與 Flow prompt，選定後再手動處理。")
    if notification_errors:
        for error in notification_errors:
            print(f"[通知警告] {error}")
        print("候選檔案已完成，但部分 Telegram 通知失敗。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
