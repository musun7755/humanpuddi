"""Restart Discord bot when its heartbeat stops updating."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT_SCRIPT = ROOT / "src" / "discord_review_bot.py"
HEARTBEAT_FILE = ROOT / "data" / "discord_bot_heartbeat.json"
LOG_FILE = ROOT / "logs" / "discord_watchdog.log"
STALE_SECONDS = 10 * 60


def _log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def _pythonw() -> str:
    candidate = Path(os.environ.get("LocalAppData", "")) / "Programs" / "Python" / "Python312" / "pythonw.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _is_bot_process(pid: int) -> bool:
    if pid <= 0:
        return False
    query = (
        "Get-CimInstance Win32_Process "
        f"-Filter \"ProcessId = {pid}\" | "
        "Select-Object -ExpandProperty CommandLine"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.returncode == 0 and "discord_review_bot.py" in result.stdout


def _bot_pids() -> list[int]:
    query = (
        "Get-CimInstance Win32_Process "
        "-Filter \"Name = 'python.exe' or Name = 'pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -like '*discord_review_bot.py*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _stop_pid(pid: int) -> None:
    if not _is_bot_process(pid):
        _log(f"略過終止 pid={pid}，不是 Discord bot。")
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, timeout=20)
    _log(f"已終止無心跳 Discord bot：pid={pid}")


def _start_bot() -> None:
    subprocess.Popen(
        [_pythonw(), str(BOT_SCRIPT), "--scheduled"],
        cwd=ROOT,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _log("已啟動 Discord bot。")


def main() -> int:
    pid = 0
    checked_heartbeat = False
    if HEARTBEAT_FILE.exists():
        try:
            checked_heartbeat = True
            heartbeat = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            pid = int(heartbeat.get("pid") or 0)
            updated_at = float(heartbeat.get("updated_at") or 0)
            age = time.time() - updated_at
            status = str(heartbeat.get("status") or "unknown")
            if age <= STALE_SECONDS and _is_bot_process(pid):
                _log(f"Discord bot 正常：pid={pid}，status={status}，age={age:.0f}s")
                return 0
            _log(f"Discord bot 心跳過期：pid={pid}，status={status}，age={age:.0f}s")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _log(f"讀取心跳失敗：{exc}")
    else:
        _log("找不到 Discord bot 心跳，準備啟動。")

    if pid:
        _stop_pid(pid)
    elif not checked_heartbeat:
        for old_pid in _bot_pids():
            _stop_pid(old_pid)
    _start_bot()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
