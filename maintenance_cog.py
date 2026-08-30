"""
maintenance_cog.py
===================
Cog quản lý chế độ BẢO TRÌ toàn bộ bot, dùng prefix command `ccvc.`

LỆNH
----
ccvc.baotri <lý do...> <biến thể>
    Bật chế độ bảo trì: TOÀN BỘ lệnh khác (slash + prefix) sẽ bị chặn và
    trả lời bằng lý do bảo trì. Đồng thời đổi trạng thái (presence) của bot.

    <biến thể> (từ cuối cùng trong lệnh, không phân biệt hoa/thường, có
    dấu hay không dấu đều được):
        nhe / nhẹ / binhthuong / bình thường  -> trạng thái "Đang chờ" (Idle)
        nang / nặng                            -> trạng thái "Không làm phiền" (DND)

    Ví dụ:
        ccvc.baotri Đang nâng cấp hệ thống câu cá nhẹ
        ccvc.baotri Sập server đang khắc phục nặng

ccvc.baotri het   (hoặc: tat / off / huy)
    Tắt chế độ bảo trì, mọi lệnh hoạt động lại bình thường, trạng thái bot
    trở về Online.

Chỉ Owner (xem firebase_db.OWNER_IDS) mới dùng được lệnh này.
"""

from __future__ import annotations

import unicodedata

import discord
from discord.ext import commands

from firebase_db import OWNER_IDS


def _bo_dau(text: str) -> str:
    """Bỏ dấu tiếng Việt + hạ thường, để so khớp biến thể không cần gõ dấu."""
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D").lower().strip()


_OFF_KEYWORDS = {"het", "tat", "off", "huy", "huybaotri", "tatbaotri"}
_IDLE_KEYWORDS = {"nhe", "binhthuong"}
_DND_KEYWORDS = {"nang"}


class MaintenanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Trạng thái bảo trì lưu thẳng trên đối tượng bot để main.py (check
        # toàn cục cho cả slash lẫn prefix command) đọc được.
        if not hasattr(bot, "maintenance_mode"):
            bot.maintenance_mode = False
        if not hasattr(bot, "maintenance_reason"):
            bot.maintenance_reason = ""

    @commands.command(name="baotri")
    async def baotri(self, ctx: commands.Context, *, args: str = "") -> None:
        if ctx.author.id not in OWNER_IDS:
            await ctx.reply("⚠️ Chỉ Owner mới dùng được lệnh này.", mention_author=False)
            return

        parts = args.rsplit(maxsplit=1)
        last_word = _bo_dau(parts[-1]) if parts else ""

        # --- Tắt bảo trì ---
        if last_word in _OFF_KEYWORDS or _bo_dau(args) in _OFF_KEYWORDS:
            self.bot.maintenance_mode = False
            self.bot.maintenance_reason = ""
            await self.bot.change_presence(status=discord.Status.online, activity=None)
            await ctx.reply("✅ Đã tắt chế độ bảo trì. Mọi lệnh hoạt động lại bình thường.", mention_author=False)
            return

        # --- Bật bảo trì: cần có lý do + biến thể ---
        if len(parts) < 2:
            await ctx.reply(
                "⚠️ Cú pháp: `ccvc.baotri <lý do> <nhe/binhthuong/nang>` "
                "hoặc `ccvc.baotri het` để tắt bảo trì.",
                mention_author=False,
            )
            return

        lydo, bienthe = parts[0], last_word

        if bienthe in _IDLE_KEYWORDS:
            status = discord.Status.idle
            trang_thai_text = "Đang chờ"
        elif bienthe in _DND_KEYWORDS:
            status = discord.Status.dnd
            trang_thai_text = "Không làm phiền"
        else:
            await ctx.reply(
                "⚠️ Biến thể không hợp lệ. Dùng `nhe`/`binhthuong` (Đang chờ) "
                "hoặc `nang` (Không làm phiền).",
                mention_author=False,
            )
            return

        self.bot.maintenance_mode = True
        self.bot.maintenance_reason = lydo

        await self.bot.change_presence(
            status=status,
            activity=discord.Activity(type=discord.ActivityType.custom, name=lydo),
        )

        await ctx.reply(
            f"🛠️ **Đã bật chế độ bảo trì.**\n"
            f"**Lý do:** {lydo}\n"
            f"**Trạng thái:** {trang_thai_text}\n"
            f"Toàn bộ lệnh khác sẽ bị chặn cho đến khi chạy `ccvc.baotri het`.",
            mention_author=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MaintenanceCog(bot))
