"""Ping the Render webhook so the free instance is less likely to sleep."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
LOG_FILE = ROOT / "logs" / "render_keepalive.log"


def _log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    base_url = os.getenv("RENDER_CONTROL_URL", "https://humanpuddi.onrender.com").strip().rstrip("/")
    if not base_url:
        _log("失敗：RENDER_CONTROL_URL 為空。")
        return 1

    try:
        health = requests.get(f"{base_url}/health", timeout=30)
        health.raise_for_status()

        secret = os.getenv("AUTO_REPLY_CONTROL_SECRET", "").strip()
        if secret:
            state_response = requests.get(
                f"{base_url}/auto-reply",
                headers={"Authorization": f"Bearer {secret}"},
                timeout=30,
            )
            state_response.raise_for_status()
            state = state_response.json()
            _log(
                "Render 正常；auto_reply="
                f"{bool(state.get('enabled'))}；daily_count={state.get('daily_count', 0)}"
            )
        else:
            _log("Render 正常；未設定 AUTO_REPLY_CONTROL_SECRET，略過狀態檢查。")
        return 0
    except requests.RequestException as exc:
        _log(f"失敗：{exc}")
    except json.JSONDecodeError as exc:
        _log(f"失敗：auto-reply 狀態不是 JSON：{exc}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
