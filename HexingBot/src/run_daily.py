"""產生今日三則 Threads 候選貼文，但不會發布。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from discord_notify import send_discord_message, send_review_candidates, send_review_control
from gemini_client import GeminiAPIError, GeminiClient


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
CONFIG_DIR: Final = PROJECT_ROOT / "config"
PENDING_DIR: Final = PROJECT_ROOT / "posts" / "pending"
ECOSYSTEM_REPORT: Final = PROJECT_ROOT / "research" / "daily_ecosystem_report.md"
ECOSYSTEM_CSV: Final = PROJECT_ROOT / "data" / "ecosystem_signals.csv"

CONFIG_FILES: Final = (
    "bot_profile.md",
    "character_hexing.md",
    "social_rules.md",
    "image_rules.md",
    "trend_keywords.txt",
)

SYSTEM_INSTRUCTION: Final = """你是 HexingBot 的原創社群內容編輯器。
你只產生供人工審核的候選文字與 Flow prompt，絕不宣稱已發布，也不要求自動發布。
角色赫湦面向粉絲時使用 Public Mode：幽默、公開、保持界線，不戀愛、不曖昧。
面向操作者時使用 Operator Mode：像有風格的創意搭檔。
禁止搬運、改寫、致敬或模仿 meme、歌詞、歌曲封面、MV、名人照片、動漫、影劇、遊戲角色或他人作品。
Flow prompt 只能描述原創視覺，不得指定在世藝術家、品牌角色或可辨識作品的風格。
嚴格遵守要求的 JSON 格式。"""

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


def read_settings() -> dict[str, str]:
    settings: dict[str, str] = {}
    for filename in CONFIG_FILES:
        path = CONFIG_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f"缺少設定檔：{path}")
        settings[filename] = path.read_text(encoding="utf-8").strip()
    return settings


def read_ecosystem_context() -> str:
    """讀取可選的生態摘要；缺檔或讀取失敗時維持原流程。"""
    sections: list[str] = []
    try:
        if ECOSYSTEM_REPORT.is_file():
            report = ECOSYSTEM_REPORT.read_text(encoding="utf-8").strip()
            if report:
                sections.append(f"--- daily_ecosystem_report.md ---\n{report}")

        if ECOSYSTEM_CSV.is_file():
            cutoff = date.today() - timedelta(days=13)
            with ECOSYSTEM_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = []
                for row in csv.DictReader(handle):
                    try:
                        if date.fromisoformat(row.get("date", "")) >= cutoff:
                            rows.append(row)
                    except ValueError:
                        continue
            if rows:
                fields = ("date", "type", "label", "keywords", "vibe", "heat", "days_seen", "hexing_angle", "notes")
                csv_lines = [",".join(fields)]
                csv_lines.extend(",".join(str(row.get(field, "")).replace("\n", " ") for field in fields) for row in rows)
                sections.append("--- ecosystem_signals.csv（最近 14 天） ---\n" + "\n".join(csv_lines))
    except OSError as exc:
        print(f"[生態參考警告] 無法讀取生態調查檔案，將照原流程產文：{exc}")
        return ""
    return "\n\n".join(sections)


def build_prompt(
    settings: dict[str, str],
    previous_rounds: str = "",
    feedback: str = "",
    ecosystem_context: str = "",
) -> str:
    config_text = "\n\n".join(
        f"--- {filename} ---\n{content or '（目前沒有內容）'}"
        for filename, content in settings.items()
    )
    retry_text = ""
    if previous_rounds:
        retry_text = f"""

【重新生成規則】
以下是先前候選與操作者回饋。請完整吸收拒絕理由，三則新候選都必須避開先前各輪的主題、句型、笑點與場景；不可只換同義詞。

先前候選：
{previous_rounds}

操作者回饋：
{feedback}
"""

    ecosystem_text = ""
    if ecosystem_context:
        ecosystem_text = f"""

【最近社群氣氛（僅供靈感參考）】
以下內容不是硬性題目，不要直接報導熱門事件、照抄句子或聲稱即時熱門。赫湦仍以自己的日常、正能量、好笑、日常可愛與生活觀察為主。
{ecosystem_context}
"""

    return f"""今天要為 @humanpuddi 產生三則可人工審核的 Threads 候選貼文。

請先只根據 trend_keywords.txt 的人工關鍵字，整理「今日可用趨勢方向摘要」。這不是即時熱門搜尋；若檔案空白，請明確說明沒有人工趨勢關鍵字，並改用常青原創方向，不得捏造熱門事件。

接著產生剛好三則彼此明顯不同的候選，candidate_id 依序為 A、B、C。每則都要：
1. 使用赫湦 Public Mode，適合公開粉絲閱讀。
2. thread_text 是可直接人工審核的繁體中文貼文。
3. thread_text 必須是完成稿，適合直接複製貼到 Threads；自然分行，可自由使用適量 Emoji 排版，不要輸出說明或 Markdown 標題，最多 350 字。
4. flow_prompt 是精簡英文原創視覺提示詞，只提供給操作者手動使用 Flow，最多 700 字；不得要求自動生圖或上傳。
5. content_category 是簡短文案分類標籤，例如「日常／搞笑」，最多 30 字。
6. inspiration_source 用繁體中文簡述原創靈感或流行方向，最多 180 字。若沒有可信的近期梗，寫明是常青日常方向，不得捏造流行事件或假稱使用某個 meme。

安全規則仍必須在生成時遵守，但不要輸出 negative prompt、推薦、版權檢查、邊界檢查或 Operator Mode 說明。

【設定檔】
{config_text}
{ecosystem_text}
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



def generate_candidates(
    settings: dict[str, str],
    previous_rounds: str = "",
    feedback: str = "",
    ecosystem_context: str = "",
) -> dict[str, Any]:
    client = GeminiClient()
    result = client.generate_json(
        prompt=build_prompt(settings, previous_rounds, feedback, ecosystem_context),
        response_schema=CANDIDATE_SCHEMA,
        system_instruction=SYSTEM_INSTRUCTION,
    )
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
        result = generate_candidates(settings, ecosystem_context=read_ecosystem_context())
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
        print("候選檔案已完成，但部分 Discord 通知失敗。")
        return 2
    return 0


def notify_control() -> str | None:
    try:
        send_review_control()
    except (RuntimeError, ValueError) as exc:
        return f"review control: {exc}"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
