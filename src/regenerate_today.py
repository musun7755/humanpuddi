"""直接重新產生今日三則候選；不要求回饋。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from gemini_client import GeminiAPIError
from run_daily import (
    PENDING_DIR, generate_candidates, notify, notify_control, notify_review,
    read_settings, render_markdown, report_fatal_error, write_markdown,
)

def retry_number(path: Path) -> int:
    match = re.search(r"_retry(\d+)\.md$", path.name)
    return int(match.group(1)) if match else 0


def retry_paths(day: str) -> list[Path]:
    return sorted(PENDING_DIR.glob(f"{day}_retry*.md"), key=retry_number)


def main() -> int:
    day = date.today().isoformat()
    original_path = PENDING_DIR / f"{day}.md"
    if not original_path.is_file():
        report_fatal_error(f"找不到今日原始候選：{original_path}。請先執行今日產文.bat。")
        return 1

    existing_retries = retry_paths(day)
    retry = len(existing_retries) + 1
    output_path = PENDING_DIR / f"{day}_retry{retry}.md"
    prior_paths = [original_path, *existing_retries]
    try:
        previous_rounds = "\n\n".join(
            f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}" for path in prior_paths
        )
        result = generate_candidates(
            read_settings(),
            previous_rounds,
            "操作者要求直接重新發想；避開所有上一輪主題、句型與笑點。",
        )
        markdown = render_markdown(result, day, f"第 {retry} 次重新發想")
        write_markdown(output_path, markdown)
    except (OSError, ValueError, GeminiAPIError) as exc:
        report_fatal_error(str(exc))
        return 1

    errors = [error for error in (
        notify_review(result, day, f"第 {retry} 次重新發想"),
        notify_control(),
        notify("log", f"HexingBot 今日第 {retry} 次重新發想成功：{day}。"),
    ) if error]
    print(f"[完成] 第 {retry} 次重新發想已寫入：{output_path}")
    for error in errors:
        print(f"[通知警告] {error}")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
