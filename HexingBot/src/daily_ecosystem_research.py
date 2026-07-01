"""以簡短摘要記錄每日 Threads 生態，不保存貼文原文。"""

from __future__ import annotations

import csv
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv

from gemini_client import GeminiAPIError, GeminiClient


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
SCOPE_PATH: Final = PROJECT_ROOT / "config" / "ecosystem_scope.md"
CSV_PATH: Final = PROJECT_ROOT / "data" / "ecosystem_signals.csv"
REPORT_PATH: Final = PROJECT_ROOT / "research" / "daily_ecosystem_report.md"
ENV_PATH: Final = PROJECT_ROOT / ".env"
CHROME_PROFILE_DIR: Final = PROJECT_ROOT / ".threads-chrome-profile"
FIELDS: Final = (
    "date", "type", "label", "keywords", "vibe", "heat", "days_seen",
    "hexing_angle", "notes",
)
ALLOWED_TYPES: Final = {"trend", "meme", "keyword", "light_event", "mood"}
ALLOWED_HEAT: Final = {"low", "medium", "high"}

SCHEMA: Final = {
    "type": "object",
    "properties": {
        "today_mood": {"type": "string"},
        "signals": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": sorted(ALLOWED_TYPES)},
                    "label": {"type": "string"},
                    "keywords": {"type": "string"},
                    "vibe": {"type": "string"},
                    "heat": {"type": "string", "enum": sorted(ALLOWED_HEAT)},
                    "hexing_angle": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["type", "label", "keywords", "vibe", "heat", "hexing_angle", "notes"],
            },
        },
        "conversion_advice": {"type": "string"},
    },
    "required": ["today_mood", "signals", "conversion_advice"],
}


