"""
fishing_cog.py
====================
Cog câu cá: shop cần câu, câu cá bằng minigame "Kéo" (không phải spam —
mỗi lần bấm có cooldown chống spam, dây câu có giới hạn độ dài và sẽ ĐỨT
nếu kéo quá tay), kho cá + lệnh bán riêng, shop mồi câu.

Kết quả gửi bằng Discord Components V2 (Container/TextDisplay/
MediaGallery/Separator) — KHÔNG dùng embed, theo đúng yêu cầu gốc.

YÊU CẦU
-------
- discord.py >= 2.4 (bản có Components V2: discord.ui.LayoutView,
  discord.ui.Container, discord.ui.TextDisplay, discord.ui.MediaGallery,
  discord.ui.Separator, discord.ui.ActionRow, discord.ui.Select).

TIỀN TỆ
-------
3 loại: Vàng (chính — bán cá / mua cần / mua mồi), Kim Cương (premium),
Cash (premium, nạp thật). Xem firebase_db.py để biết schema lưu.

CƠ CHẾ CÂU CÁ (MINIGAME "KÉO")
------------------------------
- Bấm /câu_cá -> hệ thống roll 1 con cá theo cấp mà cần câu hiện có đủ
  "Lực kéo" để tiếp cận (fish_data.tiers_unlocked_for_pull).
- Mở ra khung "Kéo!" (1 nút duy nhất, sửa (edit) lại CÙNG 1 tin nhắn mỗi
  lần bấm — không gửi tin nhắn mới, không phải spam):
    * Mỗi lần bấm "Kéo!": tiến độ kéo cá (progress) tăng theo "Lực kéo"
      của cần, đồng thời độ dài dây đã dùng (tension) cũng tăng theo %
      của "Độ dài dây câu" tối đa của cần.
    * Nếu progress đạt mục tiêu trước -> câu được cá, cá vào kho.
    * Nếu tension chạm giới hạn "Độ dài dây câu" trước -> ĐỨT DÂY, cần
      câu bị gãy (mất thời gian, không mất cần vĩnh viễn).
    * Chống spam: mỗi nút chỉ nhận 1 lần bấm mỗi COOLDOWN_CLICK giây;
      bấm dồn dập trong lúc đang hồi sẽ bị bỏ qua kèm cảnh báo, không
      tính tiến độ lẫn không tăng thêm tension.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from firebase_db import OWNER_IDS, aget_user_data, asave_user_data
from fish_data import ALL_FISH, FISH_BY_KEY, FISH_BY_TIER, TIERS, FishSpecies, tiers_unlocked_for_pull
from rod_data import DEFAULT_ROD_KEY, RODS, ROD_LIST, Rod

ASSET_DIR = Path(__file__).parent / "assets"
ROD_BREAK_IMAGE = ASSET_DIR / "can_gay.png"


# ---------------------------------------------------------------------------
# Emoji dùng trong khung kết quả (icon mặc định — không phụ thuộc server nào)
# ---------------------------------------------------------------------------
class E:
    TOP1 = "🥇"
    TOP3 = "🏆"
    RANK_TRUYEN_THUYET = "🐉"
    RANK_BAN_THANH = "⭐"
    GOLD = "🪙"
    DIAMOND = "💎"
    CASH = "💵"
    BAIT = "🪱"
    FISH_NUMBER = "🐟"


RANK_TIERS = [
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


def fmt_vang(n) -> str:
    if n == float("inf"):
        return "∞"
    return f"{int(n):,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Shop mồi câu (Vàng) — tăng % may mắn (giảm tension tăng thêm khi kéo,
# tăng sát thương kéo) trong 1 khoảng thời gian.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bait:
    key: str
    name: str
    luck: float          # % luck, vd 0.15 = +15%
    duration_s: int
    price_vang: int


BAIT_SHOP: list[Bait] = [
    Bait("moi_thuong", "Mồi Thường", 0.05, 30 * 60, 50_000),
    Bait("moi_chu_sa", "Mồi Chu Sa", 0.15, 30 * 60, 300_000),
    Bait("moi_hoang_kim", "Mồi Hoàng Kim", 0.30, 60 * 60, 1_200_000),
]
BAITS: dict[str, Bait] = {b.key: b for b in BAIT_SHOP}


# ---------------------------------------------------------------------------
# Cơ chế câu cá
# ---------------------------------------------------------------------------
CAST_COOLDOWN_SECONDS = 12       # thời gian hồi giữa 2 lần /câu_cá
CLICK_COOLDOWN_SECONDS = 0.6      # chống spam nút "Kéo!"
REEL_TIMEOUT_SECONDS = 45.0        # không thao tác quá lâu -> hết hạn cứng, dừng ván
IDLE_TENSION_PER_SECOND = 3.0      # % độ căng dây tăng thêm mỗi giây KHÔNG bấm "Kéo!"
IDLE_TICK_SECONDS = 1.0            # tần suất kiểm tra/tăng tension khi đứng yên


def roll_fish(rod: Rod) -> FishSpecies:
    """Chọn 1 con cá theo cấp mà lực kéo của cần hiện có thể tiếp cận.
    Cấp cao hơn có trọng số random thấp hơn (khó gặp hơn); trong 1 cấp,
    cá giá cao hơn cũng hiếm hơn."""
    tiers = tiers_unlocked_for_pull(rod.pull)
    if not tiers:
        tiers = [t for t in TIERS if FISH_BY_TIER[t.key]][:1]

    tier_weights = [1.0 / (i + 1) for i in range(len(tiers))]
    tier = random.choices(tiers, weights=tier_weights)[0]

    pool = FISH_BY_TIER[tier.key]
    max_price = max(f.price for f in pool)
    fish_weights = [ (max_price / f.price) ** 0.5 for f in pool ]
    return random.choices(pool, weights=fish_weights)[0]


def compute_challenge(rod: Rod, fish: FishSpecies) -> tuple[float, float]:
    """Tính (target_progress, tension_per_click_max) cho ván kéo cá.
    Thiết kế theo tỉ lệ RIÊNG của từng cần (không phụ thuộc tuyệt đối vào
    độ lớn số liệu giữa các cần khác nhau) để cần yếu/mạnh đều cần khoảng
    5-12 lần bấm "Kéo!" hợp lý, cá đắt hơn trong cùng 1 cấp thì dai hơn."""
    pool = FISH_BY_TIER[fish.tier_key]
    max_price = max(f.price for f in pool)
    price_ratio = fish.price / max_price  # 0..1, càng lớn cá càng "dai"

    clicks_needed = random.uniform(4.0, 9.0) * (0.6 + 0.7 * price_ratio)
    target = rod.pull * clicks_needed
    return target, clicks_needed


def format_time_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}p{s}s"


def make_bar(ratio: float, size: int = 14, fill: str = "█", empty: str = "░") -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * size)
    return fill * filled + empty * (size - filled)


# ---------------------------------------------------------------------------
# Khung kết quả (Components V2)
# ---------------------------------------------------------------------------
def build_fail_view(
    member: discord.Member,
    rod: Rod,
    rank_label: str,
    rank_badge: str,
    reason: str = "Con cá đã giật đứt dây và bơi mất tiêu!",
) -> tuple[discord.ui.LayoutView, discord.File]:
    file = discord.File(ROD_BREAK_IMAGE, filename="can_gay.png")

    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.red())

    header = (
        f"{E.TOP1} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"🎣 **Cần:** {rod.emoji} `{rod.name}`"
    )
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.MediaGallery(
        discord.MediaGalleryItem("attachment://can_gay.png")
    ))
    container.add_item(discord.ui.TextDisplay(
        f"💥 **RẮC! Cần câu của bạn đã bị gãy!**\n{reason}"
    ))
    view.add_item(container)
    return view, file


def build_success_view(
    member: discord.Member,
    rod: Rod,
    rank_label: str,
    rank_badge: str,
    fish: FishSpecies,
    bait_name: Optional[str] = None,
    bait_luck: float = 0.0,
    bait_time_left: Optional[str] = None,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.gold())

    header = (
        f"{E.TOP3} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"🎣 **Cần:** {rod.emoji} `{rod.name}`"
    )
    if bait_name:
        header += (
            f"\n✨ **Mồi đang dùng:** {E.BAIT} **{bait_name}** "
            f"(+{bait_luck:.0%} may mắn) - Còn `{bait_time_left}`"
        )
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"**🎉 Chúc mừng bạn đã câu được:**\n"
        f"**Tên cá:** {fish.name}\n"
        f"**Khối lượng:** `{fish.weight_label}`\n"
        f"**Đơn giá bán:** {E.GOLD} `{fmt_vang(fish.price)}` Vàng / con"
    ))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"# {E.FISH_NUMBER}\nDùng `/bán` để đổi cá trong kho ra Vàng."
    ))
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# Minigame "Kéo!" — sửa (edit) lại đúng 1 tin nhắn, có cooldown chống spam.
# ---------------------------------------------------------------------------
class ReelView(discord.ui.LayoutView):
    def __init__(
        self,
        member: discord.Member,
        rod: Rod,
        fish: FishSpecies,
        luck_bonus: float,
        rank_label: str,
        rank_badge: str,
        bait_name: Optional[str],
        bait_time_left: Optional[str],
        on_finish,
    ):
        super().__init__(timeout=REEL_TIMEOUT_SECONDS)
        self.member = member
        self.rod = rod
        self.fish = fish
        self.luck_bonus = luck_bonus
        self.rank_label = rank_label
        self.rank_badge = rank_badge
        self.bait_name = bait_name
        self.bait_time_left = bait_time_left
        self.on_finish = on_finish  # async callback(success: bool)

        self.target, _ = compute_challenge(rod, fish)
        self.progress = 0.0
        self.tension_max = 100.0  # % — quy về 0-100 cho dễ hiển thị, tương ứng độ dài dây câu tối đa của cần
        self.tension = 0.0
        self.last_click = 0.0
        self.last_action_at = time.time()  # mốc để tính tension tự tăng khi đứng yên
        self.finished = False
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()  # chặn _on_pull và _idle_tick edit chồng lên nhau

        self._render()
        self._idle_tick.start()

    # -- vòng lặp tension tự tăng khi không bấm "Kéo!" ------------------
    @tasks.loop(seconds=IDLE_TICK_SECONDS)
    async def _idle_tick(self) -> None:
        # message chỉ được gán SAU khi followup.send() xong (sau __init__),
        # nên vài tick đầu tiên có thể chưa có -> bỏ qua, đợi tick sau.
        if self.finished or self.message is None:
            return
        if self._lock.locked():
            return  # đang có 1 lần bấm "Kéo!" xử lý dở, đợi tick sau để tránh edit chồng

        async with self._lock:
            now = time.time()
            idle_for = now - self.last_action_at
            if idle_for < IDLE_TICK_SECONDS:
                return  # vừa có thao tác gần đây, chưa cần cộng thêm

            self.tension += IDLE_TENSION_PER_SECOND * idle_for
            self.last_action_at = now

            if self.tension >= self.tension_max:
                self.finished = True
                self._idle_tick.stop()
                self.clear_items()
                self.stop()
                view, file = build_fail_view(
                    self.member, self.rod, self.rank_label, self.rank_badge,
                    reason="Bạn đứng câu quá lâu không kéo, dây căng hết cỡ rồi đứt phựt!",
                )
                try:
                    await self.message.edit(view=view, attachments=[file])
                except discord.HTTPException:
                    pass
                await self.on_finish(False)
                return

            self._render()
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # -- render -------------------------------------------------------
    def _render(self) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.blue())
        header = (
            f"🎣 **{self.member.display_name}** đang câu...\n"
            f"**Cần:** {self.rod.emoji} `{self.rod.name}` "
            f"(Độ dài dây câu: `{self.rod.line_len}`)"
        )
        if self.bait_name:
            header += f"\n✨ Mồi: {E.BAIT} **{self.bait_name}** - Còn `{self.bait_time_left}`"
        container.add_item(discord.ui.TextDisplay(header))
        container.add_item(discord.ui.Separator())

        progress_ratio = min(1.0, self.progress / self.target) if self.target else 0.0
        tension_ratio = min(1.0, self.tension / self.tension_max)
        container.add_item(discord.ui.TextDisplay(
            f"**Có gì đó đang cắn câu!** Bấm **Kéo!** để kéo cá vào, "
            f"nhưng đừng kéo quá tay kẻo đứt dây.\n\n"
            f"Tiến độ kéo cá: `{make_bar(progress_ratio)}` {progress_ratio:.0%}\n"
            f"Độ căng dây câu: `{make_bar(tension_ratio)}` {tension_ratio:.0%}"
        ))
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        btn = discord.ui.Button(label="🎣 Kéo!", style=discord.ButtonStyle.primary)
        btn.callback = self._on_pull
        row.add_item(btn)
        container.add_item(row)

        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                "Đây không phải cần câu của bạn!", ephemeral=True
            )
            return False
        return True

    async def _on_pull(self, interaction: discord.Interaction) -> None:
        if self.finished:
            await interaction.response.defer()
            return
        if not await self._guard(interaction):
            return

        now = time.time()
        if now - self.last_click < CLICK_COOLDOWN_SECONDS:
            await interaction.response.send_message(
                "⚠️ Đừng kéo dồn dập quá, để cá lấy hơi đã rồi hẵng kéo tiếp!",
                ephemeral=True,
            )
            return
        self.last_click = now

        async with self._lock:
            if self.finished:  # có thể vừa bị idle_tick kết thúc trong lúc chờ lock
                await interaction.response.defer()
                return

            self.last_action_at = now  # có thao tác -> idle tick không cộng dồn từ mốc cũ

            dmg = self.rod.pull * random.uniform(0.9, 1.3) * (1 + self.luck_bonus * 0.5)
            self.progress += dmg

            tension_gain = 100.0 / random.uniform(6.0, 11.0) * (1 - self.luck_bonus * 0.4)
            self.tension += max(1.0, tension_gain)

            if self.progress >= self.target:
                self.finished = True
                self._idle_tick.stop()
                await self._finish(interaction, success=True)
                return
            if self.tension >= self.tension_max:
                self.finished = True
                self._idle_tick.stop()
                await self._finish(interaction, success=False)
                return

            self._render()
            await interaction.response.edit_message(view=self)

    async def _finish(self, interaction: discord.Interaction, success: bool) -> None:
        self.clear_items()
        self.stop()
        if success:
            view = build_success_view(
                self.member, self.rod, self.rank_label, self.rank_badge, self.fish,
                bait_name=self.bait_name, bait_luck=self.luck_bonus,
                bait_time_left=self.bait_time_left,
            )
            await interaction.response.edit_message(view=view, attachments=[])
        else:
            view, file = build_fail_view(self.member, self.rod, self.rank_label, self.rank_badge)
            await interaction.response.edit_message(view=view, attachments=[file])
        await self.on_finish(success)

    async def on_timeout(self) -> None:
        async with self._lock:
            if self.finished:
                return
            self.finished = True
            self._idle_tick.stop()
            self.clear_items()
            container = discord.ui.Container(accent_colour=discord.Colour.dark_grey())
            container.add_item(discord.ui.TextDisplay(
                f"💤 **{self.member.display_name}** đứng câu quá lâu, con cá đã tự bơi đi mất..."
            ))
            self.add_item(container)
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass
            await self.on_finish(None)


# ---------------------------------------------------------------------------
# Shop cần câu — Components V2, phân trang từng cây
# ---------------------------------------------------------------------------
class RodShopView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict, index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.index = index
        self._render(data)

    @classmethod
    async def create(cls, user_id: int, index: int = 0) -> "RodShopView":
        """Fetch dữ liệu Firebase (async, không block loop) rồi tạo view."""
        data = await aget_user_data(user_id)
        return cls(user_id, data, index)

    def _render(self, data: dict) -> None:
        self.clear_items()
        rod = ROD_LIST[self.index]
        owned = rod.key in data["unlocked_rods"]

        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay(
            f"## {rod.emoji} {rod.name}  ({self.index + 1}/{len(ROD_LIST)})"
        ))

        price_line = (
            f"{E.GOLD} Giá: `{fmt_vang(rod.price_vang)}` Vàng" if rod.price_vang is not None
            else "🔒 Không bán trực tiếp — xem cách nhận bên dưới"
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
            equip_btn = discord.ui.Button(label="Trang bị", style=discord.ButtonStyle.success)
            equip_btn.callback = self._equip
            action_row.add_item(equip_btn)
        elif rod.price_vang is not None:
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
        await interaction.response.defer()
        self.index = max(0, self.index - 1)
        data = await aget_user_data(self.user_id)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.index = min(len(ROD_LIST) - 1, self.index + 1)
        data = await aget_user_data(self.user_id)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        rod = ROD_LIST[self.index]
        data = await aget_user_data(self.user_id)
        if rod.key in data["unlocked_rods"]:
            await interaction.followup.send("Bạn đã sở hữu cần này rồi!", ephemeral=True)
            return
        if data["vang"] < (rod.price_vang or 0):
            await interaction.followup.send(
                f"Bạn không đủ Vàng! Cần `{fmt_vang(rod.price_vang)}` Vàng.", ephemeral=True
            )
            return
        data["vang"] -= rod.price_vang
        data["unlocked_rods"].append(rod.key)
        await asave_user_data(self.user_id, data)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _equip(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        rod = ROD_LIST[self.index]
        data = await aget_user_data(self.user_id)
        data["rod"] = rod.key
        await asave_user_data(self.user_id, data)
        await interaction.followup.send(
            f"Đã trang bị {rod.emoji} `{rod.name}`!", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Kho cá + bán cá — Components V2, phân trang theo cấp (tier)
# ---------------------------------------------------------------------------
class SellView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict, tier_index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.tier_index = tier_index
        self._render(data)

    @classmethod
    async def create(cls, user_id: int, tier_index: int = 0) -> "SellView":
        data = await aget_user_data(user_id)
        return cls(user_id, data, tier_index)

    def _owned_in_tier(self, data: dict, tier_key: str) -> list[tuple[FishSpecies, int]]:
        inv = data.get("inventory", {})
        out = []
        for fish in FISH_BY_TIER[tier_key]:
            qty = inv.get(fish.key, 0)
            if qty > 0:
                out.append((fish, qty))
        return out

    def _render(self, data: dict) -> None:
        self.clear_items()
        tier = TIERS[self.tier_index]
        owned = self._owned_in_tier(data, tier.key)
        tier_total = sum(f.price * q for f, q in owned)
        grand_total = sum(
            f.price * q for f in ALL_FISH for k, q in [(f.key, data.get("inventory", {}).get(f.key, 0))] if q > 0
        )

        container = discord.ui.Container(accent_colour=discord.Colour.green())
        container.add_item(discord.ui.TextDisplay(
            f"## 🐟 Kho Cá — {tier.label}  ({self.tier_index + 1}/{len(TIERS)})"
        ))

        if not owned:
            container.add_item(discord.ui.TextDisplay("_Bạn chưa có cá nào ở cấp này._"))
        else:
            lines = []
            for fish, qty in owned:
                lines.append(
                    f"**{fish.name}** (`{fish.weight_label}`) — SL: `{qty}` — "
                    f"Đơn giá: {E.GOLD}`{fmt_vang(fish.price)}` — "
                    f"Tổng: {E.GOLD}`{fmt_vang(fish.price * qty)}`"
                )
            container.add_item(discord.ui.TextDisplay("\n".join(lines)))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Tổng giá trị cấp này:** {E.GOLD} `{fmt_vang(tier_total)}` Vàng\n"
            f"**Tổng giá trị toàn bộ kho:** {E.GOLD} `{fmt_vang(grand_total)}` Vàng"
        ))
        container.add_item(discord.ui.Separator())

        if owned:
            select = discord.ui.Select(
                placeholder="Chọn 1 loại cá để bán toàn bộ số lượng đang có...",
                options=[
                    discord.SelectOption(
                        label=f"{fish.name} (SL {qty})",
                        description=f"{fish.weight_label} · {fmt_vang(fish.price)} Vàng/con",
                        value=fish.key,
                    )
                    for fish, qty in owned[:25]
                ],
            )
            select.callback = self._sell_selected
            row = discord.ui.ActionRow()
            row.add_item(select)
            container.add_item(row)

        nav_row = discord.ui.ActionRow()
        prev_btn = discord.ui.Button(label="◀ Trước", style=discord.ButtonStyle.secondary,
                                       disabled=self.tier_index == 0)
        prev_btn.callback = self._go_prev
        next_btn = discord.ui.Button(label="Sau ▶", style=discord.ButtonStyle.secondary,
                                       disabled=self.tier_index == len(TIERS) - 1)
        next_btn.callback = self._go_next
        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)
        container.add_item(nav_row)

        action_row = discord.ui.ActionRow()
        sell_tier_btn = discord.ui.Button(
            label=f"💰 Bán Nhanh (cấp này: {fmt_vang(tier_total)})",
            style=discord.ButtonStyle.success, disabled=tier_total == 0,
        )
        sell_tier_btn.callback = self._sell_tier
        sell_all_btn = discord.ui.Button(
            label=f"💎 Bán Nhanh (Tất Cả: {fmt_vang(grand_total)})",
            style=discord.ButtonStyle.danger, disabled=grand_total == 0,
        )
        sell_all_btn.callback = self._sell_all
        action_row.add_item(sell_tier_btn)
        action_row.add_item(sell_all_btn)
        container.add_item(action_row)

        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Đây không phải kho cá của bạn!", ephemeral=True)
            return False
        return True

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.tier_index = max(0, self.tier_index - 1)
        data = await aget_user_data(self.user_id)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.tier_index = min(len(TIERS) - 1, self.tier_index + 1)
        data = await aget_user_data(self.user_id)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _sell_selected(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        fish_key = interaction.data["values"][0]
        fish = FISH_BY_KEY.get(fish_key)
        data = await aget_user_data(self.user_id)
        qty = data.get("inventory", {}).get(fish_key, 0)
        if not fish or qty <= 0:
            await interaction.followup.send("Bạn không còn cá này trong kho!", ephemeral=True)
            return
        gained = fish.price * qty
        data["inventory"][fish_key] = 0
        data["vang"] += gained
        await asave_user_data(self.user_id, data)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _sell_tier(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        data = await aget_user_data(self.user_id)
        owned = self._owned_in_tier(data, TIERS[self.tier_index].key)
        gained = 0
        for fish, qty in owned:
            gained += fish.price * qty
            data["inventory"][fish.key] = 0
        data["vang"] += gained
        await asave_user_data(self.user_id, data)
        self._render(data)
        await interaction.edit_original_response(view=self)

    async def _sell_all(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        data = await aget_user_data(self.user_id)
        inv = data.get("inventory", {})
        gained = 0
        for fish in ALL_FISH:
            qty = inv.get(fish.key, 0)
            if qty > 0:
                gained += fish.price * qty
                inv[fish.key] = 0
        data["inventory"] = inv
        data["vang"] += gained
        await asave_user_data(self.user_id, data)
        self._render(data)
        await interaction.edit_original_response(view=self)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
class CauCaVanCan(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="câu_cá", description="Thả cần câu cá!")
    async def cau_ca(self, interaction: discord.Interaction) -> None:
        # defer() ngay lập tức trước khi đụng tới Firebase — tránh lỗi
        # "Ứng dụng không phản hồi" nếu việc đọc/ghi DB mất hơn 3 giây.
        await interaction.response.defer()

        data = await aget_user_data(interaction.user.id)

        now = time.time()
        remaining = CAST_COOLDOWN_SECONDS - (now - data["last_cast"])
        if remaining > 0 and interaction.user.id not in OWNER_IDS:
            await interaction.followup.send(
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

        data["last_cast"] = now
        await asave_user_data(interaction.user.id, data)

        fish = roll_fish(rod)
        rank_label, rank_badge = rank_for_score(data["score"])

        async def on_finish(success: Optional[bool]) -> None:
            fresh = await aget_user_data(interaction.user.id)
            if success is True:
                inv = fresh.get("inventory", {})
                inv[fish.key] = inv.get(fish.key, 0) + 1
                fresh["inventory"] = inv
                fresh["score"] = fresh.get("score", 0) + 10
            elif success is False:
                fresh["score"] = max(0, fresh.get("score", 0) - 5)
            # success is None (timeout) -> không cộng/trừ gì, cá tự bơi đi
            await asave_user_data(interaction.user.id, fresh)

        view = ReelView(
            interaction.user, rod, fish, luck_bonus, rank_label, rank_badge,
            bait_name, bait_time_left, on_finish,
        )
        view.message = await interaction.followup.send(view=view, wait=True)

    @app_commands.command(name="shop_cần", description="Xem và mở khóa cần câu")
    async def shop_can(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await RodShopView.create(user_id=interaction.user.id)
        await interaction.followup.send(view=view)

    @app_commands.command(name="bán", description="Xem kho cá và bán cá lấy Vàng")
    async def ban(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await SellView.create(user_id=interaction.user.id)
        await interaction.followup.send(view=view)

    @app_commands.command(name="mua_mồi", description="Mua mồi câu để tăng % may mắn khi câu")
    @app_commands.choices(loai_moi=[
        app_commands.Choice(name=f"{b.name} (+{b.luck:.0%} may mắn, {b.duration_s // 60} phút — {b.price_vang:,} Vàng)",
                             value=b.key)
        for b in BAIT_SHOP
    ])
    async def mua_moi(self, interaction: discord.Interaction, loai_moi: app_commands.Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        bait = BAITS[loai_moi.value]
        data = await aget_user_data(interaction.user.id)
        if data["vang"] < bait.price_vang:
            await interaction.followup.send(
                f"Bạn không đủ Vàng! Cần `{fmt_vang(bait.price_vang)}` Vàng.", ephemeral=True
            )
            return
        data["vang"] -= bait.price_vang
        data["bait"] = {
            "name": bait.name,
            "luck": bait.luck,
            "expires_at": time.time() + bait.duration_s,
        }
        await asave_user_data(interaction.user.id, data)
        await interaction.followup.send(
            f"✅ Đã dùng {E.BAIT} **{bait.name}** (+{bait.luck:.0%} may mắn, "
            f"còn `{format_time_left(bait.duration_s)}`)!",
            ephemeral=True,
        )

    @app_commands.command(name="ví", description="Xem số Vàng / Kim Cương / Cash hiện có")
    async def vi(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        data = await aget_user_data(interaction.user.id)
        rank_label, rank_badge = rank_for_score(data["score"])
        rod = RODS.get(data["rod"], RODS[DEFAULT_ROD_KEY])

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay(
            f"## 👛 Ví của {interaction.user.display_name}\n"
            f"{rank_badge} `[{rank_label}]` — Điểm: `{data['score']}`"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"{E.GOLD} **Vàng:** `{fmt_vang(data['vang'])}`\n"
            f"{E.DIAMOND} **Kim Cương:** `{fmt_vang(data['kim_cuong'])}`\n"
            f"{E.CASH} **Cash:** `{fmt_vang(data['cash'])}`\n"
            f"🎣 **Cần đang dùng:** {rod.emoji} `{rod.name}`"
        ))
        view.add_item(container)
        await interaction.followup.send(view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CauCaVanCan(bot))
