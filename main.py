"""
main.py
========
Entrypoint chạy bot. Load cog câu cá vạn cân + cog update log AI, mở web
server tối thiểu để Render (Web Service) nhận diện có port đang chạy.

GIỚI HẠN KÊNH LỆNH
-------------------
TOÀN BỘ lệnh (slash command lẫn prefix command) chỉ dùng được trong đúng 1
kênh ALLOWED_CHANNEL_ID. Dùng ở kênh khác (kể cả DM) sẽ bị từ chối kèm
thông báo ephemeral. Chặn ở tầng CommandTree/global check nên KHÔNG cần sửa
từng lệnh riêng lẻ trong các cog.
"""

import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands

from keep_alive import keep_alive
from firebase_db import init_firebase

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = os.environ.get("GUILD_ID")  # tùy chọn, để sync slash command nhanh khi test

# Kênh DUY NHẤT được phép gõ lệnh (áp dụng cho mọi lệnh của bot).
ALLOWED_CHANNEL_ID = 1543098261705855096

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class RestrictedCommandTree(app_commands.CommandTree):
    """CommandTree chặn slash command ở mọi kênh khác ALLOWED_CHANNEL_ID."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != ALLOWED_CHANNEL_ID:
            await interaction.response.send_message(
                f"⚠️ Lệnh chỉ dùng được ở <#{ALLOWED_CHANNEL_ID}>!",
                ephemeral=True,
            )
            return False
        return True


bot = commands.Bot(command_prefix="!", intents=intents, tree_cls=RestrictedCommandTree)


@bot.check
async def _only_allowed_channel(ctx: commands.Context) -> bool:
    """Áp dụng tương tự cho prefix command (vd !updatelog)."""
    if ctx.guild is None or ctx.channel.id != ALLOWED_CHANNEL_ID:
        return False
    return True


@bot.event
async def on_ready():
    print(f"Đã đăng nhập: {bot.user} (ID: {bot.user.id})")
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    else:
        synced = await bot.tree.sync()
    print(f"Đã sync {len(synced)} slash command(s)")


async def main() -> None:
    async with bot:
        await bot.load_extension("fishing_cog")
        await bot.load_extension("update_log_cog")
        await bot.start(TOKEN)


if __name__ == "__main__":
    init_firebase()
    keep_alive()
    asyncio.run(main())
