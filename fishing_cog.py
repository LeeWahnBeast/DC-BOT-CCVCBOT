"""
fishing_cog.py
====================
Cog câu cá: shop gộp "Đồ Câu Lão Bát" (/đồ_câu_lão_bát — cần câu, kỹ năng,
mồi câu trong 1 view có tab), câu cá bằng minigame "Kéo" (không phải spam —
mỗi lần bấm có cooldown chống spam, dây câu có giới hạn độ dài và sẽ ĐỨT
nếu kéo quá tay), kho cá + lệnh bán riêng.

Kết quả gửi bằng Discord Components V2 (Container/TextDisplay/
MediaGallery/Separator) — KHÔNG dùng embed, theo đúng yêu cầu gốc.

YÊU CẦU
-------
- discord.py >= 2.4 (bản có Components V2: discord.ui.LayoutView,
  discord.ui.Container, discord.ui.TextDisplay, discord.ui.MediaGallery,
  discord.ui.Separator, discord.ui.ActionRow, discord.ui.Select).

TIỀN TỆ
-------
Chỉ 1 loại: Vàng (dùng cho tất cả — bán cá / mua cần / mua mồi / mua kỹ
năng). Xem firebase_db.py để biết schema lưu.

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
- Tên cá và MÁU CÁ (dạng thanh, giảm dần từ 100% -> 0% theo mỗi lần bấm
  "Kéo!") hiển thị ngay khi bắt đầu ván câu, không chỉ khi câu xong.
- KỸ NĂNG (skill_data.py): mỗi người có SKILL_SLOTS (3) ô trang bị, mua/mở
  khóa qua /shop_kỹ_năng. Mỗi skill trang bị chỉ dùng được 1 lần/ván câu,
  tốn thể lực, hiệu ứng là trừ ngay % độ căng dây hoặc làm chậm tốc độ
  tăng độ căng dây trong vài giây — không có skill gây thêm sát thương.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from firebase_db import OWNER_IDS, aget_user_data, asave_user_data
from fish_data import (
    ALL_FISH, BOSS_FISH_KEYS, FISH_BY_KEY, FISH_BY_TIER, MAP_BY_KEY, MAPS,
    TIERS, FishSpecies, fish_in_map, tiers_unlocked_for_pull,
)
from rod_data import DEFAULT_ROD_KEY, LIMITED_ROD_LIST, RODS, ROD_LIST, Rod
from skill_data import SKILL_SHOP, SKILL_SLOTS, SKILLS, Skill, equipped_skill_objects

ASSET_DIR = Path(__file__).parent / "assets"
ROD_BREAK_IMAGE = ASSET_DIR / "can_gay.png"
SHOP_BANNER_IMAGE = ASSET_DIR / "do_cau_lao_bat.webp"


# ---------------------------------------------------------------------------
# Emoji dùng trong khung kết quả (icon mặc định — không phụ thuộc server nào)
# ---------------------------------------------------------------------------
class E:
    TOP1 = "🥇"
    TOP3 = "🏆"
    RANK_TRUYEN_THUYET = "🐉"
    RANK_BAN_THANH = "⭐"
    GOLD = "<:xu:1543162904424218644>"
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


def fmt_gia_trieu(n) -> str:
    """Hiển thị giá theo đơn vị triệu Vàng (dùng cho giá cần câu / skill —
    đã quy về bội số 1.000.000 để đồng bộ mặt bằng giá "giá triệu")."""
    if n is None:
        return "—"
    if n == float("inf"):
        return "∞"
    trieu = n / 1_000_000
    if trieu == int(trieu):
        return f"{int(trieu):,}".replace(",", ".") + " triệu"
    return f"{trieu:,.1f}".replace(",", ".") + " triệu"


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

# ---------------------------------------------------------------------------
# Thể lực (thanh năng lượng) — TÁCH RIÊNG với "độ căng dây câu" ở trên.
# Hao theo LẦN BẤM NÚT "Kéo!" (mỗi cái bấm hợp lệ -1 thể lực), tự hồi dần
# theo thời gian thực (không phụ thuộc vào có đang câu hay không).
# ---------------------------------------------------------------------------
ENERGY_BASE = 500          # thể lực tối đa ở level 1
ENERGY_PER_LEVEL = 50       # mỗi level cộng thêm bấy nhiêu thể lực tối đa (có thể chỉnh)
ENERGY_REGEN_MINUTES = 5    # tự hồi +1 thể lực mỗi X phút

# ---------------------------------------------------------------------------
# Level / EXP — câu cá thành công thì cộng EXP theo giá trị con cá (cá mắc
# hơn = nhiều EXP hơn). Số EXP cần để lên level tăng dần theo level.
# ---------------------------------------------------------------------------
EXP_BASE = 100               # EXP cần để lên từ level 1 -> level 2
EXP_PER_LEVEL_STEP = 50       # mỗi level, EXP cần lên cấp tiếp theo tăng thêm bấy nhiêu
EXP_PER_FISH_PRICE = 5_000    # quy đổi: cứ 5.000 Vàng giá cá = 1 EXP (tối thiểu 5 EXP/con)


def max_energy_for_level(level: int) -> int:
    return ENERGY_BASE + max(0, level - 1) * ENERGY_PER_LEVEL


def exp_needed_for_level(level: int) -> int:
    """Số EXP cần để đi từ `level` lên `level + 1`."""
    return EXP_BASE + max(0, level - 1) * EXP_PER_LEVEL_STEP


def exp_for_fish(fish: FishSpecies) -> int:
    return max(5, fish.price // EXP_PER_FISH_PRICE)


def add_exp(data: dict, exp_gain: int) -> tuple[dict, bool, int]:
    """Cộng EXP vào `data`, tự động lên level (có thể lên nhiều level cùng
    lúc nếu EXP dư nhiều — ví dụ câu được cá cực hiếm). Trả về
    (data đã cập nhật, có lên cấp hay không, số cấp đã lên)."""
    level = data.get("level", 1)
    exp = data.get("exp", 0) + exp_gain
    levels_gained = 0
    while exp >= exp_needed_for_level(level):
        exp -= exp_needed_for_level(level)
        level += 1
        levels_gained += 1
    data["level"] = level
    data["exp"] = exp
    return data, levels_gained > 0, levels_gained


def apply_energy_regen(data: dict) -> dict:
    """Hồi thể lực dần theo thời gian thực. Tính kiểu "lazy" ngay khi đọc
    dữ liệu (dựa vào energy_updated_at) thay vì chạy 1 vòng lặp nền quét
    toàn bộ user mỗi phút — vừa nhẹ vừa chính xác theo đúng thời gian thực
    tế đã trôi qua kể từ lần cuối user tương tác."""
    now = time.time()
    level = data.get("level", 1)
    max_e = max_energy_for_level(level)
    energy = data.get("energy", max_e)
    last = data.get("energy_updated_at", now)

    if energy >= max_e:
        data["energy"] = max_e
        data["energy_updated_at"] = now
        return data

    interval = ENERGY_REGEN_MINUTES * 60
    elapsed = now - last
    gained = int(elapsed // interval)
    if gained > 0:
        energy = min(max_e, energy + gained)
        last += gained * interval  # giữ lại phần dư thời gian chưa đủ 1 tick

    data["energy"] = energy
    data["energy_updated_at"] = last
    return data


def roll_fish(rod: Rod, map_key: Optional[str] = None) -> FishSpecies:
    """Chọn 1 con cá theo cấp mà lực kéo của cần hiện có thể tiếp cận.
    Cấp cao hơn có trọng số random thấp hơn (khó gặp hơn); trong 1 cấp,
    cá giá cao hơn cũng hiếm hơn.

    Nếu `map_key` được chỉ định: chỉ roll trong số cá thuộc khu vực đó.
    Nếu khu vực đó chưa có cá nào tương thích với lực kéo hiện tại, tự
    động rơi về roll không giới hạn khu vực để không bao giờ "câu hụt".
    """
    tiers = tiers_unlocked_for_pull(rod.pull)
    if not tiers:
        tiers = [t for t in TIERS if FISH_BY_TIER[t.key]][:1]

    def pool_for(tier_key: str) -> list[FishSpecies]:
        if map_key is None:
            return FISH_BY_TIER[tier_key]
        return [f for f in FISH_BY_TIER[tier_key] if f.map_key == map_key]

    if map_key is not None:
        tiers = [t for t in tiers if pool_for(t.key)]
        if not tiers:  # khu vực chưa có dữ liệu cá cho lực kéo này -> bỏ lọc map
            return roll_fish(rod, map_key=None)

    tier_weights = [1.0 / (i + 1) for i in range(len(tiers))]
    tier = random.choices(tiers, weights=tier_weights)[0]

    pool = pool_for(tier.key)
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
    level_info: Optional[dict] = None,
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
    if level_info:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"🔋 **Thể lực:** `{level_info['energy']}/{level_info['max_energy']}`"
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
    is_boss: bool = False,
    level_info: Optional[dict] = None,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(
        accent_colour=discord.Colour.dark_purple() if is_boss else discord.Colour.gold()
    )

    header = (
        f"{E.TOP3} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"🎣 **Cần:** {rod.emoji} `{rod.name}`"
    )
    if is_boss:
        header = f"👑🐉 **ĐÃ CÂU ĐƯỢC BOSS!** 👑🐉\n" + header
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
    if level_info:
        container.add_item(discord.ui.Separator())
        exp_line = f"✨ **+{level_info['exp_gained']} EXP**"
        if level_info.get("leveled_up"):
            exp_line += f"\n🎉 **LÊN CẤP {level_info['new_level']}!** Thể lực đã được hồi đầy."
        exp_line += f"\n🔋 **Thể lực:** `{level_info['energy']}/{level_info['max_energy']}`"
        container.add_item(discord.ui.TextDisplay(exp_line))
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
        is_boss: bool = False,
        energy: int = 0,
        max_energy: int = ENERGY_BASE,
        skills: Optional[list[Optional[Skill]]] = None,
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
        self.on_finish = on_finish  # async callback(success: bool | None, energy_used: int) -> dict
        self.is_boss = is_boss
        self.energy = energy            # thể lực còn lại tại thời điểm bắt đầu câu (snapshot cục bộ)
        self.max_energy = max_energy
        self.energy_spent = 0            # số thể lực đã tiêu trong ván này (số lần bấm Kéo hợp lệ)

        self.target, _ = compute_challenge(rod, fish)
        self.progress = 0.0
        self.tension_max = 100.0  # % — quy về 0-100 cho dễ hiển thị, tương ứng độ dài dây câu tối đa của cần
        self.tension = 0.0
        self.last_click = 0.0
        self.last_action_at = time.time()  # mốc để tính tension tự tăng khi đứng yên
        self.finished = False
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()  # chặn _on_pull và _idle_tick edit chồng lên nhau

        # -- Kỹ năng (skill) — tối đa SKILL_SLOTS ô, mỗi skill dùng 1 lần/ván ---
        self.skills: list[Optional[Skill]] = list(skills or [])
        self.skills_used: set[str] = set()
        self.tension_slow_until: float = 0.0   # timestamp, còn hiệu lực "slow_tension" tới lúc này
        self.tension_slow_factor: float = 1.0    # hệ số nhân độ căng dây khi đang có "slow_tension"
        self._cid_skills: dict[str, str] = {
            s.key: f"reel_skill_{s.key}_{uuid.uuid4().hex}" for s in self.skills if s
        }

        # QUAN TRỌNG: custom_id CỐ ĐỊNH cho nút "Kéo!", tạo 1 LẦN DUY NHẤT ở
        # đây (không tạo lại mỗi lần _render()). Discord bắt buộc mỗi nút phải
        # có custom_id, và nếu không tự đặt thì discord.py auto-sinh 1 id NGẪU
        # NHIÊN MỚI mỗi lần Button() được khởi tạo. Vì _render() bị gọi lại
        # liên tục (kể cả bởi _idle_tick chạy nền mỗi giây) và luôn dựng lại
        # Button từ đầu, custom_id sẽ đổi liên tục nếu không cố định — dẫn tới
        # đúng lỗi "Tương tác này thất bại": người dùng bấm nút với custom_id
        # của bản UI cũ (bot vừa edit đổi custom_id mới ngay trước đó do
        # idle_tick), Discord gửi interaction lên nhưng view hiện tại không
        # còn item nào khớp custom_id đó nữa nên không có callback nào được
        # gọi -> tương tác rơi vào hư không, Discord báo lỗi cho user.
        self._cid_pull = f"reel_pull_{uuid.uuid4().hex}"

        self._render()
        self._idle_tick.start()

    # -- tension tự tăng khi không bấm "Kéo!" ---------------------------
    # THAY ĐỔI: idle tick giờ chỉ CỘNG DỒN tension NGẦM (không edit UI mỗi
    # giây nữa). Trước đây mỗi tick đều gọi message.edit() để hiện thanh độ
    # căng dây tăng dần theo thời gian thực -> vừa dễ đụng rate limit edit
    # message của Discord, vừa khiến nút "Kéo!" bị đổi/redraw liên tục ngay
    # trước khi kịp xử lý cú bấm của người chơi (nút xử lý không kịp, UI
    # nhấp nháy). Giờ:
    #   - Mỗi tick chỉ update self.tension trong bộ nhớ, KHÔNG edit message.
    #   - UI chỉ được vẽ lại (render + edit) đúng lúc user bấm "Kéo!" — khi
    #     đó _on_pull sẽ tự cộng thêm phần tension đã tích lũy ngầm trong
    #     lúc đứng yên (xem _apply_idle_tension), nên số hiển thị vẫn luôn
    #     đúng và cập nhật ngay khi bấm, không "trễ nhịp".
    #   - Nếu tension ngầm vượt ngưỡng trước khi user kịp bấm gì -> đây là
    #     lúc DUY NHẤT idle tick edit message, để báo đứt dây (kết thúc ván).
    def _apply_idle_tension(self, now: float) -> None:
        """Cộng phần tension tích lũy từ lúc `last_action_at` tới `now` vào
        self.tension (không edit UI) — gọi trước khi render bất cứ lúc nào
        cần số liệu mới nhất (khi user bấm Kéo, khi dùng skill, khi idle
        tick kiểm tra đứt dây)."""
        idle_for = now - self.last_action_at
        if idle_for <= 0:
            return
        slow_mult = self.tension_slow_factor if now < self.tension_slow_until else 1.0
        self.tension += IDLE_TENSION_PER_SECOND * idle_for * slow_mult
        self.last_action_at = now

    @tasks.loop(seconds=IDLE_TICK_SECONDS)
    async def _idle_tick(self) -> None:
        # message chỉ được gán SAU khi followup.send() xong (sau __init__),
        # nên vài tick đầu tiên có thể chưa có -> bỏ qua, đợi tick sau.
        if self.finished or self.message is None:
            return
        if self._lock.locked():
            return  # đang có 1 lần bấm "Kéo!" xử lý dở, đợi tick sau tránh đụng dữ liệu

        async with self._lock:
            now = time.time()
            self._apply_idle_tension(now)

            if self.tension < self.tension_max:
                return  # vẫn an toàn, KHÔNG edit UI — chỉ âm thầm cộng dồn

            # Chỉ tới đây (đứt dây do đứng câu quá lâu không kéo) mới thực
            # sự cần edit message — đây là lần edit DUY NHẤT của idle tick
            # trong suốt vòng đời ván câu (khác hẳn bản cũ edit mỗi giây).
            self.finished = True
            self._idle_tick.stop()
            self.clear_items()
            self.stop()
            result = await self.on_finish(False, self.energy_spent)
            view, file = build_fail_view(
                self.member, self.rod, self.rank_label, self.rank_badge,
                reason="Bạn đứng câu quá lâu không kéo, dây căng hết cỡ rồi đứt phựt!",
                level_info=result,
            )
            try:
                await self.message.edit(view=view, attachments=[file])
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
        if self.is_boss:
            header = f"👑🐉 **BOSS XUẤT HIỆN: {self.fish.name}!** 👑🐉\n" + header
        if self.bait_name:
            header += f"\n✨ Mồi: {E.BAIT} **{self.bait_name}** - Còn `{self.bait_time_left}`"
        container.add_item(discord.ui.TextDisplay(header))
        container.add_item(discord.ui.Separator())

        progress_ratio = min(1.0, self.progress / self.target) if self.target else 0.0
        hp_ratio = 1.0 - progress_ratio
        hp_current = max(0, round(self.target - self.progress))
        hp_max = max(1, round(self.target))
        tension_ratio = min(1.0, self.tension / self.tension_max)
        energy_ratio = (self.energy / self.max_energy) if self.max_energy else 0.0
        now = time.time()
        slow_note = ""
        if now < self.tension_slow_until:
            slow_note = f" *(đang làm chậm, còn `{format_time_left(self.tension_slow_until - now)}`)*"
        container.add_item(discord.ui.TextDisplay(
            f"**🐟 Cá:** `{self.fish.name}`\n"
            f"**Có gì đó đang cắn câu!** Bấm **Kéo!** để kéo cá vào, "
            f"nhưng đừng kéo quá tay kẻo đứt dây.\n\n"
            f"❤️ Máu cá: `{make_bar(hp_ratio)}` {hp_current:,}/{hp_max:,}\n"
            f"Độ căng dây câu: `{make_bar(tension_ratio)}` {tension_ratio:.0%}{slow_note}\n"
            f"🔋 Thể lực: `{make_bar(energy_ratio)}` {self.energy}/{self.max_energy}"
        ))
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        btn = discord.ui.Button(
            label="🎣 Kéo!", style=discord.ButtonStyle.primary, custom_id=self._cid_pull,
        )
        btn.callback = self._on_pull
        row.add_item(btn)
        container.add_item(row)

        active_skills = [s for s in self.skills if s]
        if active_skills:
            skill_row = discord.ui.ActionRow()
            for skill in active_skills:
                used = skill.key in self.skills_used
                can_afford = self.energy >= skill.energy_cost
                skill_btn = discord.ui.Button(
                    label=f"{skill.emoji} {skill.name} ({skill.energy_cost}🔋)",
                    style=discord.ButtonStyle.secondary,
                    disabled=used or not can_afford,
                    custom_id=self._cid_skills[skill.key],
                )
                skill_btn.callback = self._skill_callback(skill)
                skill_row.add_item(skill_btn)
            container.add_item(skill_row)

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
        if self.energy <= 0:
            await interaction.response.send_message(
                "🔋 Bạn đã hết thể lực rồi, phải nghỉ tay cho thể lực hồi lại đã "
                "mới kéo tiếp được (tự hồi dần theo thời gian)!",
                ephemeral=True,
            )
            return
        self.last_click = now

        async with self._lock:
            if self.finished:  # có thể vừa bị idle_tick kết thúc trong lúc chờ lock
                await interaction.response.defer()
                return

            # Cộng nốt phần tension đã tích lũy NGẦM từ lần thao tác trước
            # tới giờ (idle tick không còn tự edit UI, chỉ cộng dồn số liệu
            # trong nền — xem _apply_idle_tension) rồi mới cộng thêm phần
            # tension của chính cú "Kéo!" này, để số hiển thị sau _render()
            # luôn khớp đúng thời điểm hiện tại, không bị "trễ nhịp".
            self._apply_idle_tension(now)

            dmg = self.rod.pull * random.uniform(0.9, 1.3) * (1 + self.luck_bonus * 0.5)
            self.progress += dmg

            slow_mult = self.tension_slow_factor if now < self.tension_slow_until else 1.0
            base_tension_gain = max(1.0, 100.0 / random.uniform(6.0, 11.0) * (1 - self.luck_bonus * 0.4))
            self.tension += base_tension_gain * slow_mult

            self.energy -= 1
            self.energy_spent += 1

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
            try:
                await interaction.response.edit_message(view=self)
            except discord.HTTPException:
                if self.message:
                    try:
                        await self.message.edit(view=self)
                    except discord.HTTPException:
                        pass

    def _skill_callback(self, skill: Skill):
        async def _cb(interaction: discord.Interaction) -> None:
            await self._on_skill(interaction, skill)
        return _cb

    async def _on_skill(self, interaction: discord.Interaction, skill: Skill) -> None:
        if self.finished:
            await interaction.response.defer()
            return
        if not await self._guard(interaction):
            return
        if skill.key in self.skills_used:
            await interaction.response.send_message(
                f"⚠️ Bạn đã dùng **{skill.name}** trong ván câu này rồi!", ephemeral=True,
            )
            return
        if self.energy < skill.energy_cost:
            await interaction.response.send_message(
                f"🔋 Không đủ thể lực để dùng **{skill.name}** (cần `{skill.energy_cost}`)!",
                ephemeral=True,
            )
            return

        async with self._lock:
            if self.finished:  # có thể vừa bị idle_tick kết thúc trong lúc chờ lock
                await interaction.response.defer()
                return

            now = time.time()
            # Cộng nốt tension tích lũy ngầm trước khi trừ/giảm tốc, để
            # skill "reduce_tension"/"slow_tension" tác động trên số liệu
            # đúng thời điểm hiện tại (không phải số liệu cũ từ lần render
            # trước).
            self._apply_idle_tension(now)
            self.energy -= skill.energy_cost
            self.energy_spent += skill.energy_cost
            self.skills_used.add(skill.key)

            if skill.effect == "reduce_tension":
                self.tension = max(0.0, self.tension - self.tension_max * skill.value)
            elif skill.effect == "slow_tension":
                self.tension_slow_until = now + skill.duration_s
                self.tension_slow_factor = 1.0 - skill.value

            # Idle tick không còn tự kiểm tra mỗi giây -> phải tự check ở
            # đây: nếu phần tension ngầm đã kịp vượt ngưỡng NGAY TRƯỚC LÚC
            # skill kịp giảm nó xuống (đứng lâu rồi mới bấm skill), ván câu
            # coi như đứt dây, dùng skill không kịp "cứu" nữa.
            if self.tension >= self.tension_max:
                self.finished = True
                self._idle_tick.stop()
                await self._finish(interaction, success=False)
                return

            self._render()
            try:
                await interaction.response.edit_message(view=self)
            except discord.HTTPException:
                if self.message:
                    try:
                        await self.message.edit(view=self)
                    except discord.HTTPException:
                        pass

    async def _finish(self, interaction: discord.Interaction, success: bool) -> None:
        self.clear_items()
        self.stop()
        # Gọi on_finish TRƯỚC khi build view kết quả, để lấy EXP/level/thể lực
        # mới nhất và hiển thị luôn trong CÙNG 1 lần edit (không gửi thêm tin nhắn).
        result = await self.on_finish(success, self.energy_spent)
        try:
            if success:
                view = build_success_view(
                    self.member, self.rod, self.rank_label, self.rank_badge, self.fish,
                    bait_name=self.bait_name, bait_luck=self.luck_bonus,
                    bait_time_left=self.bait_time_left, is_boss=self.is_boss,
                    level_info=result,
                )
                await interaction.response.edit_message(view=view, attachments=[])
            else:
                view, file = build_fail_view(
                    self.member, self.rod, self.rank_label, self.rank_badge,
                    level_info=result,
                )
                await interaction.response.edit_message(view=view, attachments=[file])
        except discord.HTTPException:
            pass

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
            await self.on_finish(None, self.energy_spent)


# ---------------------------------------------------------------------------
# Shop cần câu — Components V2, phân trang từng cây
#
# GHI CHÚ GỘP SHOP: logic render được tách thành `_build_container()` (nhận
# sẵn 1 discord.ui.Container rỗng và tự thêm nội dung/nút vào đó) để lớp vỏ
# UnifiedShopView (xem bên dưới, sau SkillShopView/mồi câu) có thể tái sử
# dụng NGUYÊN VẸN logic phân trang/mua/trang bị của từng shop con mà không
# copy-paste lại. RodShopView vẫn hoạt động độc lập y hệt trước (dùng lại
# khi cần), chỉ là _render() giờ chỉ là 1 lớp mỏng gọi _build_container().
# ---------------------------------------------------------------------------
class RodShopView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict, tab: str = "thuong_truc", index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.tab = tab      # "thuong_truc" | "gioi_han"
        self.index = index
        # custom_id cố định cho từng nút (xem giải thích chi tiết trong
        # ReelView.__init__) — tránh lỗi "tương tác thất bại" khi _render()
        # bị gọi lại (chuyển trang, đổi tab, mua/trang bị cần).
        self._cid_prev = f"rodshop_prev_{uuid.uuid4().hex}"
        self._cid_next = f"rodshop_next_{uuid.uuid4().hex}"
        self._cid_equip = f"rodshop_equip_{uuid.uuid4().hex}"
        self._cid_buy = f"rodshop_buy_{uuid.uuid4().hex}"
        self._cid_tab_tt = f"rodshop_tab_tt_{uuid.uuid4().hex}"
        self._cid_tab_gh = f"rodshop_tab_gh_{uuid.uuid4().hex}"
        self._render(data)

    @classmethod
    async def create(cls, user_id: int, tab: str = "thuong_truc", index: int = 0) -> "RodShopView":
        """Fetch dữ liệu Firebase (async, không block loop) rồi tạo view."""
        data = await aget_user_data(user_id)
        return cls(user_id, data, tab, index)

    @property
    def _rod_list(self) -> list[Rod]:
        return ROD_LIST if self.tab == "thuong_truc" else LIMITED_ROD_LIST

    def _render(self, data: dict) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        self._build_container(container, data, show_tab_row=True)
        self.add_item(container)

    def _build_container(self, container: discord.ui.Container, data: dict,
                          show_tab_row: bool = True) -> None:
        """Thêm toàn bộ nội dung shop cần câu vào `container` có sẵn.
        `show_tab_row=False` khi được UnifiedShopView nhúng vào (nó đã có
        1 tab-row lớn riêng ở tầng ngoài, không cần lặp lại tab con)."""
        rods = self._rod_list
        self.index = max(0, min(self.index, len(rods) - 1))
        rod = rods[self.index]
        owned = rod.key in data["unlocked_rods"]

        if show_tab_row:
            tab_row = discord.ui.ActionRow()
            tt_btn = discord.ui.Button(
                label="Cần Thường Trực",
                style=discord.ButtonStyle.primary if self.tab == "thuong_truc" else discord.ButtonStyle.secondary,
                custom_id=self._cid_tab_tt,
            )
            tt_btn.callback = self._switch_thuong_truc
            gh_btn = discord.ui.Button(
                label="Cần Câu Giới Hạn",
                style=discord.ButtonStyle.primary if self.tab == "gioi_han" else discord.ButtonStyle.secondary,
                custom_id=self._cid_tab_gh,
            )
            gh_btn.callback = self._switch_gioi_han
            tab_row.add_item(tt_btn)
            tab_row.add_item(gh_btn)
            container.add_item(tab_row)
            container.add_item(discord.ui.Separator())
        else:
            # Trong UnifiedShopView, cần vẫn cho chọn tab con (Thường Trực /
            # Giới Hạn) nhưng dùng custom_id riêng để không đụng nút của
            # RodShopView độc lập nếu cả 2 tồn tại song song.
            subtab_row = discord.ui.ActionRow()
            tt_btn = discord.ui.Button(
                label="Thường Trực",
                style=discord.ButtonStyle.primary if self.tab == "thuong_truc" else discord.ButtonStyle.secondary,
                custom_id=self._cid_tab_tt,
            )
            tt_btn.callback = self._switch_thuong_truc
            gh_btn = discord.ui.Button(
                label="Giới Hạn",
                style=discord.ButtonStyle.primary if self.tab == "gioi_han" else discord.ButtonStyle.secondary,
                custom_id=self._cid_tab_gh,
            )
            gh_btn.callback = self._switch_gioi_han
            subtab_row.add_item(tt_btn)
            subtab_row.add_item(gh_btn)
            container.add_item(subtab_row)

        container.add_item(discord.ui.TextDisplay(
            f"## {rod.emoji} {rod.name}  ({self.index + 1}/{len(rods)})"
        ))

        price_line = (
            f"{E.GOLD} Giá: `{fmt_gia_trieu(rod.price_vang)}` Vàng" if rod.price_vang is not None
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
            disabled=self.index == 0, custom_id=self._cid_prev,
        )
        prev_btn.callback = self._go_prev
        next_btn = discord.ui.Button(
            label="Sau ▶", style=discord.ButtonStyle.secondary,
            disabled=self.index == len(rods) - 1, custom_id=self._cid_next,
        )
        next_btn.callback = self._go_next
        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)
        container.add_item(nav_row)

        action_row = discord.ui.ActionRow()
        if owned:
            equip_btn = discord.ui.Button(
                label="Trang bị", style=discord.ButtonStyle.success, custom_id=self._cid_equip,
            )
            equip_btn.callback = self._equip
            action_row.add_item(equip_btn)
        elif rod.price_vang is not None:
            buy_btn = discord.ui.Button(
                label="Mở Khóa", style=discord.ButtonStyle.primary, custom_id=self._cid_buy,
            )
            buy_btn.callback = self._buy
            action_row.add_item(buy_btn)
        else:
            locked_btn = discord.ui.Button(
                label="Cần nhiệm vụ/sự kiện để mở khóa", style=discord.ButtonStyle.secondary,
                disabled=True,
            )
            action_row.add_item(locked_btn)
        container.add_item(action_row)

        self.add_item(container)

    # `_on_change` (mặc định None): khi RodShopView được UnifiedShopView
    # nhúng vào làm shop con, Unified sẽ gán hàm này để tự vẽ lại TOÀN BỘ
    # view cha (tab lớn + container con) thay vì để RodShopView tự
    # edit_original_response bằng chính nó (self) — vì lúc đó `self`
    # không phải là view đang thật sự hiển thị trên Discord nữa.
    _on_change = None  # type: Optional[callable]

    async def _refresh(self, interaction: discord.Interaction, data: dict) -> None:
        if self._on_change is not None:
            # Unified view sẽ tự dựng lại toàn bộ container (gọi
            # _build_container với show_tab_row=False) — không cần
            # self._render() ở đây vì self không phải view đang hiển thị.
            await self._on_change(interaction, data)
        else:
            self._render(data)
            await interaction.edit_original_response(view=self)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Đây không phải shop của bạn!", ephemeral=True
            )
            return False
        return True

    async def _switch_thuong_truc(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.tab = "thuong_truc"
        self.index = 0
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _switch_gioi_han(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.tab = "gioi_han"
        self.index = 0
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.index = max(0, self.index - 1)
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.index = min(len(self._rod_list) - 1, self.index + 1)
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        rod = self._rod_list[self.index]
        data = await aget_user_data(self.user_id)
        if rod.key in data["unlocked_rods"]:
            await interaction.followup.send("Bạn đã sở hữu cần này rồi!", ephemeral=True)
            return
        if data["vang"] < (rod.price_vang or 0):
            await interaction.followup.send(
                f"Bạn không đủ Vàng! Cần `{fmt_gia_trieu(rod.price_vang)}` Vàng.", ephemeral=True
            )
            return
        data["vang"] -= rod.price_vang
        data["unlocked_rods"].append(rod.key)
        await asave_user_data(self.user_id, data)
        await self._refresh(interaction, data)

    async def _equip(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        rod = self._rod_list[self.index]
        data = await aget_user_data(self.user_id)
        data["rod"] = rod.key
        await asave_user_data(self.user_id, data)
        await interaction.followup.send(
            f"Đã trang bị {rod.emoji} `{rod.name}`!", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Shop kỹ năng câu cá — Components V2, phân trang từng skill. Mỗi người có
# SKILL_SLOTS (3) ô trang bị; bấm vào 1 ô để trang bị/gỡ skill đang xem
# khỏi ô đó (skill đã ở ô khác sẽ tự được gỡ ra trước khi gán ô mới).
# ---------------------------------------------------------------------------
class SkillShopView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict, index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.index = index
        self._cid_prev = f"skillshop_prev_{uuid.uuid4().hex}"
        self._cid_next = f"skillshop_next_{uuid.uuid4().hex}"
        self._cid_buy = f"skillshop_buy_{uuid.uuid4().hex}"
        self._cid_slots = [f"skillshop_slot{i}_{uuid.uuid4().hex}" for i in range(SKILL_SLOTS)]
        self._render(data)

    @classmethod
    async def create(cls, user_id: int, index: int = 0) -> "SkillShopView":
        data = await aget_user_data(user_id)
        return cls(user_id, data, index)

    def _render(self, data: dict) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.teal())
        self._build_container(container, data)
        self.add_item(container)

    def _build_container(self, container: discord.ui.Container, data: dict) -> None:
        """Thêm toàn bộ nội dung shop kỹ năng vào `container` có sẵn — dùng
        chung bởi SkillShopView độc lập và bởi UnifiedShopView khi nhúng."""
        skill = SKILL_SHOP[self.index]
        unlocked = set(data.get("unlocked_skills", []))
        owned = skill.key in unlocked
        equipped_keys = (list(data.get("equipped_skills", [None] * SKILL_SLOTS))
                         + [None] * SKILL_SLOTS)[:SKILL_SLOTS]

        container.add_item(discord.ui.TextDisplay(
            f"## {skill.emoji} {skill.name}  ({self.index + 1}/{len(SKILL_SHOP)})"
        ))

        if skill.effect == "reduce_tension":
            effect_line = f"Trừ ngay `{skill.value:.0%}` độ căng dây khi dùng."
        else:
            effect_line = f"Giảm `{skill.value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s`."

        stats = (
            f"{skill.description}\n"
            f"**Hiệu ứng:** {effect_line}\n"
            f"**Thể lực tiêu hao:** `{skill.energy_cost}` mỗi lần dùng (1 lần/ván câu)\n"
            f"{E.GOLD} Giá: `{fmt_gia_trieu(skill.price_vang)}` Vàng"
        )
        container.add_item(discord.ui.TextDisplay(stats))
        container.add_item(discord.ui.Separator())

        nav_row = discord.ui.ActionRow()
        prev_btn = discord.ui.Button(
            label="◀ Trước", style=discord.ButtonStyle.secondary,
            disabled=self.index == 0, custom_id=self._cid_prev,
        )
        prev_btn.callback = self._go_prev
        next_btn = discord.ui.Button(
            label="Sau ▶", style=discord.ButtonStyle.secondary,
            disabled=self.index == len(SKILL_SHOP) - 1, custom_id=self._cid_next,
        )
        next_btn.callback = self._go_next
        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)
        container.add_item(nav_row)

        action_row = discord.ui.ActionRow()
        if not owned:
            buy_btn = discord.ui.Button(
                label=f"Mở Khóa ({fmt_gia_trieu(skill.price_vang)})",
                style=discord.ButtonStyle.primary,
                disabled=data["vang"] < skill.price_vang,
                custom_id=self._cid_buy,
            )
            buy_btn.callback = self._buy
            action_row.add_item(buy_btn)
        else:
            for i in range(SKILL_SLOTS):
                in_slot = equipped_keys[i] == skill.key
                slot_btn = discord.ui.Button(
                    label=f"{'✅ ' if in_slot else ''}Ô {i + 1}",
                    style=discord.ButtonStyle.success if in_slot else discord.ButtonStyle.secondary,
                    custom_id=self._cid_slots[i],
                )
                slot_btn.callback = self._make_slot_cb(i)
                action_row.add_item(slot_btn)
        container.add_item(action_row)

        if owned:
            equipped_line = " · ".join(
                f"Ô{i + 1}: {SKILLS[k].emoji} {SKILLS[k].name}" if k in SKILLS else f"Ô{i + 1}: —"
                for i, k in enumerate(equipped_keys)
            )
            container.add_item(discord.ui.TextDisplay(
                f"_Bấm 1 ô để trang bị/gỡ kỹ năng này khỏi ô đó._\n**Đang trang bị:** {equipped_line}"
            ))

    # Xem giải thích _on_change ở RodShopView — cùng cơ chế cho phép
    # UnifiedShopView "mượn" logic của SkillShopView.
    _on_change = None  # type: Optional[callable]

    async def _refresh(self, interaction: discord.Interaction, data: dict) -> None:
        if self._on_change is not None:
            await self._on_change(interaction, data)
        else:
            self._render(data)
            await interaction.edit_original_response(view=self)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Đây không phải shop kỹ năng của bạn!", ephemeral=True
            )
            return False
        return True

    async def _go_prev(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.index = max(0, self.index - 1)
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _go_next(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        self.index = min(len(SKILL_SHOP) - 1, self.index + 1)
        data = await aget_user_data(self.user_id)
        await self._refresh(interaction, data)

    async def _buy(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        skill = SKILL_SHOP[self.index]
        data = await aget_user_data(self.user_id)
        unlocked = set(data.get("unlocked_skills", []))
        if skill.key in unlocked:
            await interaction.followup.send("Bạn đã sở hữu kỹ năng này rồi!", ephemeral=True)
            return
        if data["vang"] < skill.price_vang:
            await interaction.followup.send(
                f"Bạn không đủ Vàng! Cần `{fmt_gia_trieu(skill.price_vang)}` Vàng.", ephemeral=True
            )
            return
        data["vang"] -= skill.price_vang
        unlocked.add(skill.key)
        data["unlocked_skills"] = list(unlocked)
        await asave_user_data(self.user_id, data)
        await self._refresh(interaction, data)

    def _make_slot_cb(self, slot_index: int):
        async def _cb(interaction: discord.Interaction) -> None:
            if not await self._guard(interaction):
                return
            await interaction.response.defer()
            skill = SKILL_SHOP[self.index]
            data = await aget_user_data(self.user_id)
            equipped = (list(data.get("equipped_skills", [None] * SKILL_SLOTS))
                        + [None] * SKILL_SLOTS)[:SKILL_SLOTS]
            if equipped[slot_index] == skill.key:
                equipped[slot_index] = None  # bấm lại ô đang chứa skill này -> gỡ ra
            else:
                # gỡ skill này khỏi ô cũ (nếu có) trước khi gán vào ô mới
                equipped = [None if k == skill.key else k for k in equipped]
                equipped[slot_index] = skill.key
            data["equipped_skills"] = equipped
            await asave_user_data(self.user_id, data)
            await self._refresh(interaction, data)
        return _cb


# ---------------------------------------------------------------------------
# Shop mồi câu — chỉ 3 loại (không cần phân trang từng cây như cần/skill),
# hiện đủ 3 mồi cùng lúc kèm nút "Mua" riêng cho mỗi loại. Trước đây (bản cũ)
# mồi câu chỉ mua được qua lệnh /mua_mồi (dropdown Choice, không có UI xem
# trước) — giờ có thêm view này để nhúng vào tab "Mồi Câu" của
# UnifiedShopView; lệnh /mua_mồi vẫn giữ nguyên để không phá API cũ.
# ---------------------------------------------------------------------------
class BaitShopView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict):
        super().__init__(timeout=120)
        self.user_id = user_id
        self._cid_buy = [f"baitshop_buy{i}_{uuid.uuid4().hex}" for i in range(len(BAIT_SHOP))]
        self._render(data)

    @classmethod
    async def create(cls, user_id: int) -> "BaitShopView":
        data = await aget_user_data(user_id)
        return cls(user_id, data)

    def _render(self, data: dict) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.gold())
        self._build_container(container, data)
        self.add_item(container)

    def _build_container(self, container: discord.ui.Container, data: dict) -> None:
        """Thêm toàn bộ nội dung shop mồi câu vào `container` có sẵn — dùng
        chung bởi BaitShopView độc lập và bởi UnifiedShopView khi nhúng."""
        container.add_item(discord.ui.TextDisplay(
            f"## {E.BAIT} Mồi Câu\n"
            "Dùng Vàng mua mồi để tăng % may mắn (giảm độ căng dây tăng thêm "
            "khi kéo, tăng sát thương kéo) trong 1 khoảng thời gian."
        ))
        bait_data = data.get("bait") or {}
        if bait_data.get("expires_at", 0) > time.time():
            container.add_item(discord.ui.TextDisplay(
                f"✨ Đang dùng: {E.BAIT} **{bait_data.get('name', '?')}** "
                f"(+{bait_data.get('luck', 0):.0%} may mắn) — "
                f"còn `{format_time_left(bait_data['expires_at'] - time.time())}`"
            ))
        container.add_item(discord.ui.Separator())

        for i, bait in enumerate(BAIT_SHOP):
            row_text = (
                f"**{bait.name}** — +{bait.luck:.0%} may mắn, "
                f"`{bait.duration_s // 60}` phút\n"
                f"{E.GOLD} Giá: `{fmt_vang(bait.price_vang)}` Vàng"
            )
            container.add_item(discord.ui.TextDisplay(row_text))
            buy_row = discord.ui.ActionRow()
            buy_btn = discord.ui.Button(
                label=f"Mua {bait.name}",
                style=discord.ButtonStyle.primary,
                disabled=data["vang"] < bait.price_vang,
                custom_id=self._cid_buy[i],
            )
            buy_btn.callback = self._make_buy_cb(i)
            buy_row.add_item(buy_btn)
            container.add_item(buy_row)
            if i < len(BAIT_SHOP) - 1:
                container.add_item(discord.ui.Separator())

    # Xem giải thích _on_change ở RodShopView.
    _on_change = None  # type: Optional[callable]

    async def _refresh(self, interaction: discord.Interaction, data: dict) -> None:
        if self._on_change is not None:
            await self._on_change(interaction, data)
        else:
            self._render(data)
            await interaction.edit_original_response(view=self)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Đây không phải shop mồi câu của bạn!", ephemeral=True
            )
            return False
        return True

    def _make_buy_cb(self, bait_index: int):
        async def _cb(interaction: discord.Interaction) -> None:
            if not await self._guard(interaction):
                return
            await interaction.response.defer()
            bait = BAIT_SHOP[bait_index]
            data = await aget_user_data(self.user_id)
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
            await asave_user_data(self.user_id, data)
            await self._refresh(interaction, data)
        return _cb


# ---------------------------------------------------------------------------
# Shop gộp — "/đồ_câu_Lão_Bát": 1 view duy nhất với tab lớn trên cùng
# [Cần Câu] [Kỹ Năng] [Mồi Câu]. Mỗi tab NHÚNG lại nguyên logic phân trang/
# mua/trang bị của shop con tương ứng (RodShopView/SkillShopView/
# BaitShopView) thông qua _build_container() + hook _on_change — không
# copy-paste lại code, chỉ khác phần khung tab lớn bên ngoài.
# ---------------------------------------------------------------------------
class UnifiedShopView(discord.ui.LayoutView):
    TABS = ("can_cau", "ky_nang", "moi_cau")
    TAB_LABELS = {"can_cau": "🎣 Cần Câu", "ky_nang": "🧩 Kỹ Năng", "moi_cau": f"{E.BAIT} Mồi Câu"}

    def __init__(self, user_id: int, data: dict, tab: str = "can_cau"):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.tab = tab
        self._cid_tabs = {t: f"unishop_tab_{t}_{uuid.uuid4().hex}" for t in self.TABS}

        # Sub-shop con giữ NGUYÊN state riêng (index/tab con...) qua các lần
        # chuyển tab lớn trong CÙNG 1 phiên UnifiedShopView, để user không bị
        # "reset về trang đầu" mỗi lần bấm qua lại giữa các tab.
        self.rod_shop = RodShopView(user_id, data)
        self.skill_shop = SkillShopView(user_id, data)
        self.bait_shop = BaitShopView(user_id, data)
        for sub in (self.rod_shop, self.skill_shop, self.bait_shop):
            sub._on_change = self._make_sub_on_change()

        self._render(data)

    @classmethod
    async def create(cls, user_id: int, tab: str = "can_cau") -> "UnifiedShopView":
        data = await aget_user_data(user_id)
        return cls(user_id, data, tab)

    def _make_sub_on_change(self):
        async def _on_change(interaction: discord.Interaction, data: dict) -> None:
            self._render(data)
            # Banner ảnh (attachment://...) đã có sẵn trên message gốc từ lúc
            # gửi lần đầu — Discord tự giữ lại attachment cũ nếu edit_message
            # không truyền `attachments` mới, nên không cần gửi lại file ở
            # mỗi lần đổi trang/mua đồ, chỉ cần gửi lại view.
            await interaction.edit_original_response(view=self)
        return _on_change

    @staticmethod
    def banner_file() -> discord.File:
        """Tạo 1 discord.File MỚI cho banner shop — Discord yêu cầu 1 File
        object riêng cho mỗi lần gửi/edit có đính kèm, không tái dùng được
        object đã gửi trước đó."""
        return discord.File(SHOP_BANNER_IMAGE, filename="do_cau_lao_bat.webp")

    def _render(self, data: dict) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.dark_gold())

        container.add_item(discord.ui.TextDisplay("# 🏮 Đồ Câu Lão Bát"))
        container.add_item(discord.ui.MediaGallery(
            discord.MediaGalleryItem("attachment://do_cau_lao_bat.webp")
        ))
        tab_row = discord.ui.ActionRow()
        for t in self.TABS:
            btn = discord.ui.Button(
                label=self.TAB_LABELS[t],
                style=discord.ButtonStyle.primary if self.tab == t else discord.ButtonStyle.secondary,
                custom_id=self._cid_tabs[t],
            )
            btn.callback = self._make_switch_tab_cb(t)
            tab_row.add_item(btn)
        container.add_item(tab_row)
        container.add_item(discord.ui.Separator())

        if self.tab == "can_cau":
            self.rod_shop._build_container(container, data, show_tab_row=False)
        elif self.tab == "ky_nang":
            self.skill_shop._build_container(container, data)
        else:
            self.bait_shop._build_container(container, data)

        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Đây không phải Đồ Câu Lão Bát của bạn!", ephemeral=True
            )
            return False
        return True

    def _make_switch_tab_cb(self, tab: str):
        async def _cb(interaction: discord.Interaction) -> None:
            if not await self._guard(interaction):
                return
            await interaction.response.defer()
            self.tab = tab
            data = await aget_user_data(self.user_id)
            self._render(data)
            await interaction.edit_original_response(view=self)
        return _cb


# ---------------------------------------------------------------------------
# Kho cá + bán cá — Components V2, phân trang theo cấp (tier)
# ---------------------------------------------------------------------------
class SellView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict, tier_index: int = 0):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.tier_index = tier_index
        # custom_id cố định cho từng control (xem giải thích trong ReelView.__init__).
        self._cid_prev = f"sell_prev_{uuid.uuid4().hex}"
        self._cid_next = f"sell_next_{uuid.uuid4().hex}"
        self._cid_sell_tier = f"sell_tier_{uuid.uuid4().hex}"
        self._cid_sell_all = f"sell_all_{uuid.uuid4().hex}"
        self._cid_select = f"sell_select_{uuid.uuid4().hex}"
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
                custom_id=self._cid_select,
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
                                       disabled=self.tier_index == 0, custom_id=self._cid_prev)
        prev_btn.callback = self._go_prev
        next_btn = discord.ui.Button(label="Sau ▶", style=discord.ButtonStyle.secondary,
                                       disabled=self.tier_index == len(TIERS) - 1,
                                       custom_id=self._cid_next)
        next_btn.callback = self._go_next
        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)
        container.add_item(nav_row)

        action_row = discord.ui.ActionRow()
        sell_tier_btn = discord.ui.Button(
            label=f"💰 Bán Nhanh (cấp này: {fmt_vang(tier_total)})",
            style=discord.ButtonStyle.success, disabled=tier_total == 0,
            custom_id=self._cid_sell_tier,
        )
        sell_tier_btn.callback = self._sell_tier
        sell_all_btn = discord.ui.Button(
            label=f"💎 Bán Nhanh (Tất Cả: {fmt_vang(grand_total)})",
            style=discord.ButtonStyle.danger, disabled=grand_total == 0,
            custom_id=self._cid_sell_all,
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
# Chọn khu vực câu (map) — Select đơn, chỉ hiện các map người chơi đã đủ
# cấp độ mở khóa (unlock_level). Lưu lựa chọn vào data["current_map"].
# ---------------------------------------------------------------------------
class MapSelectView(discord.ui.LayoutView):
    def __init__(self, user_id: int, data: dict):
        super().__init__(timeout=120)
        self.user_id = user_id
        self._cid_select = f"map_select_{uuid.uuid4().hex}"
        self._cid_clear = f"map_clear_{uuid.uuid4().hex}"
        self._render(data)

    @classmethod
    async def create(cls, user_id: int) -> "MapSelectView":
        data = await aget_user_data(user_id)
        return cls(user_id, data)

    def _render(self, data: dict) -> None:
        self.clear_items()
        level = data.get("level", 1)
        current = data.get("current_map")
        unlocked = [m for m in MAPS if level >= m.unlock_level]
        locked = [m for m in MAPS if level < m.unlock_level]

        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay("## 🗺️ Chọn Khu Vực Câu"))
        container.add_item(discord.ui.Separator())

        current_label = "🌐 Tất cả khu vực (mặc định)"
        if current and current in MAP_BY_KEY:
            m = MAP_BY_KEY[current]
            current_label = f"{m.emoji} {m.label}"
        lines = [f"**Đang chọn:** {current_label}"]
        if locked:
            lock_lines = "\n".join(
                f"🔒 {m.emoji} {m.label} — mở ở Lv.{m.unlock_level}" for m in locked
            )
            lines.append(f"\n**Chưa mở khóa:**\n{lock_lines}")
        container.add_item(discord.ui.TextDisplay("\n".join(lines)))
        container.add_item(discord.ui.Separator())

        options = [
            discord.SelectOption(
                label="Tất cả khu vực", description="Câu ngẫu nhiên, không giới hạn khu vực",
                emoji="🌐", value="__all__", default=current is None,
            )
        ]
        for m in unlocked:
            options.append(discord.SelectOption(
                label=m.label, emoji=m.emoji, value=m.key,
                description=f"{len(fish_in_map(m.key))} loài cá" if fish_in_map(m.key) else "Chưa có dữ liệu cá",
                default=(current == m.key),
            ))

        select = discord.ui.Select(
            placeholder="Chọn khu vực muốn câu...",
            custom_id=self._cid_select,
            options=options[:25],
        )
        select.callback = self._on_select
        row = discord.ui.ActionRow()
        row.add_item(select)
        container.add_item(row)

        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Đây không phải lựa chọn của bạn!", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        chosen = interaction.data["values"][0]
        data = await aget_user_data(self.user_id)
        data["current_map"] = None if chosen == "__all__" else chosen
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
        data = apply_energy_regen(data)

        now = time.time()
        remaining = CAST_COOLDOWN_SECONDS - (now - data["last_cast"])
        if remaining > 0 and interaction.user.id not in OWNER_IDS:
            await interaction.followup.send(
                f"⏳ Cần câu đang hồi chiêu, chờ thêm `{remaining:.1f}s` nữa nhé!",
                ephemeral=True,
            )
            return

        if data.get("energy", 0) <= 0 and interaction.user.id not in OWNER_IDS:
            await interaction.followup.send(
                f"🔋 Bạn đã hết thể lực rồi! Thể lực tự hồi theo thời gian "
                f"(mỗi `{ENERGY_REGEN_MINUTES}` phút +1), quay lại sau nhé!",
                ephemeral=True,
            )
            await asave_user_data(interaction.user.id, data)
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

        fish = roll_fish(rod, map_key=data.get("current_map"))
        is_boss = fish.key in BOSS_FISH_KEYS
        rank_label, rank_badge = rank_for_score(data["score"])
        level = data.get("level", 1)
        energy = data.get("energy", 0)
        max_energy = max_energy_for_level(level)
        skills = equipped_skill_objects(data)

        async def on_finish(success: Optional[bool], energy_used: int) -> dict:
            """Chạy khi ván câu kết thúc (bắt được / đứt dây / hết giờ).
            Trừ thể lực đã tiêu, cộng EXP + xử lý lên cấp nếu câu thành công,
            rồi trả về thông tin để hiển thị trong khung kết quả."""
            fresh = await aget_user_data(interaction.user.id)
            fresh = apply_energy_regen(fresh)  # hồi thêm nếu có thời gian trôi qua trong lúc câu
            fresh["energy"] = max(0, fresh.get("energy", 0) - energy_used)

            result = {
                "exp_gained": 0,
                "leveled_up": False,
                "new_level": fresh.get("level", 1),
                "energy": fresh["energy"],
                "max_energy": max_energy_for_level(fresh.get("level", 1)),
            }

            if success is True:
                inv = fresh.get("inventory", {})
                inv[fish.key] = inv.get(fish.key, 0) + 1
                fresh["inventory"] = inv
                fresh["score"] = fresh.get("score", 0) + 10

                exp_gain = exp_for_fish(fish)
                fresh, leveled_up, _levels_gained = add_exp(fresh, exp_gain)
                if leveled_up:
                    # Thưởng hồi đầy thể lực khi lên cấp.
                    fresh["energy"] = max_energy_for_level(fresh["level"])
                    fresh["energy_updated_at"] = time.time()

                result["exp_gained"] = exp_gain
                result["leveled_up"] = leveled_up
                result["new_level"] = fresh["level"]
                result["energy"] = fresh["energy"]
                result["max_energy"] = max_energy_for_level(fresh["level"])
            elif success is False:
                fresh["score"] = max(0, fresh.get("score", 0) - 5)
            # success is None (timeout) -> không cộng/trừ điểm/EXP, cá tự bơi đi

            await asave_user_data(interaction.user.id, fresh)
            return result

        view = ReelView(
            interaction.user, rod, fish, luck_bonus, rank_label, rank_badge,
            bait_name, bait_time_left, on_finish,
            is_boss=is_boss, energy=energy, max_energy=max_energy, skills=skills,
        )
        view.message = await interaction.followup.send(view=view, wait=True)

    @app_commands.command(name="chọn_map", description="Chọn khu vực câu cá")
    async def chon_map(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await MapSelectView.create(user_id=interaction.user.id)
        await interaction.followup.send(view=view)

    @app_commands.command(
        name="đồ_câu_lão_bát",
        description="Đồ Câu Lão Bát — mua cần câu, kỹ năng và mồi câu (1 shop gộp)",
    )
    async def do_cau_lao_bat(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await UnifiedShopView.create(user_id=interaction.user.id)
        # Gửi kèm banner ảnh cửa hàng lần đầu — attachment này sẽ tự được
        # Discord giữ lại ở các lần edit_original_response() sau (đổi tab,
        # mua đồ...) nên không cần gửi lại file mỗi lần.
        await interaction.followup.send(view=view, file=UnifiedShopView.banner_file())

    @app_commands.command(name="bán", description="Xem kho cá và bán cá lấy Vàng")
    async def ban(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await SellView.create(user_id=interaction.user.id)
        await interaction.followup.send(view=view)

    @app_commands.command(name="ví", description="Xem số Vàng hiện có")
    async def vi(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        data = await aget_user_data(interaction.user.id)
        data = apply_energy_regen(data)
        await asave_user_data(interaction.user.id, data)

        rank_label, rank_badge = rank_for_score(data["score"])
        rod = RODS.get(data["rod"], RODS[DEFAULT_ROD_KEY])

        level = data.get("level", 1)
        exp = data.get("exp", 0)
        exp_needed = exp_needed_for_level(level)
        energy = data.get("energy", 0)
        max_energy = max_energy_for_level(level)

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay(
            f"## 👛 Ví của {interaction.user.display_name}\n"
            f"{rank_badge} `[{rank_label}]` — Điểm: `{data['score']}`"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"{E.GOLD} **Vàng:** `{fmt_vang(data['vang'])}`\n"
            f"🎣 **Cần đang dùng:** {rod.emoji} `{rod.name}`"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"📈 **Cấp:** `{level}` — EXP: `{exp}/{exp_needed}`\n"
            f"`{make_bar(exp / exp_needed if exp_needed else 0)}`\n"
            f"🔋 **Thể lực:** `{energy}/{max_energy}`\n"
            f"`{make_bar(energy / max_energy if max_energy else 0)}`"
        ))
        container.add_item(discord.ui.Separator())
        equipped = equipped_skill_objects(data)
        skill_lines = " · ".join(
            f"Ô{i + 1}: {s.emoji} {s.name}" if s else f"Ô{i + 1}: —"
            for i, s in enumerate(equipped)
        )
        container.add_item(discord.ui.TextDisplay(f"🧩 **Kỹ năng đang trang bị:** {skill_lines}"))
        view.add_item(container)
        await interaction.followup.send(view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CauCaVanCan(bot))
