"""Discord 常駐 Bot：只處理「重新發想」按鈕。"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import requests
from pathlib import Path
from typing import Final

import discord
import pystray
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image

from discord_notify import REGENERATE_CUSTOM_ID
from generate_reply_draft import generate_reply_draft
from threads_publish import publish_ghost_post, publish_image_post, publish_reply

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"
TRAY_ICON_FILE: Final = PROJECT_ROOT / "assets" / "pidddi.png"
LOG_FILE: Final = PROJECT_ROOT / "logs" / "discord_bot.log"
GHOST_DATA_DIR: Final = PROJECT_ROOT / "data" / "ghost_candidates"
REPLY_DATA_DIR: Final = PROJECT_ROOT / "data" / "reply_drafts"
MUTEX_NAME: Final = "Local\\HexingBotDiscordBot"


class TrayController:
    def __init__(self, bot: "HexingBot") -> None:
        self.bot = bot
        self.status = "正在啟動"
        self._connected_notice_sent = False
        image = Image.open(TRAY_ICON_FILE).convert("RGBA")
        self.icon = pystray.Icon(
            "HexingBot",
            image,
            "HexingBot｜正在啟動",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("重新啟動 Bot", self._restart),
                pystray.MenuItem("查看執行紀錄", self._open_log),
                pystray.MenuItem("結束", self._exit),
            ),
        )

    def _status_text(self, _: pystray.MenuItem) -> str:
        return f"狀態：{self.status}"

    def start(self) -> None:
        threading.Thread(target=self.icon.run, name="HexingBotTray", daemon=True).start()

    def set_status(self, status: str, notify: bool = False) -> None:
        self.status = status
        self.icon.title = f"HexingBot｜{status}"
        self.icon.update_menu()
        if notify and not self._connected_notice_sent:
            self.icon.notify("Discord Bot 已連線，可以使用指令。", "HexingBot")
            self._connected_notice_sent = True

    def _restart(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        self.set_status("正在重新啟動")
        self.bot.request_shutdown(restart=True)

    def _open_log(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.touch(exist_ok=True)
        os.startfile(LOG_FILE)

    def _exit(self, _: pystray.Icon, __: pystray.MenuItem) -> None:
        self.set_status("正在結束")
        self.bot.request_shutdown(restart=False)

    def stop(self) -> None:
        self.icon.stop()


class PublishPreviewView(discord.ui.View):
    def __init__(self, text: str, image_urls: list[str], topic_tag: str = "") -> None:
        super().__init__(timeout=900)
        self.text = text
        self.image_urls = image_urls
        self.topic_tag = topic_tag
        self.handled = False

    @discord.ui.button(label="批准發布", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.handled:
            await interaction.response.send_message("這筆發布已經處理。", ephemeral=True)
            return
        self.handled = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            post_id = await asyncio.to_thread(
                publish_image_post,
                self.text,
                self.image_urls,
                topic_tag=self.topic_tag,
            )
        except Exception as exc:
            self.handled = False
            for item in self.children:
                item.disabled = False
            await interaction.message.edit(view=self)
            await interaction.followup.send(f"發布失敗，尚未發到 Threads：{exc}", ephemeral=True)
            return
        await interaction.followup.send(f"已發布到 Threads。貼文 ID：`{post_id}`", ephemeral=True)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.handled:
            await interaction.response.send_message("這筆發布已經處理。", ephemeral=True)
            return
        self.handled = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("已取消，不會發布。", ephemeral=True)


class PublishTextModal(discord.ui.Modal, title="Threads 貼文內容"):
    文章 = discord.ui.TextInput(
        label="文章",
        placeholder="可輸入多行文字，換行會原樣保留",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=500,
        required=True,
    )
    主題 = discord.ui.TextInput(
        label="主題（選填）",
        placeholder="例如：戀愛；不用輸入 #",
        style=discord.TextStyle.short,
        max_length=50,
        required=False,
    )

    def __init__(self, image_urls: list[str]) -> None:
        super().__init__()
        self.image_urls = image_urls

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = str(self.文章).strip()
        topic_tag = str(self.主題).strip().lstrip("#").strip()
        embeds: list[discord.Embed] = []
        for index, image_url in enumerate(self.image_urls, start=1):
            embed = discord.Embed(
                title="Threads 發布預覽｜尚未發布" if index == 1 else f"圖片 {index}",
                description=text if index == 1 else None,
                color=0x5865F2,
            )
            embed.set_image(url=image_url)
            if index == 1:
                if topic_tag:
                    embed.add_field(name="主題", value=topic_tag, inline=False)
                embed.set_footer(
                    text=f"共 {len(self.image_urls)} 張圖片；只有按下「批准發布」後才會呼叫 Threads API"
                )
            embeds.append(embed)
        await interaction.response.send_message(
            embeds=embeds[:10],
            view=PublishPreviewView(text, self.image_urls, topic_tag),
        )
        if len(embeds) > 10:
            await interaction.followup.send(embeds=embeds[10:])


class GhostPreviewView(discord.ui.View):
    def __init__(self, text: str, topic_tag: str = "") -> None:
        super().__init__(timeout=900)
        self.text = text
        self.topic_tag = topic_tag
        self.handled = False

    @discord.ui.button(label="發布限時貼文", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.handled:
            await interaction.response.send_message("這筆發布已經處理。", ephemeral=True)
            return
        self.handled = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            post_id = await asyncio.to_thread(
                publish_ghost_post, self.text, self.topic_tag
            )
        except Exception as exc:
            self.handled = False
            for item in self.children:
                item.disabled = False
            await interaction.message.edit(view=self)
            await interaction.followup.send(
                f"發布失敗，尚未發到 Threads：{exc}", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"已發布限時貼文，24 小時後會自動消失。貼文 ID：`{post_id}`",
            ephemeral=True,
        )

    @discord.ui.button(label="略過", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.handled = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("已略過，不會發布。", ephemeral=True)


class GhostTextModal(discord.ui.Modal, title="Threads 限時貼文"):
    文章 = discord.ui.TextInput(
        label="文章",
        placeholder="輸入 24 小時後自動消失的純文字貼文",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=500,
        required=True,
    )
    主題 = discord.ui.TextInput(
        label="主題（選填）",
        placeholder="不用輸入 #",
        style=discord.TextStyle.short,
        max_length=50,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = str(self.文章).strip()
        topic_tag = str(self.主題).strip().lstrip("#").strip()
        embed = discord.Embed(
            title="Threads 限時貼文預覽｜尚未發布",
            description=text,
            color=0xF2A7C6,
        )
        if topic_tag:
            embed.add_field(name="主題", value=topic_tag, inline=False)
        embed.set_footer(text="純文字 Ghost post｜24 小時後自動消失")
        await interaction.response.send_message(
            embed=embed, view=GhostPreviewView(text, topic_tag)
        )


def _reply_path(reply_id: str) -> Path:
    return REPLY_DATA_DIR / f"{reply_id}.json"


def _write_reply_state(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _reply_embed(data: dict[str, object], footer: str = "尚未發布") -> discord.Embed:
    draft = str(data.get("draft_reply", "")).strip()
    embed = discord.Embed(
        title="Threads 留言回覆草稿",
        description=draft or "（尚無草稿，請使用「手動輸入」）",
        color=0xFEE75C,
    )
    embed.add_field(name="留言作者", value=str(data.get("author", "未知")), inline=True)
    embed.add_field(
        name="原留言", value=str(data.get("comment_text", "（無內容）"))[:1024], inline=False
    )
    embed.set_footer(text=footer)
    return embed


def _reply_view(reply_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="批准發布", style=discord.ButtonStyle.success,
            custom_id=f"hexing:reply:publish:{reply_id}",
        )
    )
    view.add_item(
        discord.ui.Button(
            label="重想一個", style=discord.ButtonStyle.primary,
            custom_id=f"hexing:reply:redo:{reply_id}",
        )
    )
    view.add_item(
        discord.ui.Button(
            label="手動輸入", style=discord.ButtonStyle.primary,
            custom_id=f"hexing:reply:manual:{reply_id}",
        )
    )
    view.add_item(
        discord.ui.Button(
            label="略過", style=discord.ButtonStyle.secondary,
            custom_id=f"hexing:reply:skip:{reply_id}",
        )
    )
    return view


class ReplyEditModal(discord.ui.Modal, title="修改 Threads 回覆"):
    回覆 = discord.ui.TextInput(
        label="回覆內容",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=500,
        required=True,
    )

    def __init__(self, reply_id: str, draft: str, message: discord.Message) -> None:
        super().__init__()
        self.reply_id = reply_id
        self.message = message
        self.回覆.default = draft

    async def on_submit(self, interaction: discord.Interaction) -> None:
        path = _reply_path(self.reply_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            await interaction.response.send_message("找不到這則回覆草稿。", ephemeral=True)
            return
        if data.get("status") != "pending":
            await interaction.response.send_message("這則回覆已經處理。", ephemeral=True)
            return
        data["draft_reply"] = str(self.回覆).strip()
        _write_reply_state(path, data)
        await interaction.response.defer(ephemeral=True)
        await self.message.edit(
            embed=_reply_embed(data, "已修改｜尚未發布"),
            view=_reply_view(self.reply_id),
        )
        await interaction.followup.send("草稿已更新。", ephemeral=True)


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
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.tree = app_commands.CommandTree(self)
        self.tray: TrayController | None = None
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.restart_requested = False

    async def setup_hook(self) -> None:
        self.event_loop = asyncio.get_running_loop()
        self.tree.add_command(publish_threads)
        self.tree.add_command(publish_ghost_thread)
        self.tree.add_command(auto_reply_on)
        self.tree.add_command(auto_reply_off)
        self.tree.add_command(auto_reply_status)
        await self.tree.sync()
        # 全域 slash command 可能被 Discord 快取一段時間；同步到 review
        # 頻道所在伺服器，讓本專案的指令修改立即生效。
        review_channel_id = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
        if review_channel_id.isdigit():
            channel = await self.fetch_channel(int(review_channel_id))
            guild = getattr(channel, "guild", None)
            if guild is not None:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        print(f"[完成] Discord Bot 已登入：{self.user}；僅保留 Threads 發布指令。")
        if self.tray:
            self.tray.set_status("已連線", notify=True)

    async def on_message(self, message: discord.Message) -> None:
        return
        embed = message.embeds[0]
        footer = embed.footer.text or ""
        marker = "reply_id:"
        if embed.title != "Threads 新留言" or marker not in footer:
            return
        reply_id = footer.rsplit(marker, 1)[-1].strip()
        if not reply_id.isdigit() or _reply_path(reply_id).exists():
            return
        fields = {field.name: field.value for field in embed.fields}
        post_text = fields.get("原貼文", "")
        author = fields.get("留言作者", "未知")
        comment_text = fields.get("留言內容", "")
        if not comment_text:
            return
        embed.set_footer(text="正在產生回覆草稿…")
        await message.edit(embed=embed)
        data: dict[str, object] = {
            "reply_id": reply_id,
            "author": author,
            "comment_text": comment_text,
            "post_text": post_text,
            "draft_reply": "",
            "status": "pending",
        }
        try:
            result = await asyncio.to_thread(
                generate_reply_draft, author, comment_text, post_text=post_text
            )
            if result.get("safe_to_draft"):
                data["draft_reply"] = str(result["draft_reply"])
                footer_text = "AI 草稿｜尚未發布"
            else:
                footer_text = f"建議人工判斷：{result.get('reason', '請手動輸入')}"
        except Exception as exc:
            footer_text = f"草稿產生失敗：{exc}"
        _write_reply_state(_reply_path(reply_id), data)
        await message.edit(
            embed=_reply_embed(data, footer_text[:2048]), view=_reply_view(reply_id)
        )

    async def on_disconnect(self) -> None:
        if self.tray:
            self.tray.set_status("連線中斷，正在重連")

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        # Discord 僅保留發布 slash command；候選與審核按鈕改由 Telegram 處理。
        return

    async def _handle_ghost_candidate(
        self, interaction: discord.Interaction, custom_id: str
    ) -> None:
        parts = custom_id.split(":", 3)
        if len(parts) != 4 or parts[2] not in {"publish", "skip"}:
            await interaction.response.send_message("無效的限時貼文操作。", ephemeral=True)
            return
        action, candidate_id = parts[2], parts[3]
        if any(character not in "0123456789-abcdefghijklmnopqrstuvwxyz" for character in candidate_id):
            await interaction.response.send_message("無效的候選編號。", ephemeral=True)
            return
        path = GHOST_DATA_DIR / f"{candidate_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            await interaction.response.send_message("找不到這則限時貼文候選。", ephemeral=True)
            return
        if data.get("status") != "pending":
            await interaction.response.send_message(
                f"這則候選已處理：{data.get('status', 'unknown')}。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "skip":
            data["status"] = "skipped"
            self._write_ghost_state(path, data)
            await self._finish_ghost_message(interaction, "已略過，不會發布。", 0x808080)
            await interaction.followup.send("已略過，不會發布。", ephemeral=True)
            return

        data["status"] = "publishing"
        self._write_ghost_state(path, data)
        try:
            post_id = await asyncio.to_thread(publish_ghost_post, str(data["text"]))
        except Exception as exc:
            data["status"] = "pending"
            self._write_ghost_state(path, data)
            await interaction.followup.send(
                f"發布失敗，候選仍可再次操作：{exc}", ephemeral=True
            )
            return
        data["status"] = "published"
        data["threads_post_id"] = post_id
        self._write_ghost_state(path, data)
        await self._finish_ghost_message(
            interaction, "已發布｜24 小時後自動消失", 0x57F287
        )
        await interaction.followup.send(
            f"已發布限時貼文。貼文 ID：`{post_id}`", ephemeral=True
        )

    @staticmethod
    def _write_ghost_state(path: Path, data: dict[str, object]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    @staticmethod
    async def _finish_ghost_message(
        interaction: discord.Interaction, footer: str, color: int
    ) -> None:
        message = interaction.message
        if message is None:
            return
        embeds = message.embeds
        if embeds:
            embed = embeds[0]
            embed.color = color
            embed.set_footer(text=footer)
            await message.edit(embed=embed, view=None)
        else:
            await message.edit(view=None)

    async def _handle_reply(
        self, interaction: discord.Interaction, custom_id: str
    ) -> None:
        parts = custom_id.split(":", 3)
        if len(parts) != 4 or parts[2] not in {
            "draft", "publish", "edit", "redo", "manual", "skip"
        }:
            await interaction.response.send_message("無效的留言回覆操作。", ephemeral=True)
            return
        action, reply_id = parts[2], parts[3]
        if not reply_id.isdigit():
            await interaction.response.send_message("無效的 Threads 留言 ID。", ephemeral=True)
            return
        if action == "draft":
            await self._create_reply_draft(interaction, reply_id)
            return

        path = _reply_path(reply_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            await interaction.response.send_message("找不到這則回覆草稿。", ephemeral=True)
            return
        if data.get("status") != "pending":
            await interaction.response.send_message(
                f"這則回覆已處理：{data.get('status', 'unknown')}。", ephemeral=True
            )
            return
        if action in {"edit", "manual"}:
            if interaction.message is None:
                await interaction.response.send_message("找不到草稿訊息。", ephemeral=True)
                return
            await interaction.response.send_modal(
                ReplyEditModal(reply_id, str(data.get("draft_reply", "")), interaction.message)
            )
            return

        if action == "redo":
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await asyncio.to_thread(
                    generate_reply_draft,
                    str(data.get("author", "未知")),
                    str(data.get("comment_text", "")),
                    post_text=str(data.get("post_text", "")),
                    previous_draft=str(data.get("draft_reply", "")),
                )
            except Exception as exc:
                await interaction.followup.send(f"重新產生失敗：{exc}", ephemeral=True)
                return
            if not result.get("safe_to_draft"):
                await interaction.followup.send(
                    f"這則留言建議人工判斷：{result.get('reason', '請手動輸入')} ",
                    ephemeral=True,
                )
                return
            data["draft_reply"] = str(result["draft_reply"])
            _write_reply_state(path, data)
            if interaction.message:
                await interaction.message.edit(
                    embed=_reply_embed(data, "已重想｜尚未發布"),
                    view=_reply_view(reply_id),
                )
            await interaction.followup.send("已換一個新草稿。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "skip":
            data["status"] = "skipped"
            _write_reply_state(path, data)
            if interaction.message:
                await interaction.message.edit(
                    embed=_reply_embed(data, "已略過，不會發布"), view=None
                )
            await interaction.followup.send("已略過，不會回覆。", ephemeral=True)
            return

        data["status"] = "publishing"
        if not str(data.get("draft_reply", "")).strip():
            await interaction.followup.send("請先使用「手動輸入」填寫回覆。", ephemeral=True)
            return
        _write_reply_state(path, data)
        try:
            post_id = await asyncio.to_thread(
                publish_reply,
                reply_id,
                str(data["draft_reply"]),
                author=str(data.get("author", "")),
                comment_text=str(data.get("comment_text", "")),
                post_text=str(data.get("post_text", "")),
                conversation_text=str(data.get("conversation_text", "")),
                source="discord_human_approved",
            )
        except Exception as exc:
            data["status"] = "pending"
            _write_reply_state(path, data)
            await interaction.followup.send(
                f"發布失敗，草稿仍可再次操作：{exc}", ephemeral=True
            )
            return
        data["status"] = "published"
        data["threads_reply_id"] = post_id
        _write_reply_state(path, data)
        if interaction.message:
            embed = _reply_embed(data, "已發布到 Threads")
            embed.color = 0x57F287
            await interaction.message.edit(embed=embed, view=None)
        await interaction.followup.send(
            f"已發布留言回覆。回覆 ID：`{post_id}`", ephemeral=True
        )

    async def _create_reply_draft(
        self, interaction: discord.Interaction, reply_id: str
    ) -> None:
        path = _reply_path(reply_id)
        if path.exists():
            await interaction.response.send_message("這則留言已經產生過草稿。", ephemeral=True)
            return
        message = interaction.message
        if message is None or not message.embeds:
            await interaction.response.send_message("找不到原留言內容。", ephemeral=True)
            return
        fields = {field.name: field.value for field in message.embeds[0].fields}
        author = fields.get("留言作者", "未知")
        comment_text = fields.get("留言內容", fields.get("留言內容｜可直接複製", ""))
        if not comment_text:
            await interaction.response.send_message("原留言內容是空白。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(generate_reply_draft, author, comment_text)
        except Exception as exc:
            await interaction.followup.send(f"產生草稿失敗：{exc}", ephemeral=True)
            return
        if not result.get("safe_to_draft"):
            reason = str(result.get("reason", "建議人工判斷。"))
            await interaction.followup.send(
                f"這則留言不適合自動產生草稿：{reason}", ephemeral=True
            )
            return
        data: dict[str, object] = {
            "reply_id": reply_id,
            "author": author,
            "comment_text": comment_text,
            "draft_reply": str(result["draft_reply"]),
            "status": "pending",
        }
        _write_reply_state(path, data)
        if interaction.channel is None:
            await interaction.followup.send("找不到 Discord 頻道。", ephemeral=True)
            return
        await interaction.channel.send(
            embed=_reply_embed(data), view=_reply_view(reply_id)
        )
        source_embed = message.embeds[0]
        source_embed.set_footer(text="已產生回覆草稿｜等待人工批准")
        await message.edit(embed=source_embed, view=None)
        await interaction.followup.send("回覆草稿已產生。", ephemeral=True)

    def request_shutdown(self, restart: bool) -> None:
        self.restart_requested = restart
        if self.event_loop and self.event_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.close(), self.event_loop)


@app_commands.command(name="發布threads", description="預覽並人工批准一篇 1～20 張圖片的 Threads 貼文")
@app_commands.describe(圖片1="必填；JPG 或 PNG", 圖片2="選填；可依序附加至圖片20")
async def publish_threads(
    interaction: discord.Interaction,
    圖片1: discord.Attachment,
    圖片2: discord.Attachment | None = None,
    圖片3: discord.Attachment | None = None,
    圖片4: discord.Attachment | None = None,
    圖片5: discord.Attachment | None = None,
    圖片6: discord.Attachment | None = None,
    圖片7: discord.Attachment | None = None,
    圖片8: discord.Attachment | None = None,
    圖片9: discord.Attachment | None = None,
    圖片10: discord.Attachment | None = None,
    圖片11: discord.Attachment | None = None,
    圖片12: discord.Attachment | None = None,
    圖片13: discord.Attachment | None = None,
    圖片14: discord.Attachment | None = None,
    圖片15: discord.Attachment | None = None,
    圖片16: discord.Attachment | None = None,
    圖片17: discord.Attachment | None = None,
    圖片18: discord.Attachment | None = None,
    圖片19: discord.Attachment | None = None,
    圖片20: discord.Attachment | None = None,
) -> None:
    load_dotenv(ENV_FILE, override=False)
    review_channel = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if str(interaction.channel_id) != review_channel:
        await interaction.response.send_message("請在指定的 review 頻道使用這個指令。", ephemeral=True)
        return
    images = [
        image
        for image in (
            圖片1, 圖片2, 圖片3, 圖片4, 圖片5, 圖片6, 圖片7, 圖片8, 圖片9, 圖片10,
            圖片11, 圖片12, 圖片13, 圖片14, 圖片15, 圖片16, 圖片17, 圖片18, 圖片19, 圖片20,
        )
        if image is not None
    ]
    invalid = [image.filename for image in images if (image.content_type or "").lower() not in {"image/jpeg", "image/png"}]
    if invalid:
        await interaction.response.send_message(
            f"只支援 JPG 或 PNG；不支援的檔案：{', '.join(invalid)}", ephemeral=True
        )
        return
    await interaction.response.send_modal(PublishTextModal([image.url for image in images]))


@app_commands.command(
    name="發布限時threads", description="預覽並人工發布一則 24 小時後消失的純文字貼文"
)
async def publish_ghost_thread(interaction: discord.Interaction) -> None:
    load_dotenv(ENV_FILE, override=False)
    review_channel = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if str(interaction.channel_id) != review_channel:
        await interaction.response.send_message(
            "請在指定的 review 頻道使用這個指令。", ephemeral=True
        )
        return
    await interaction.response.send_modal(GhostTextModal())


def _set_auto_reply(enabled: bool | None = None) -> dict[str, object]:
    url = os.getenv("RENDER_CONTROL_URL", "https://humanpuddi.onrender.com").strip().rstrip("/")
    secret = os.getenv("AUTO_REPLY_CONTROL_SECRET", "").strip()
    if not secret:
        raise RuntimeError("本機尚未設定 AUTO_REPLY_CONTROL_SECRET")
    headers = {"Authorization": f"Bearer {secret}"}
    if enabled is None:
        response = requests.get(f"{url}/auto-reply", headers=headers, timeout=30)
    else:
        response = requests.post(f"{url}/auto-reply", headers=headers, json={"enabled": enabled}, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Render HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


async def _auto_reply_command(interaction: discord.Interaction, enabled: bool | None) -> None:
    if str(interaction.channel_id) != os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip():
        await interaction.response.send_message("請在指定的 review 頻道使用這個指令。", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        state = await asyncio.to_thread(_set_auto_reply, enabled)
        label = "開啟" if state.get("enabled") else "關閉"
        await interaction.followup.send(f"Threads 自動回覆：{label}\n今日已自動回覆：{state.get('daily_count', 0)} 則", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"操作失敗：{exc}", ephemeral=True)


@app_commands.command(name="自動回覆開啟", description="開啟 Threads 安全留言自動回覆")
async def auto_reply_on(interaction: discord.Interaction) -> None:
    await _auto_reply_command(interaction, True)


@app_commands.command(name="自動回覆關閉", description="立即關閉 Threads 留言自動回覆")
async def auto_reply_off(interaction: discord.Interaction) -> None:
    await _auto_reply_command(interaction, False)


@app_commands.command(name="自動回覆狀態", description="查看 Threads 自動回覆狀態")
async def auto_reply_status(interaction: discord.Interaction) -> None:
    await _auto_reply_command(interaction, None)


def main() -> int:
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(
            None, "HexingBot 已經在右下角執行中。", "HexingBot", 0x40
        )
        ctypes.windll.kernel32.CloseHandle(mutex)
        return 0
    load_dotenv(ENV_FILE, override=False)
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_REVIEW_CHANNEL_ID", "").strip()
    if not token:
        print("[失敗] 請在 .env 設定 DISCORD_BOT_TOKEN。")
        return 1
    if not channel_id.isdigit():
        print("[失敗] DISCORD_REVIEW_CHANNEL_ID 必須是 Discord 頻道 ID。")
        return 1
    if not TRAY_ICON_FILE.exists():
        print(f"[失敗] 找不到系統匣圖示：{TRAY_ICON_FILE}")
        return 1
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    bot = HexingBot(intents=discord.Intents.default())
    tray = TrayController(bot)
    bot.tray = tray
    tray.start()
    try:
        bot.run(token, log_handler=handler, log_level=logging.INFO)
    finally:
        tray.stop()
        handler.close()
        ctypes.windll.kernel32.CloseHandle(mutex)
    if bot.restart_requested:
        os.execl(sys.executable, sys.executable, str(Path(__file__).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
