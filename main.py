"""
main.py
========
Entrypoint chạy bot. Load cog câu cá vạn cân và mở web server tối thiểu
để Render (Web Service) nhận diện có port đang chạy.
"""

import asyncio
import os

import discord
from discord.ext import commands

from keep_alive import keep_alive

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = os.environ.get("GUILD_ID")  # tùy chọn, để sync slash command nhanh khi test

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


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
        await bot.start(TOKEN)


if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
