"""
update_log_cog.py
==================
Lệnh /update_log (chỉ Owner — xem firebase_db.OWNER_IDS) nhận ghi chú thay
đổi thô, gửi cho Groq AI viết lại thành các gạch đầu dòng tiếng Việt gọn
gàng, rồi đăng vào LOG_CHANNEL_ID bằng Discord Components V2 Container
(không dùng embed), theo đúng mẫu:

    # CẬP NHẬT 5.12
    <t:1787891898:f>
    **✨ Tính năng mới:**
    • Thêm phí chuyển khoản (%2) được trừ trước khi cộng tiền cho người nhận.
    • ...
    -# 4 file thay đổi · v5.02 → v5.12

YÊU CẦU
-------
- Biến môi trường GROQ_API_KEY.
- Gói `groq` (đã thêm vào requirements.txt).
- Lệnh này vẫn bị chặn ở tầng CommandTree trong main.py (RestrictedCommandTree)
  giống mọi lệnh khác — chỉ gõ được ở ALLOWED_CHANNEL_ID — nhưng NỘI DUNG
  update log luôn được ĐĂNG (post) sang LOG_CHANNEL_ID riêng, khác kênh gõ lệnh.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from firebase_db import OWNER_IDS

# Kênh đăng update log do AI soạn.
LOG_CHANNEL_ID = 1539484617663324230

# Cho phép đổi model qua biến môi trường mà không cần sửa code (model Groq
# có thể bị deprecate/đổi tên theo thời gian).
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

_SYSTEM_PROMPT = (
    "Bạn là trợ lý viết changelog (update log) cho một Discord bot, viết "
    "bằng tiếng Việt. Nhiệm vụ: nhận ghi chú thay đổi thô (có thể lộn xộn, "
    "viết tắt) và viết lại thành các gạch đầu dòng NGẮN GỌN, RÕ RÀNG, mỗi "
    "dòng bắt đầu bằng ký tự '• '. KHÔNG thêm tiêu đề, KHÔNG thêm lời dẫn, "
    "KHÔNG thêm giải thích ngoài các gạch đầu dòng. Giữ nguyên số liệu/đơn "
    "vị (%, số lượng...) nếu có trong ghi chú gốc."
)


def _get_groq_client():
    """Khởi tạo Groq client lười (lazy) — tránh crash lúc import nếu chưa
    có GROQ_API_KEY (vd môi trường dev chưa cấu hình xong)."""
    from groq import Groq  # import trễ để không bắt buộc cài nếu không dùng lệnh này

    api_key = os.environ["GROQ_API_KEY"]
    return Groq(api_key=api_key)


def _call_groq_sync(raw_notes: str) -> str:
    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": raw_notes},
        ],
        temperature=0.4,
        max_tokens=600,
    )
    return completion.choices[0].message.content.strip()


async def _generate_bullets(raw_notes: str) -> str:
    """Gọi Groq trong thread riêng (client groq là sync/blocking) và chuẩn
    hoá lại để đảm bảo mỗi dòng đều có tiền tố '• '."""
    text = await asyncio.to_thread(_call_groq_sync, raw_notes)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullets = []
    for line in lines:
        line = line.lstrip("•-*").strip()
        bullets.append(f"• {line}")
    return "\n".join(bullets) if bullets else "• (không có nội dung)"


def build_update_log_container(
    *, tu_ban: str, den_ban: str, so_file: int, bullets: str,
) -> discord.ui.LayoutView:
    ts = int(time.time())
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.blurple())
    container.add_item(discord.ui.TextDisplay(
        f"# CẬP NHẬT {den_ban}\n"
        f"<t:{ts}:f>"
    ))
    container.add_item(discord.ui.TextDisplay(
        f"**✨ Tính năng mới:**\n{bullets}"
    ))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"-# {so_file} file thay đổi · v{tu_ban} → v{den_ban}"
    ))
    view.add_item(container)
    return view


class UpdateLogCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="update_log",
        description="[Owner] Đăng update log do AI soạn vào kênh log",
    )
    @app_commands.describe(
        tu_ban="Phiên bản cũ, vd 5.02",
        den_ban="Phiên bản mới, vd 5.12",
        so_file="Số file đã thay đổi",
        ghi_chu="Ghi chú thay đổi thô (AI sẽ viết lại thành gạch đầu dòng)",
    )
    async def update_log(
        self,
        interaction: discord.Interaction,
        tu_ban: str,
        den_ban: str,
        so_file: int,
        ghi_chu: str,
    ) -> None:
        if interaction.user.id not in OWNER_IDS:
            await interaction.response.send_message(
                "⚠️ Chỉ Owner mới dùng được lệnh này.", ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            bullets = await _generate_bullets(ghi_chu)
        except Exception as exc:  # noqa: BLE001 — báo lỗi rõ ràng cho owner
            await interaction.followup.send(
                f"❌ Groq AI lỗi: `{exc}`", ephemeral=True,
            )
            return

        view = build_update_log_container(
            tu_ban=tu_ban, den_ban=den_ban, so_file=so_file, bullets=bullets,
        )

        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except discord.HTTPException as exc:
                await interaction.followup.send(
                    f"❌ Không tìm thấy kênh log: `{exc}`", ephemeral=True,
                )
                return

        await channel.send(view=view)
        await interaction.followup.send("✅ Đã đăng update log.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UpdateLogCog(bot))