def extract_seed_keywords(scope: str) -> list[str]:
    marker = "種子關鍵字："
    if marker not in scope:
        return []
    block = scope.split(marker, 1)[1].split("\n\n", 1)[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


def choose_keywords(keywords: list[str], day: date, limit: int = 10) -> list[str]:
    """每日輪替關鍵字，使有限搜尋能逐步涵蓋全部種子。"""
    if len(keywords) <= limit:
        return keywords
    start = day.toordinal() % len(keywords)
    return [keywords[(start + index) % len(keywords)] for index in range(limit)]


def read_rows() -> list[dict[str, str]]:
    if not CSV_PATH.is_file():
        return []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def recent_context(rows: list[dict[str, str]], day: date) -> str:
    cutoff = day - timedelta(days=13)
    lines = []
    for row in rows:
        try:
            if cutoff <= date.fromisoformat(row.get("date", "")) <= day:
                lines.append(
                    " | ".join(row.get(key, "") for key in ("date", "type", "label", "keywords", "vibe", "heat"))
                )
        except ValueError:
            continue
    return "\n".join(lines[-80:]) or "（最近 14 天尚無紀錄）"


class ThreadsBrowserError(RuntimeError):
    """Threads 瀏覽器讀取設定或操作錯誤。"""


def read_browser_settings() -> tuple[list[str], int]:
    load_dotenv(ENV_PATH, override=False)
    import os
    raw_urls = os.getenv("THREADS_RESEARCH_URLS", "https://www.threads.com/")
    urls = [url.strip() for url in raw_urls.split(",") if url.strip()]
    if not urls or any(not url.startswith(("https://www.threads.com/", "https://www.threads.net/")) for url in urls):
        raise ThreadsBrowserError("THREADS_RESEARCH_URLS 只能包含 threads.com 或 threads.net 網址。")
    try:
        maximum = int(os.getenv("THREADS_RESEARCH_MAX_POSTS", "40"))
    except ValueError as exc:
        raise ThreadsBrowserError("THREADS_RESEARCH_MAX_POSTS 必須是整數。") from exc
    return urls[:10], max(10, min(maximum, 80))


def collect_visible_posts(urls: list[str], maximum: int) -> dict[str, list[dict[str, str]]]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise ThreadsBrowserError("尚未安裝 Selenium，請執行 pip install -r requirements.txt。") from exc

    options = Options()
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    results: dict[str, list[dict[str, str]]] = {}
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as exc:
        raise ThreadsBrowserError(f"無法啟動專用 Chrome：{exc}") from exc

    try:
        per_url = max(10, maximum // len(urls))
        for url in urls:
            driver.get(url)
            time.sleep(5)
            cookie_names = {cookie.get("name") for cookie in driver.get_cookies()}
            if "sessionid" not in cookie_names and len(urls) == 1:
                print("[需要登入] 請在剛開啟的專用 Chrome 登入 Threads；程式最多等待 5 分鐘並自動繼續。")
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    cookie_names = {cookie.get("name") for cookie in driver.get_cookies()}
                    if "sessionid" in cookie_names:
                        break
                    time.sleep(2)
                else:
                    raise ThreadsBrowserError("等待 Threads 登入逾時；請重新執行並在 5 分鐘內完成登入。")
                driver.get(url)
                time.sleep(6)

            posts: dict[str, dict[str, str]] = {}
            unchanged_rounds = 0
            for _ in range(15):
                previous_count = len(posts)
                found = driver.execute_script(
                    """
                    const out = [];
                    const cards = [...document.querySelectorAll('div[data-pressable-container="true"]')];
                    for (const card of cards) {
                      const text = (card.innerText || '').trim();
                      const link = card.querySelector('a[href*="/post/"]');
                      if (link && text.length >= 20 && text.length <= 2400) {
                        out.push({href: link.href, text: text.slice(0, 1200)});
                      }
                    }
                    return out;
                    """
                )
                for item in found or []:
                    href = str(item.get("href", ""))
                    text = " ".join(str(item.get("text", "")).split())
                    if href and text:
                        posts[href] = {"text": text[:500], "timestamp": "畫面近期貼文"}
                if len(posts) >= per_url or sum(len(items) for items in results.values()) + len(posts) >= maximum:
                    break
                unchanged_rounds = unchanged_rounds + 1 if len(posts) == previous_count else 0
                driver.execute_script(
                    "const cards=document.querySelectorAll('div[data-pressable-container=\"true\"]');"
                    "if(cards.length){cards[cards.length-1].scrollIntoView({block:'end'});}else{window.scrollBy(0,900);}"
                )
                time.sleep(2.5)
                if unchanged_rounds >= 4:
                    break

            results[url] = list(posts.values())[:per_url]
            print(f"[Threads] {url}：讀取 {len(results[url])} 則可見貼文")
        if sum(len(items) for items in results.values()) < 3:
            raise ThreadsBrowserError("可讀取貼文少於 3 則；請確認專用 Chrome 已登入，且網址能顯示貼文。")
        return results
    finally:
        driver.quit()


def compact_posts(results: dict[str, list[dict[str, str]]]) -> str:
    sections = []
    for source_url, posts in results.items():
        lines = [f"[來源頁面：{source_url}] 共 {len(posts)} 則"]
        lines.extend(f"- {post['timestamp']}｜{post['text']}" for post in posts)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def build_prompt(scope: str, sources: list[str], posts: str, history: str, day: date) -> str:
    source_lines = "\n".join(f"- {url}" for url in sources)
    return f"""今天是 {day.isoformat()}。以下是專用 Chrome 從 Threads 頁面讀到的前幾則可見貼文。請做一份極短的輕量生態觀察。

觀察頁面（最多 10 個）：
{source_lines}

要求：
- 只選最近可觀察、適合赫湦轉化的 3～8 個 signals。
- 不保存或引用原文，不複製句子，不列帳號、網址或長篇事件經過。
- 搜尋證據不足時降低 heat，notes 明確寫「訊號有限」；不得捏造流行度。
- 整體低氣壓只記為 mood，不評論具體事件。
- label、notes、today_mood 都要短；conversion_advice 限 1～3 句。
- hexing_angle 必須轉成赫湦自己的日常、正能量、好笑、可愛或低壓陪伴角度。

【Threads 畫面擷取結果】
{posts}

【觀察規則】
{scope}

【既有近 14 天摘要（只用來判斷重複，不代表今天仍流行）】
{history}
"""


def validate(result: dict[str, Any]) -> list[dict[str, str]]:
    signals = result.get("signals")
    if not isinstance(signals, list) or not 3 <= len(signals) <= 8:
        raise GeminiAPIError("生態調查必須整理 3～8 筆 signals。")
    normalized = []
    for signal in signals:
        if not isinstance(signal, dict):
            raise GeminiAPIError("生態 signal 格式錯誤。")
        clean = {key: str(signal.get(key, "")).strip().replace("\n", " ") for key in FIELDS if key not in {"date", "days_seen"}}
        if clean["type"] not in ALLOWED_TYPES or clean["heat"] not in ALLOWED_HEAT:
            raise GeminiAPIError("生態 signal 的 type 或 heat 不合法。")
        if any(not clean[key] for key in ("label", "keywords", "vibe", "hexing_angle", "notes")):
            raise GeminiAPIError("生態 signal 有空白欄位。")
        normalized.append(clean)
    return normalized


def add_frequency(signals: list[dict[str, str]], rows: list[dict[str, str]], day: date) -> None:
    cutoff = day - timedelta(days=13)
    for signal in signals:
        seen_dates = {day.isoformat()}
        label = signal["label"].casefold()
        keywords = {item.strip().casefold() for item in signal["keywords"].replace("、", ",").split(",") if item.strip()}
        for row in rows:
            try:
                row_day = date.fromisoformat(row.get("date", ""))
            except ValueError:
                continue
            row_text = f"{row.get('label', '')} {row.get('keywords', '')}".casefold()
            if cutoff <= row_day <= day and (label == row.get("label", "").casefold() or any(word in row_text for word in keywords)):
                seen_dates.add(row_day.isoformat())
        signal["date"] = day.isoformat()
        signal["days_seen"] = str(len(seen_dates))


def append_csv(signals: list[dict[str, str]]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    if needs_header:
        # Excel on Windows relies on the UTF-8 BOM to recognize Traditional Chinese.
        CSV_PATH.write_text("", encoding="utf-8-sig")
    elif not CSV_PATH.read_bytes().startswith(b"\xef\xbb\xbf"):
        # Preserve existing rows while repairing files created without a BOM.
        content = CSV_PATH.read_text(encoding="utf-8")
        CSV_PATH.write_text(content, encoding="utf-8-sig")
    with CSV_PATH.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerows(signals)


def write_report(result: dict[str, Any], signals: list[dict[str, str]]) -> None:
    repeated = sorted((signal for signal in signals if int(signal["days_seen"]) > 1), key=lambda item: int(item["days_seen"]), reverse=True)[:3]
    repeat_lines = [f"{index}. {item['label']}（近 14 天 {item['days_seen']} 天）" for index, item in enumerate(repeated, 1)]
    if not repeat_lines:
        repeat_lines = ["1. 目前沒有明顯重複 signal。"]
    signal_lines = [f"{index}. {item['label']}｜{item['vibe']}｜{item['hexing_angle']}" for index, item in enumerate(signals, 1)]
    report = "\n".join([
        "# 今日 Threads 生態簡報", "", "## 今日氣氛", str(result["today_mood"]).strip(), "",
        "## 今日可用 signals", *signal_lines, "", "## 最近 7～14 天重複出現", *repeat_lines, "",
        "## 給赫湦的轉化建議", str(result["conversion_advice"]).strip(), "",
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_suffix(".md.tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(REPORT_PATH)


def main() -> int:
    try:
        scope = SCOPE_PATH.read_text(encoding="utf-8").strip()
        today = date.today()
        rows = read_rows()
        if any(row.get("date") == today.isoformat() for row in rows):
            raise ThreadsBrowserError("今天的生態 signals 已存在，為避免重複寫入而停止。")
        urls, maximum = read_browser_settings()
        posts = collect_visible_posts(urls, maximum)
        result = GeminiClient().generate_json(
            prompt=build_prompt(scope, urls, compact_posts(posts), recent_context(rows, today), today),
            response_schema=SCHEMA,
            system_instruction="你是輕量 Threads 社群趨勢整理員。只根據提供的 Threads 畫面擷取結果輸出精簡 JSON 摘要，絕不搬運原文。",
        )
        signals = validate(result)
        add_frequency(signals, rows, today)
        append_csv(signals)
        write_report(result, signals)
    except (OSError, GeminiAPIError, ThreadsBrowserError) as exc:
        print(f"[失敗] {exc}")
        return 1
    print(f"[完成] 已新增 {len(signals)} 筆生態 signals：{CSV_PATH}")
    print(f"[完成] 已更新短摘要：{REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
