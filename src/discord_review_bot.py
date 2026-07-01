"""Discord 常駐 Bot：只處理「重新發想」按鈕。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import discord
from dotenv import load_dotenv

from discord_notify import REGENERATE_CUSTOM_ID

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"


class RegenerateView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="重新發想",
        style=discord.ButtonStyle.primary,
        custom_id=REGENERATE_CUSTOM_ID,
    )
    async def regenerate(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        process = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(PROJECT_ROOT / "src" / "regenerate_today.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (process.stdout or process.stderr).strip()
        if process.returncode == 3:
            await interaction.followup.send(
                "今日已重新發想 5 次，建議先挑一個方向或明天再產。", ephemeral=True
            )
        elif process.returncode in (0, 2):
            await interaction.followup.send("已重新生成 3 則候選。", ephemeral=True)
        else:
            await interaction.followup.send(
                f"重新發想失敗：{output[-1200:] or '請查看 error 頻道或本機視窗。'}",
                ephemeral=True,
            )


class HexingBot(discord.Client):
    async def setup_hook(self) -> None:
        self.add_view(RegenerateView())

    async def on_ready(self) -> None:
        print(f"[完成] Discord Bot 已登入：{self.user}；重新發想按鈕服務已啟動。")


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if not token:
        print("[失敗] 請在 .env 設定 DISCORD_BOT_TOKEN。")
        return 1
    if not channel_id.isdigit():
        print("[失敗] DISCORD_REVIEW_CHANNEL_ID 必須是 Discord 頻道 ID。")
        return 1
    HexingBot(intents=discord.Intents.default()).run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
