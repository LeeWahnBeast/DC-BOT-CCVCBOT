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
    """CommandTree chặn slash command ở mọi kênh khác ALLOWED_CHANNEL_ID, và
    chặn TẤT CẢ slash command khi bot đang ở chế độ bảo trì (xem
    maintenance_cog.py / lệnh prefix `ccvc.baotri`)."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        client = interaction.client
        if getattr(client, "maintenance_mode", False):
            reason = getattr(client, "maintenance_reason", "") or "Không rõ lý do."
            await interaction.response.send_message(
                f"🛠️ Bot đang bảo trì, vui lòng quay lại sau.\n**Lý do:** {reason}",
                ephemeral=True,
            )
            return False
        if interaction.channel_id != ALLOWED_CHANNEL_ID:
            await interaction.response.send_message(
                f"⚠️ Lệnh chỉ dùng được ở <#{ALLOWED_CHANNEL_ID}>!",
                ephemeral=True,
            )
            return False
        return True


# Prefix "ccvc." dùng cho lệnh quản trị (vd ccvc.baotri). Giữ thêm "!" để
# tương thích ngược nếu sau này có thêm prefix command khác.
bot = commands.Bot(command_prefix=["ccvc.", "!"], intents=intents, tree_cls=RestrictedCommandTree)
bot.maintenance_mode = False
bot.maintenance_reason = ""


@bot.check
async def _only_allowed_channel(ctx: commands.Context) -> bool:
    """Áp dụng tương tự cho prefix command (vd ccvc.baotri)."""
    # Lệnh baotri luôn được phép chạy (kể cả khi đang bảo trì) để Owner có
    # thể tắt bảo trì trở lại — chỉ cần đúng kênh cho phép.
    if ctx.guild is None or ctx.channel.id != ALLOWED_CHANNEL_ID:
        return False
    if bot.maintenance_mode and ctx.command is not None and ctx.command.name != "baotri":
        reason = bot.maintenance_reason or "Không rõ lý do."
        await ctx.reply(
            f"🛠️ Bot đang bảo trì, vui lòng quay lại sau.\n**Lý do:** {reason}",
            mention_author=False,
        )
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
        await bot.load_extension("help_cog")
        await bot.load_extension("auto_update_cog")
        await bot.load_extension("maintenance_cog")
        await bot.start(TOKEN)


if __name__ == "__main__":
    init_firebase()
    keep_alive()
    asyncio.run(main())
