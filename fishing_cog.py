"""
Cog: Câu Cá Vạn Cân
====================
Tính năng câu cá cho Delta Mick Bot: shop cần câu, cơ chế câu/gãy cần,
gửi kết quả bằng Discord Components V2 (Container/TextDisplay/MediaGallery),
KHÔNG dùng embed.

YÊU CẦU
-------
- discord.py >= 2.4 (bản có hỗ trợ Components V2: discord.ui.LayoutView,
  discord.ui.Container, discord.ui.TextDisplay, discord.ui.MediaGallery,
  discord.ui.Separator). Nếu bot đang ở bản cũ hơn, chạy:
      pip install -U discord.py
  và kiểm tra lại tên class vì API Components V2 vẫn có thể đổi giữa các
  bản phát hành.

TÍCH HỢP VỚI BOT HIỆN TẠI
--------------------------
- get_user_data / save_user_data được import từ firebase_db.py (đọc/ghi
  nhánh "fishing/users/<user_id>" trên Firebase Realtime Database). Đổi
  DB_ROOT trong firebase_db.py nếu bot đã có sẵn cấu trúc nhánh khác.
- Điền OWNER_IDS trong firebase_db.py để owner được bypass giá cần câu
  (MICK = float("inf")) và bypass cooldown câu cá — cùng cơ chế sentinel
  mà bot đang dùng ở các hệ thống kinh tế khác.
- Nếu bot chính chưa initialize_app() Firebase ở nơi khác, gọi
  firebase_db.init_firebase() một lần lúc bot khởi động (setup_hook/on_ready)
  trước khi cog này được load.
- File ảnh gãy cần đặt cùng thư mục: assets/can_gay.png (ảnh số 5 trong yêu
  cầu gốc) — đổi ROD_BREAK_IMAGE nếu bạn để nơi khác.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from firebase_db import OWNER_IDS, get_user_data, save_user_data

ASSET_DIR = Path(__file__).parent / "assets"
ROD_BREAK_IMAGE = ASSET_DIR / "can_gay.png"


# ---------------------------------------------------------------------------
# Emoji dùng trong khung kết quả (thay id nếu emoji khác trên server của bạn)
# ---------------------------------------------------------------------------
class E:
    TOP1 = "<:top1:1541849836670947418>"
    TOP3 = "<:top3:1541849840571646043>"
    RANK_TRUYEN_THUYET = "<:12truyenthuyetcauca:1542120813212205066>"
    RANK_BAN_THANH = "<:8banthanhcauca:1542120804282531901>"
    ROD_THEP_REN = "<:5canthepren:1542915747385311232>"
    WEATHER_GIO = "<:gioto:1541471720823849050>"
    BUFF_GIAM_TG = "<:giamthoigian:1541471728658681856>"
    BAIT_CHU_SA = "<:2m:1542183289362845747>"
    FISH_NUMBER = "<:39:1541129020635086968>"


# ---------------------------------------------------------------------------
# Dữ liệu cần câu (lấy từ danh sách shop "Cần Thường Trực" bạn cung cấp)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rod:
    key: str
    name: str
    emoji: str
    dps: int                 # Sát thương/giây
    pull: int                # Lực kéo
    line_len: int             # Độ dài dây câu
    effect: str               # Hiệu ứng đặc biệt
    obtain: str                # Cách nhận
    price_mick: Optional[int] = None   # None = không bán trực tiếp, phải làm nhiệm vụ


ROD_LIST: list[Rod] = [
    Rod("tre", "Cần Tre", "🎋", 12_000, 500, 20,
        "Không", "Mua trực tiếp bằng Vàng", price_mick=1_500_000),
    Rod("pho_cot_chi_thu", "Phó Cốt Chi Thứ", "🦴", 15_000, 400, 15,
        "Mỗi đòn +500 sát thương", "Luyện từ Cá Mập Biến Dị 10 vạn cân"),
    Rod("thep_ren", "Cần Thép Ren", E.ROD_THEP_REN, 40_000, 900, 45,
        "Không", "Phần thưởng sự kiện"),
    Rod("am_thep_gan", "Âm · Thép Gân", "⛓️", 20_000, 600, 40,
        "Không", "Nhận khi hồi sinh Hạ Điếu Đế"),
    Rod("thep_gan_vibranium", "Thép Gân Vibranium", "🩶", 30_000, 700, 40,
        "Không", "Mua trực tiếp bằng Vàng", price_mick=3_000_000),
    Rod("nuot_troi", "Cần Nuốt Trời", "🐉", 25_000, 500, 35,
        "Nhận +20% sát thương câu, mỗi 200 thể lực tiêu hao +5% sát thương",
        "Nhận từ phó bản Cá Chép Kình Biến"),
    Rod("vuong_gia_dai_vat", "Vương Giả Đại Vật", "👑", 45_000, 1_000, 65,
        "Đâm Cá: đòn đầu gây thêm 5%-25% máu tối đa mục tiêu",
        "Thưởng Đại Hội Câu Cá"),
    Rod("thanh_can", "Thanh Cần", "🗡️", 50_000, 1_300, 80,
        "+100% sát thương câu Hàng Ngư Thần Bát",
        "Vượt thử thách Thập Bát Điệu Sở Y Cửu"),
    Rod("dao_moc", "Cần Đào Mộc", "🌳", 50_000, 800, 70,
        "+100% sát thương Thuần Dương Điệu", "Cần đến Côn Luân Sơn"),
    Rod("doc_cau_van_co", "Cần Độc Câu Vạn Cổ", "☠️", 250_000, 2_000, 150,
        "+100% lực kéo, -40% hồi chiêu điệu câu, -40% tiêu hao thể lực",
        "Làm từ Rùa Cá Sấu Trăm Hắc Thủy Thần"),
    Rod("phat_tran", "Cần Câu Phất Trần", "🪶", 200_000, 1_000, 100,
        "+100% sát thương loạt điệu Câu Mao Sơn, -50% tiêu hao thể lực",
        "Cần đến Ai Lao Sơn"),
    Rod("thien_truong", "Cần Câu Thiền Trượng", "🔱", 300_000, 1_200, 150,
        "+200% sát thương Thái Cực Điệu, -30% hồi chiêu câu, "
        "+200% kỹ năng câu của Biểu Ca", "Nhận Dây Âm Dương Ngư"),
    Rod("ac_ngu", "Cần Ác Ngư", "🐟", 500_000, 1_500, 100,
        "+160% sát thương câu, +100% tiêu hao thể lực",
        "Thu thập tại vùng biển Somalia"),
    Rod("danh_than", "Cần Đánh Thần", "⚡", 2_500_000, 2_000, 500,
        "+120% sát thương câu, +100% sát thương Chung Chương/Điệu Câu đỉnh cấp",
        "Nhận tại Thần Nông Cốc"),
    Rod("hien_vien", "Cần Hiên Viên", "🌟", 10_000_000, 3_000, 1_000,
        "+30% hiệu năng Điều Hồn, +200% sát thương Điệu Câu, "
        "-60% hồi chiêu Điều, -60% tiêu hao thể lực",
        "Nhận tại Cấm Địa Sở Gia"),
]
RODS: dict[str, Rod] = {r.key: r for r in ROD_LIST}
DEFAULT_ROD_KEY = "thep_ren"


# ---------------------------------------------------------------------------
# Dữ liệu cá — chỉnh/thêm tuỳ ý
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FishSpecies:
    key: str
    name: str
    min_kg: float
    max_kg: float
    base_pull: int      # Lực kéo cơ bản mà con cá này đòi hỏi
    rarity_weight: int   # trọng số random, càng cao càng dễ ra
    value_per_kg: int     # MICK thưởng mỗi kg khi bán


FISH_POOL: list[FishSpecies] = [
    FishSpecies("ca_chep", "Cá Chép", 1, 15, 300, 100, 20),
    FishSpecies("ca_rong", "Cá Rồng", 10, 60, 800, 55, 45),
    FishSpecies("ca_map", "Cá Mập", 40, 200, 1_400, 30, 80),
    FishSpecies("rua_khong_lo", "Rùa Khổng Lồ", 100, 500, 2_200, 12, 150),
    FishSpecies("xich_nhan", "Xích Nhân", 300, 900, 2_800, 5, 260),
]

RANK_TIERS = [
    # (điểm tối thiểu, nhãn, badge emoji)
    (0, "Tân Thủ Câu Cá", ""),
    (1_000, "Bán Thánh Câu Cá", E.RANK_BAN_THANH),
    (5_000, "Truyền Thuyết Câu Cá", E.RANK_TRUYEN_THUYET),
]


def rank_for_score(score: int) -> tuple[str, str]:
    label, badge = RANK_TIERS[0][1], RANK_TIERS[0][2]
    for min_score, lbl, bdg in RANK_TIERS:
        if score >= min_score:
            label, badge = lbl, bdg
    return label, badge


# ---------------------------------------------------------------------------
# Lưu trữ: get_user_data / save_user_data được import từ firebase_db.py
# (đọc/ghi nhánh "fishing/users/<user_id>" trên Firebase Realtime Database).
# ---------------------------------------------------------------------------
# Cơ chế câu cá
# ---------------------------------------------------------------------------
CAST_COOLDOWN_SECONDS = 12  # thời gian chờ câu cơ bản


def calculate_outcome(rod: Rod, luck_bonus: float) -> tuple[bool, FishSpecies, float]:
    """Roll một con cá, tính xem có câu thành công hay bị đứt/gãy cần.

    Trả về (thành_công, loài_cá, cân_nặng_kg).
    """
    fish = random.choices(FISH_POOL, weights=[f.rarity_weight for f in FISH_POOL])[0]
    weight = round(random.uniform(fish.min_kg, fish.max_kg), 1)

    # Cá càng nặng (so với khung của loài) thì lực kéo đòi hỏi càng cao
    ratio = (weight - fish.min_kg) / max(fish.max_kg - fish.min_kg, 0.01)
    required_pull = fish.base_pull * (0.7 + 0.6 * ratio)

    power_ratio = rod.pull / required_pull
    success_chance = min(0.97, max(0.03, power_ratio * 0.65 + luck_bonus))

    success = random.random() < success_chance
    return success, fish, weight


def format_time_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}p{s}s"


# ---------------------------------------------------------------------------
# Xây dựng khung kết quả bằng Components V2 (không dùng embed)
# ---------------------------------------------------------------------------
def build_fail_view(
    member: discord.Member,
    rod: Rod,
    rank_label: str,
    rank_badge: str,
    weather: str = "Trời Gió",
    buff_desc: str = "Giảm thời gian chờ câu",
) -> tuple[discord.ui.LayoutView, discord.File]:
    file = discord.File(ROD_BREAK_IMAGE, filename="can_gay.png")

    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.red())

    header = (
        f"{E.TOP1} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"🎣 **Cần:** {rod.emoji} `{rod.name}`\n"
        f"{E.WEATHER_GIO} {weather}\n"
        f"{E.BUFF_GIAM_TG}: {buff_desc}"
    )
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.MediaGallery(
        discord.MediaGalleryItem("attachment://can_gay.png")
    ))
    container.add_item(discord.ui.TextDisplay(
        "💥 **RẮC! Cần câu của bạn đã bị gãy!**\n"
        "Con cá đã giật đứt dây và bơi mất tiêu!"
    ))
    view.add_item(container)
    return view, file


def build_success_view(
    member: discord.Member,
    rod: Rod,
    rank_label: str,
    rank_badge: str,
    fish: FishSpecies,
    weight_kg: float,
    weather: str = "Trời Gió",
    buff_desc: str = "Giảm thời gian chờ câu",
    bait_name: Optional[str] = None,
    bait_luck: float = 0.0,
    bait_time_left: Optional[str] = None,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.gold())

    header = (
        f"{E.TOP3} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"🎣 **Cần:** {rod.emoji} `{rod.name}`\n"
        f"{E.WEATHER_GIO} {weather}\n"
        f"{E.BUFF_GIAM_TG}: {buff_desc}"
    )
    if bait_name:
        header += (
            f"\n✨ **Mồi đang dùng:** {E.BAIT_CHU_SA} **{bait_name}** "
            f"(+{bait_luck:.2%} luck) - Còn `{bait_time_left}`"
        )
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"**Chúc mừng bạn đã câu được:**\n**Tên cá:** {fish.name}"
    ))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"# {E.FISH_NUMBER}\n**Cân nặng:** `{weight_kg} kg`"
    ))
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# Shop cần câu — cũng bằng Components V2, phân trang từng cây
# ---------------------------------------------------------------------------
class RodShopView(discord.ui.LayoutView):
    def __init__(self, user_id: int, index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.index = index
        self._render()

    def _render(self) -> None:
        self.clear_items()
        rod = ROD_LIST[self.index]
        data = get_user_data(self.user_id)
        owned = rod.key in data["unlocked_rods"]

        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay(f"## {rod.emoji} {rod.name}"))

        price_line = (
            f"💰 Giá: `{rod.price_mick:,} MICK`" if rod.price_mick is not None
            else "🔒 Không bán trực tiếp"
        )
        stats = (
            f"**Sát thương/giây:** `{rod.dps:,}`\n"
            f"**Lực kéo:** `{rod.pull:,}`\n"
            f"**Độ dài dây câu:** `{rod.line_len}`\n"
            f"**Hiệu ứng đặc biệt:** {rod.effect}\n"
            f"**Cách nhận:** {rod.obtain}\n"
            f"{price_line}"
        )
        container.add_item(discord.ui.TextDisplay(stats))
        container.add_item(discord.ui.Separator())

        nav_row = discord.ui.ActionRow()
        prev_btn = discord.ui.Button(
            label="◀ Trước", style=discord.ButtonStyle.secondary,
            disabled=self.index == 0,
        )
        prev_btn.callback = self._go_prev
        next_btn = discord.ui.Button(
            label="Sau ▶", style=discord.ButtonStyle.secondary,
            disabled=self.index == len(ROD_LIST) - 1,
        )
        next_btn.callback = self._go_next
        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)
        container.add_item(nav_row)

        action_row = discord.ui.ActionRow()
        if owned:
            equip_btn = discord.ui.Button(label="Đang/Chọn dùng", style=discord.ButtonStyle.success)
            equip_btn.callback = self._equip
            action_row.add_item(equip_btn)
        elif rod.price_mick is not None:
            buy_btn = discord.ui.Button(label="Mở Khóa", style=discord.ButtonStyle.primary)
            buy_btn.callback = self._buy
            action_row.add_item(buy_btn)
        else:
            locked_btn = discord.ui.Button(
                label="Cần nhiệm vụ để mở khóa", style=discord.ButtonStyle.secondary,
                disabled=True,
            )
            action_row.add_item(locked_btn)
        container.add_item(action_row)

        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Đây không phải shop của bạn!", ephemeral=True
            )
            return False
        return True

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.index = max(0, self.index - 1)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.index = min(len(ROD_LIST) - 1, self.index + 1)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        rod = ROD_LIST[self.index]
        data = get_user_data(self.user_id)
        if rod.key in data["unlocked_rods"]:
            await interaction.response.send_message("Bạn đã sở hữu cần này rồi!", ephemeral=True)
            return
        if data["mick"] < (rod.price_mick or 0):
            await interaction.response.send_message(
                f"Bạn không đủ MICK! Cần `{rod.price_mick:,}` MICK.", ephemeral=True
            )
            return
        data["mick"] -= rod.price_mick
        data["unlocked_rods"].append(rod.key)
        save_user_data(self.user_id, data)
        self._render()
        await interaction.response.edit_message(view=self)

    async def _equip(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        rod = ROD_LIST[self.index]
        data = get_user_data(self.user_id)
        data["rod"] = rod.key
        save_user_data(self.user_id, data)
        await interaction.response.send_message(
            f"Đã trang bị {rod.emoji} `{rod.name}`!", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
class CauCaVanCan(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="câu_cá", description="Thả cần câu cá vạn cân!")
    async def cau_ca(self, interaction: discord.Interaction) -> None:
        data = get_user_data(interaction.user.id)

        now = time.time()
        remaining = CAST_COOLDOWN_SECONDS - (now - data["last_cast"])
        if remaining > 0 and interaction.user.id not in OWNER_IDS:
            await interaction.response.send_message(
                f"⏳ Cần câu đang hồi chiêu, chờ thêm `{remaining:.1f}s` nữa nhé!",
                ephemeral=True,
            )
            return

        rod = RODS.get(data["rod"], RODS[DEFAULT_ROD_KEY])

        luck_bonus = 0.0
        bait_name = None
        bait_time_left = None
        bait = data.get("bait")
        if bait and bait.get("expires_at", 0) > now:
            luck_bonus = bait["luck"]
            bait_name = bait["name"]
            bait_time_left = format_time_left(bait["expires_at"] - now)
        elif bait:
            data["bait"] = None  # mồi đã hết hạn

        await interaction.response.defer()

        success, fish, weight = calculate_outcome(rod, luck_bonus)
        data["last_cast"] = now

        rank_label, rank_badge = rank_for_score(data["score"])

        if not success:
            data["score"] = max(0, data["score"] - 5)
            save_user_data(interaction.user.id, data)
            view, file = build_fail_view(interaction.user, rod, rank_label, rank_badge)
            await interaction.followup.send(view=view, files=[file])
            return

        reward = round(fish.value_per_kg * weight)
        data["mick"] += reward
        data["score"] += 10
        save_user_data(interaction.user.id, data)

        view = build_success_view(
            interaction.user, rod, rank_label, rank_badge, fish, weight,
            bait_name=bait_name, bait_luck=luck_bonus, bait_time_left=bait_time_left,
        )
        await interaction.followup.send(view=view)

    @app_commands.command(name="shop_cần", description="Xem và mở khóa cần câu")
    async def shop_can(self, interaction: discord.Interaction) -> None:
        view = RodShopView(user_id=interaction.user.id)
        await interaction.response.send_message(view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CauCaVanCan(bot))
