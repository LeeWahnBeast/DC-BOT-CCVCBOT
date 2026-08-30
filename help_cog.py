"""
help_cog.py
===========
Lệnh /help — liệt kê danh sách lệnh của bot kèm hướng dẫn chơi cơ bản.
Ai cũng dùng được (không giới hạn Owner/Admin), chỉ riêng phần "Lệnh quản
trị" ở cuối là liệt kê tên lệnh admin để biết mặt, KHÔNG cho phép chạy nếu
không có quyền (quyền vẫn kiểm tra như cũ ở từng lệnh gốc).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


def build_help_container() -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.gold())

    container.add_item(discord.ui.TextDisplay(
        "# 🎣 Hướng Dẫn Câu Cá Vạn Cân"
    ))
    container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.TextDisplay(
        "**📖 Cách chơi cơ bản**\n"
        "1️⃣ Dùng `/câu_cá` để thả cần, chờ cá cắn câu rồi bấm **Kéo!** đúng nhịp "
        "để không bị đứt dây.\n"
        "2️⃣ Cá câu được sẽ nằm trong kho — dùng `/bán` để đổi thành Vàng.\n"
        "3️⃣ Dùng Vàng ở `/đồ_câu_lão_bát` để mua cần câu mới, kỹ năng hỗ trợ "
        "và mồi câu.\n"
        "4️⃣ Trang bị kỹ năng đã mua vào các ô trong cùng shop kỹ năng để dùng "
        "trong lúc kéo cá.\n"
        "5️⃣ Xem `/thông-tin` để theo dõi Cấp, EXP, Năng lượng và kỹ năng đang "
        "trang bị."
    ))
    container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.TextDisplay(
        "**📜 Danh sách lệnh**\n"
        "`/câu_cá` — Thả cần câu cá!\n"
        "`/bán` — Xem kho cá và bán cá lấy Vàng\n"
        "`/đồ_câu_lão_bát` — Shop gộp: mua cần câu, kỹ năng và mồi câu\n"
        "`/chọn_map` — Chọn khu vực câu cá\n"
        "`/thời_tiết` — Xem thời tiết câu cá hiện tại\n"
        "`/thông-tin` — Xem thông tin nhân vật (Vàng, Cấp, EXP...)\n"
        "`/bảng_xếp_hạng` — Bảng xếp hạng cân nặng cá & Vàng đang có\n"
        "`/help` — Xem lại hướng dẫn này"
    ))
    container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.TextDisplay(
        "**🛠️ Lệnh quản trị** _(cần quyền Admin/Owner)_\n"
        "`/tạo-code` — Tạo code đổi thưởng (Vàng / cần câu / kỹ năng / mồi câu)\n"
        "`ccvc.baotri` — Bật/tắt chế độ bảo trì bot"
    ))
    container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.TextDisplay(
        "-# 💡 Mọi lệnh chỉ dùng được trong đúng kênh quy định của bot."
    ))

    view.add_item(container)
    return view


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Xem danh sách lệnh và hướng dẫn chơi")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = build_help_container()
        await interaction.followup.send(view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
