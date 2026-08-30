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
- KỸ NĂNG (skill_data.py): mỗi người mặc định có 3 ô trang bị, mua/mở khóa
  qua /shop_kỹ_năng. Có thể MUA THÊM ô trang bị bằng Vàng, giá tăng dần
  50 triệu mỗi ô (skill_data.next_slot_price). Mỗi skill trang bị chỉ dùng
  được 1 lần/ván câu, tốn thể lực, hiệu ứng là trừ ngay % độ căng dây hoặc
  làm chậm tốc độ tăng độ căng dây trong vài giây — không có skill gây
  thêm sát thương (trừ vài skill damage_fish_hp/slow_then_damage riêng).

THỜI TIẾT (weather_data.py)
---------------------------
Bot tự random 1 thời tiết mới MỖI GIỜ (weather_loop trong CauCaVanCan),
lưu vào Firebase (fishing/weather/current) và thông báo trong đúng kênh
WEATHER_CHANNEL_ID. Lệnh /thời_tiết chỉ dùng được trong kênh đó. Thời tiết
hiện tại được áp dụng (snapshot) vào mỗi ván /câu_cá lúc thả cần: cộng
thêm luck_bonus, nhân thêm tốc độ tăng độ căng dây, và tăng/giảm tỷ lệ
gặp cá boss/hiếm. 5 loại: Mưa, Giông, Đêm, Hạn Hán, Bảy Sắc Cầu Vồng
(cực hiếm, buff mạnh nhất).
"""

from __future__ import annotations

import asyncio
import random
import string
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from firebase_db import (
    DEFAULT_CODE_EXPIRY_MAX_DAYS, DEFAULT_CODE_EXPIRY_MIN_DAYS, OWNER_IDS,
    acreate_code, aget_all_users, aget_code, aget_current_weather,
    aget_user_data, apvp_queue_join_or_match, apvp_queue_leave,
    aredeem_code, aset_current_weather, asave_user_data,
)
from fish_data import (
    ALL_FISH, BOSS_FISH_KEYS, FISH_BY_KEY, FISH_BY_TIER, FishTier, JUNK_ITEMS,
    MAP6_KEY, MAP7_ITEM_KEY, MAP7_ITEM_LABEL, MAP_BY_KEY, MAPS, TIERS,
    FishSpecies, fish_in_map, is_junk_fish, map_is_unlocked, roll_junk,
    tiers_unlocked_for_pull,
)
from rod_data import DEFAULT_ROD_KEY, LIMITED_ROD_LIST, RODS, ROD_LIST, Rod
from skill_data import (
    SKILL_SHOP, SKILL_SLOTS, SKILLS, Skill, equipped_skill_objects,
    slot_count, next_slot_price,
)
from weather_data import WEATHER_BY_KEY, WEATHERS, Weather, roll_weather

ASSET_DIR = Path(__file__).parent / "assets"
ROD_BREAK_IMAGE = ASSET_DIR / "can_gay.png"
SHOP_BANNER_IMAGE = ASSET_DIR / "do_cau_lao_bat.webp"

# Kênh DUY NHẤT được phép dùng lệnh thời tiết + nơi bot tự động gửi thông
# báo thời tiết mới mỗi giờ.
WEATHER_CHANNEL_ID = 1543098261705855096


# ---------------------------------------------------------------------------
# Emoji dùng trong khung kết quả (icon mặc định — không phụ thuộc server nào)
# ---------------------------------------------------------------------------
class E:
    TOP1 = "🥇"
    TOP3 = "<:cup:1543460863170707466>"
    GOLD = "<:xu:1543462839430160384>"
    # Icon custom "túi mồi câu" — dùng ở mọi nơi hiển thị mồi câu (thay 🪱).
    BAIT = "<:tuimoicancau:1543465353823125504>"
    FISH_NUMBER = "<:ca:1543468587144974336>"
    # Emoji custom "Năng lượng" — thay cho biểu tượng pin 🔋 mặc định ở mọi
    # nơi hiển thị thanh thể lực/năng lượng cho người chơi.
    ENERGY = "<:nangluong:1543459912615469156>"
    JUNK = "<:tuirac:1543465482030547126>"
    # Icon custom mới — cân nặng / cần câu / máu / vận may.
    WEIGHT = "<:caican:1543468233095389254>"
    ROD = "<:cancau:1543465309229285377>"
    HEALTH = "<:mau:1543460091993526313>"
    LUCKY = "<:lucky:1543464401066131506>"
    CLOCK = "<a:clock:1543479349326512128>"


# ---------------------------------------------------------------------------
# Cấp bậc (rank) theo Điểm (score) — 12 bậc, thứ tự THẤP -> CAO đúng theo
# yêu cầu: Gà Mờ, Tân Thủ, Cao Thủ, Bậc Thầy, Tông Sư, Bán Tiên, Tiên Nhân,
# Bán Thánh, Thánh Nhân, Bán Thần, Thần Tiên, Huyền Thoại.
# GHI CHÚ: ngưỡng điểm (min_score) chưa có số liệu gốc cụ thể từ game —
# tự đặt tăng dần hợp lý (mỗi cá câu được +10 điểm, thua đứt dây -5 điểm)
# để 12 bậc dàn trải đều theo quá trình chơi dài hạn; chỉnh lại nếu có số
# liệu chính xác từ game gốc.
# ---------------------------------------------------------------------------
RANK_TIERS = [
    (0, "Gà Mờ Câu Cá", "🐣"),
    (300, "Tân Thủ Câu Cá", "🎣"),
    (800, "Cao Thủ Câu Cá", "🥈"),
    (1_800, "Bậc Thầy Câu Cá", "🥇"),
    (3_500, "Tông Sư Câu Cá", "🏵️"),
    (6_500, "Bán Tiên Câu Cá", "🌗"),
    (11_000, "Tiên Nhân Câu Cá", "🧙"),
    (18_000, "Bán Thánh Câu Cá", "⭐"),
    (28_000, "Thánh Nhân Câu Cá", "🌟"),
    (42_000, "Bán Thần Câu Cá", "🔥"),
    (62_000, "Thần Tiên Câu Cá", "<:vuongmien:1543461013045645323>"),
    (90_000, "Huyền Thoại Câu Cá", "🐉"),
]


def rank_for_score(score: int) -> tuple[str, str]:
    label, badge = RANK_TIERS[0][1], RANK_TIERS[0][2]
    for min_score, lbl, bdg in RANK_TIERS:
        if score >= min_score:
            label, badge = lbl, bdg
    return label, badge


# ---------------------------------------------------------------------------
# PvP (/pvp) — Điểm Đấu Bậc (ĐĐB, "dtb" trong firebase_db._default_data).
# Thang bậc RIÊNG với RANK_TIERS ở trên (RANK_TIERS tính theo "score" câu
# cá, PVP_RANK_TIERS tính theo "dtb" — 2 hệ thống độc lập). Khởi điểm mọi
# người đều có 1000 ĐĐB (xem _default_data), thắng/thua cộng/trừ quanh mốc
# đó -> 7 bậc dàn đều 2 phía trên/dưới mốc khởi điểm.
# ---------------------------------------------------------------------------
PVP_RANK_TIERS = [
    (0, "Tân Binh", "🔰"),
    (900, "Chiến Binh", "⚔️"),
    (1_100, "Tinh Anh", "🛡️"),
    (1_300, "Cao Thủ", "🥋"),
    (1_600, "Vô Địch", "👑"),
    (2_000, "Chiến Thần", "🔥"),
    (2_500, "Đấu Bậc Vương Giả", "<:vuongmien:1543461013045645323>"),
]


def pvp_rank_for_dtb(dtb: int) -> tuple[str, str]:
    label, badge = PVP_RANK_TIERS[0][1], PVP_RANK_TIERS[0][2]
    for min_dtb, lbl, bdg in PVP_RANK_TIERS:
        if dtb >= min_dtb:
            label, badge = lbl, bdg
    return label, badge


# Số trận /pvp tối đa mỗi ngày (chống spam farm ĐĐB/Vàng) — reset theo ngày
# UTC (xem pvp_matches_left / _pvp_today_str).
PVP_DAILY_MATCH_LIMIT = 10

# ĐĐB thắng/thua cơ bản + thưởng Vàng nhỏ khi thắng — nhân/cộng thêm theo
# chênh lệch sức mạnh (xem pvp_battle bên dưới, dựa trên K-factor kiểu ELO).
PVP_DTB_K_FACTOR = 32
PVP_WIN_GOLD_MIN = 200_000
PVP_WIN_GOLD_MAX = 800_000


def _pvp_today_str() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def pvp_matches_left(data: dict) -> int:
    """Số trận /pvp còn lại hôm nay — tự reset về PVP_DAILY_MATCH_LIMIT nếu
    mốc ngày lưu trong data khác ngày hiện tại (KHÔNG tự lưu data xuống DB ở
    đây — bên gọi chịu trách nhiệm asave_user_data khi cần)."""
    if data.get("pvp_matches_date") != _pvp_today_str():
        return PVP_DAILY_MATCH_LIMIT
    return max(0, PVP_DAILY_MATCH_LIMIT - data.get("pvp_matches_today", 0))


def pvp_consume_match(data: dict) -> dict:
    """Trừ 1 lượt trận /pvp hôm nay vào `data` (tự reset nếu qua ngày mới),
    trả về data đã cập nhật — bên gọi tự save."""
    today = _pvp_today_str()
    if data.get("pvp_matches_date") != today:
        data["pvp_matches_date"] = today
        data["pvp_matches_today"] = 0
    data["pvp_matches_today"] = data.get("pvp_matches_today", 0) + 1
    return data


def pvp_power(data: dict) -> float:
    """Chỉ số "sức mạnh" tổng hợp dùng để tính xác suất thắng PvP — kết hợp
    lực kéo cần (rod.pull, ảnh hưởng nhiều nhất vì thể hiện đầu tư chính),
    cấp độ người chơi, và ĐĐB hiện tại (để đối đầu công bằng hơn — người
    ĐĐB cao thường gặp đối thủ ĐĐB cao nên bản thân dtb cũng góp vào sức
    mạnh, tránh 1 người dtb thấp nhưng full đồ luôn thắng tuyệt đối)."""
    rod = RODS.get(data.get("rod"), RODS[DEFAULT_ROD_KEY])
    level = data.get("level", 1)
    dtb = data.get("dtb", 1000)
    return rod.pull * 3.0 + level * 15.0 + dtb * 0.5


def pvp_win_probability(power_a: float, power_b: float) -> float:
    """Xác suất A thắng B — công thức kiểu ELO chuẩn (logistic), scale=400
    (tương đương thang ELO cờ vua) áp trên hiệu số power thay vì dtb thuần
    để phản ánh đúng cả trang bị lẫn thứ bậc."""
    diff = power_b - power_a
    return 1.0 / (1.0 + 10 ** (diff / 400.0))


def pvp_dtb_delta(dtb_self: int, dtb_opp: int, win: bool) -> int:
    """Delta ĐĐB kiểu ELO chuẩn: kỳ vọng thắng tính riêng theo dtb 2 bên
    (khác pvp_win_probability dùng để roll thắng/thua thật — ở đây chỉ dùng
    dtb thuần để CHỈNH ĐIỂM, tách biệt "sức mạnh chiến đấu" và "điểm hạng"
    để người dtb thấp thắng người dtb cao được cộng nhiều điểm hơn, đúng
    tinh thần ELO)."""
    expected = 1.0 / (1.0 + 10 ** ((dtb_opp - dtb_self) / 400.0))
    actual = 1.0 if win else 0.0
    return round(PVP_DTB_K_FACTOR * (actual - expected))


# ---------------------------------------------------------------------------
# Khí Tức — danh hiệu hiển thị theo CẤP ĐỘ (level, khác RANK_TIERS ở trên
# vốn tính theo Điểm/score). Mốc cao hơn ghi đè mốc thấp hơn, chưa đạt mốc
# nào thì không hiện Khí Tức.
# ---------------------------------------------------------------------------
AURA_TIERS = [
    (20, "Khí Tức Tuyệt Vọng", "💀"),
    (45, "Khí Tức Tiên Nhân", "🌌"),
]


def aura_for_level(level: int) -> Optional[tuple[str, str]]:
    label, badge = None, None
    for min_level, lbl, bdg in AURA_TIERS:
        if level >= min_level:
            label, badge = lbl, bdg
    return (label, badge) if label else None


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
CAST_COOLDOWN_SECONDS = 6        # thời gian hồi giữa 2 lần /câu_cá (buff: giảm từ 12s)
CLICK_COOLDOWN_SECONDS = 0.4      # chống spam nút "Kéo!" (buff: giảm từ 0.6s)
REEL_TIMEOUT_SECONDS = 45.0        # không thao tác quá lâu -> hết hạn cứng, dừng ván
IDLE_TENSION_PER_SECOND = 2.0      # % độ căng dây tăng thêm mỗi giây KHÔNG bấm "Kéo!" (buff: giảm từ 3.0)
IDLE_TICK_SECONDS = 1.0            # tần suất kiểm tra/tăng tension khi đứng yên

# Khi độ căng dây chạm/vượt tension_max, dây KHÔNG đứt ngay lập tức nữa —
# vào trạng thái "báo động" chạy đếm ngược này trước, cho người chơi cơ
# hội cuối dùng skill (reduce_tension/slow_tension...) kéo tension xuống
# lại để cứu ván câu. Hết chừng này giây mà tension vẫn ở mức max thì dây
# mới đứt thật (xem ReelView._check_line_break).
LINE_BREAK_GRACE_SECONDS = 5.0

# Tỉ lệ TRƯỢT khi dùng skill "Đập cá" (effect instant_finish) — trước đây
# ăn chắc 100% quá bá, giờ có 30% khả năng hụt đòn: mất thể lực/lượt dùng
# như bình thường nhưng cá KHÔNG chết, ván câu vẫn tiếp tục bình thường.
INSTANT_FINISH_MISS_CHANCE = 0.30

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


def roll_fish(
    rod: Rod, map_key: Optional[str] = None, boss_weight_mult: float = 1.0,
) -> FishSpecies:
    """Chọn 1 con cá theo cấp mà lực kéo của cần hiện có thể tiếp cận.
    Cấp cao hơn có trọng số random thấp hơn (khó gặp hơn); trong 1 cấp,
    cá giá cao hơn cũng hiếm hơn.

    Nếu `map_key` được chỉ định: chỉ roll trong số cá thuộc khu vực đó.
    Nếu khu vực đó chưa có cá nào tương thích với lực kéo hiện tại, tự
    động rơi về roll không giới hạn khu vực để không bao giờ "câu hụt".

    `boss_weight_mult` (thời tiết, xem weather_data.py): nhân thêm vào
    trọng số random của cá "boss" (cá đắt nhất mỗi cấp) — >1 nghĩa là thời
    tiết hiện tại đang làm cá boss/hiếm dễ gặp hơn bình thường.
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
            return roll_fish(rod, map_key=None, boss_weight_mult=boss_weight_mult)

    tier_weights = [1.0 / (i + 1) for i in range(len(tiers))]
    tier = random.choices(tiers, weights=tier_weights)[0]

    pool = pool_for(tier.key)
    max_price = max(f.price for f in pool)
    fish_weights = [
        (max_price / f.price) ** 0.5 * (boss_weight_mult if f.key in BOSS_FISH_KEYS else 1.0)
        for f in pool
    ]
    return random.choices(pool, weights=fish_weights)[0]


# ---------------------------------------------------------------------------
# Tỉ lệ câu ra rác — 8% cơ bản, cộng thêm/bớt theo thời tiết hiện tại
# (weather.junk_chance_delta, xem weather_data.py), luôn kẹp về [0, 0.35] để
# không bao giờ ra rác quá thường xuyên (trước là nền 20%/trần 90% — cảm
# giác ra rác liên tục dù công thức chưa từng thực sự chạm gần 100%).
# ---------------------------------------------------------------------------
BASE_JUNK_CHANCE = 0.08
JUNK_CHANCE_CAP = 0.35

# "Rác" hiện là 1 tab riêng cuối cùng trong /bán (Kho Cá) — tái dùng
# FishTier chỉ để có label/key hiển thị nhất quán với các tier cá thật,
# KHÔNG đăng ký vào fish_data.TIERS (giữ nguyên không ảnh hưởng roll_fish/
# tiers_unlocked_for_pull). required_pull=0 không có ý nghĩa gì ở đây vì
# tier rác không tham gia roll theo lực kéo.
RAC_TIER = FishTier("rac", f"{E.JUNK} Rác", 0)
SELL_TIERS: list[FishTier] = TIERS + [RAC_TIER]
# Toàn bộ vật phẩm có thể bán qua /bán (cá thật + rác) — dùng cho nút
# "Bán Nhanh (Tất Cả)" để không bỏ sót rác đang tồn trong kho.
ALL_SELLABLE = ALL_FISH + JUNK_ITEMS


def roll_catch(
    rod: Rod, map_key: Optional[str] = None, weather: Optional[Weather] = None,
) -> FishSpecies:
    """Quyết định kết quả 1 lần thả cần: có `junk_chance` xác suất ra rác
    (không phụ thuộc map/lực kéo — rác trôi nổi ở đâu cũng gặp được), còn
    lại roll cá bình thường qua `roll_fish`. Trả về 1 FishSpecies — dùng
    `fish_data.is_junk_fish(result.key)` ở nơi gọi để phân biệt."""
    junk_chance = BASE_JUNK_CHANCE + (weather.junk_chance_delta if weather else 0.0)
    junk_cap = (weather.junk_chance_cap if weather and weather.junk_chance_cap is not None
                else JUNK_CHANCE_CAP)
    junk_chance = max(0.0, min(junk_cap, junk_chance))
    if random.random() < junk_chance:
        return roll_junk()
    boss_weight_mult = weather.boss_weight_mult if weather else 1.0
    return roll_fish(rod, map_key=map_key, boss_weight_mult=boss_weight_mult)



# Buff máu (target_progress) riêng cho cá "tiền khủng" — áp theo GIÁ TUYỆT
# ĐỐI của cá (không phụ thuộc tier), cộng dồn với độ dai vốn có trong cùng
# tier ở trên. Cá giá càng cao thì hệ số càng lớn.
HP_BUFF_PRICE_10M = 10_000_000
HP_BUFF_PRICE_5M = 5_000_000
HP_BUFF_MULT_OVER_10M = 3.0
HP_BUFF_MULT_OVER_5M = 2.0

# Buff máu CHUNG cho TẤT CẢ cá (nhân thêm vào target sau hp_buff_multiplier),
# theo yêu cầu tăng máu tất cả cá lên 10-20%. Đang để 1.15 (=+15%, giữa
# khoảng yêu cầu) — chỉnh trực tiếp số này thành 1.10 hoặc 1.20 nếu muốn
# đổi mức tăng.
GLOBAL_HP_MULTIPLIER = 1.15


def hp_buff_multiplier(price: int) -> float:
    """Hệ số nhân máu theo giá cá: >10 triệu xu = x3, >5 triệu xu = x2,
    còn lại = x1 (không buff)."""
    if price > HP_BUFF_PRICE_10M:
        return HP_BUFF_MULT_OVER_10M
    if price > HP_BUFF_PRICE_5M:
        return HP_BUFF_MULT_OVER_5M
    return 1.0


def compute_challenge(rod: Rod, fish: FishSpecies) -> tuple[float, float]:
    """Tính (target_progress, tension_per_click_max) cho ván kéo cá.
    Thiết kế theo tỉ lệ RIÊNG của từng cần (không phụ thuộc tuyệt đối vào
    độ lớn số liệu giữa các cần khác nhau) để cần yếu/mạnh đều cần khoảng
    5-12 lần bấm "Kéo!" hợp lý, cá đắt hơn trong cùng 1 cấp thì dai hơn.
    Cá giá trên 5/10 triệu xu được buff thêm máu qua hp_buff_multiplier.

    Nếu fish.hp_override được set (vài con boss cần CHỐT cứng 1 mức máu cụ
    thể, xem fish_data.FishSpecies.hp_override) thì bỏ qua toàn bộ công
    thức rod.pull * clicks_needed * hp_buff_multiplier ở trên, chỉ còn nhân
    thêm GLOBAL_HP_MULTIPLIER — máu con đó KHÔNG còn phụ thuộc cần câu."""
    if fish.hp_override is not None:
        clicks_needed = random.uniform(4.0, 9.0)
        target = fish.hp_override * GLOBAL_HP_MULTIPLIER
        return target, clicks_needed

    pool = FISH_BY_TIER[fish.tier_key]
    max_price = max(f.price for f in pool)
    price_ratio = fish.price / max_price  # 0..1, càng lớn cá càng "dai"

    clicks_needed = random.uniform(4.0, 9.0) * (0.6 + 0.7 * price_ratio)
    target = rod.pull * clicks_needed * hp_buff_multiplier(fish.price) * GLOBAL_HP_MULTIPLIER
    return target, clicks_needed


def format_time_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}p{s}s"


# ---------------------------------------------------------------------------
# Icon custom cho thanh tiến trình (thay ký tự khối █/░ cũ) — 6 mảnh ghép
# đầu trái/đầu phải (bo tròn) + đoạn giữa, mỗi loại có bản "đầy" (full) và
# "rỗng" (empty). LƯU Ý: đây là custom emoji, KHÔNG được bọc trong dấu
# backtick ` ` khi chèn vào nội dung tin nhắn — code span của Discord chỉ
# hiện chữ thô (<:tên:id>) chứ không render ra icon.
# ---------------------------------------------------------------------------
BAR_LEFT_EMPTY = "<:5499lb2g:1543467009059070063>"
BAR_LEFT_FULL = "<:5988lbg:1543467011248492554>"
BAR_MID_EMPTY = "<:2827l2g:1543467004193673257>"
BAR_MID_FULL = "<:3451lg:1543467001408790538>"
BAR_RIGHT_EMPTY = "<:2881lb3g:1543467006941069383>"
BAR_RIGHT_FULL = "<:3166lb4g:1543467013505024010>"


def make_bar(ratio: float, size: int = 8) -> str:
    """Vẽ thanh tiến trình bằng emoji custom (đầu trái/đầu phải bo tròn +
    đoạn giữa, xem BAR_* ở trên) thay cho ký tự khối █/░ cũ. `size` = tổng
    số ô (tính cả 2 ô đầu-cuối), tối thiểu 2 — mặc định 8 để LUÔN gói gọn
    trong 1 dòng trên màn hình điện thoại (thử ở 10 ô từng bị Discord ngắt
    dòng giữa chuỗi emoji trên mobile, làm rớt ô cuối xuống dòng dưới).
    KHÔNG bọc kết quả hàm này trong dấu backtick khi ghép vào tin nhắn
    (xem ghi chú ở BAR_*), và LUÔN đặt bar trên 1 DÒNG RIÊNG (không để
    chung dòng với nhãn chữ phía trước) để bar được bắt đầu từ đầu dòng,
    có tối đa khoảng trống trước khi bị ngắt dòng."""
    ratio = max(0.0, min(1.0, ratio))
    size = max(2, size)
    filled = max(0, min(size, round(ratio * size)))
    tiles: list[str] = []
    for i in range(size):
        is_filled = i < filled
        if i == 0:
            tiles.append(BAR_LEFT_FULL if is_filled else BAR_LEFT_EMPTY)
        elif i == size - 1:
            tiles.append(BAR_RIGHT_FULL if is_filled else BAR_RIGHT_EMPTY)
        else:
            tiles.append(BAR_MID_FULL if is_filled else BAR_MID_EMPTY)
    return "".join(tiles)


# ---------------------------------------------------------------------------
# Khung kết quả (Components V2)
# ---------------------------------------------------------------------------
# Kiểu callback "Câu Tiếp" — nhận interaction của chính cú bấm nút, tự thả
# 1 cần câu mới (xem CauCaVanCan._do_cau_ca) y hệt như gọi lại /câu_cá.
ContinueCallback = Callable[[discord.Interaction], Awaitable[None]]


def _add_continue_row(container: discord.ui.Container, on_continue: Optional[ContinueCallback]) -> None:
    """Gắn thêm 1 nút "🎣 Câu Tiếp" vào cuối khung kết quả (thành công lẫn
    đứt dây) nếu có `on_continue` — cho phép câu vòng tiếp theo ngay mà
    không cần gõ lại lệnh /câu_cá."""
    if on_continue is None:
        return
    container.add_item(discord.ui.Separator())
    row = discord.ui.ActionRow()
    btn = discord.ui.Button(
        label="Câu Tiếp", style=discord.ButtonStyle.success,
        custom_id=f"reel_continue_{uuid.uuid4().hex}",
        emoji=E.ROD,
    )

    async def _cb(interaction: discord.Interaction) -> None:
        await on_continue(interaction)

    btn.callback = _cb
    row.add_item(btn)
    container.add_item(row)


def build_fail_view(
    member: discord.Member,
    rod: Rod,
    rank_label: str,
    rank_badge: str,
    reason: str = "Con cá đã giật đứt dây và bơi mất tiêu!",
    level_info: Optional[dict] = None,
    on_continue: Optional[ContinueCallback] = None,
) -> tuple[discord.ui.LayoutView, discord.File]:
    file = discord.File(ROD_BREAK_IMAGE, filename="can_gay.png")

    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.red())

    header = (
        f"{E.TOP1} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"{E.ROD} **Cần:** {rod.emoji} `{rod.name}`"
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
            f"{E.ENERGY} **Năng lượng:** `{level_info['energy']}/{level_info['max_energy']}`"
        ))
    _add_continue_row(container, on_continue)
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
    is_junk: bool = False,
    level_info: Optional[dict] = None,
    on_continue: Optional[ContinueCallback] = None,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(
        accent_colour=discord.Colour.dark_grey() if is_junk
        else (discord.Colour.dark_purple() if is_boss else discord.Colour.gold())
    )

    header = (
        f"{E.TOP3} **{member.display_name}** {rank_badge} `[{rank_label}]`\n"
        f"{E.ROD} **Cần:** {rod.emoji} `{rod.name}`"
    )
    if is_junk:
        header = f"{E.JUNK} **CÂU PHẢI RÁC RỒI...** {E.JUNK}\n" + header
    elif is_boss:
        header = f"<:vuongmien:1543461013045645323>🐉 **ĐÃ CÂU ĐƯỢC BOSS!** <:vuongmien:1543461013045645323>🐉\n" + header
    if bait_name:
        header += (
            f"\n<:sao:1543465405484503160> **Mồi đang dùng:** {E.BAIT} **{bait_name}** "
            f"(+{bait_luck:.0%} may mắn) - Còn `{bait_time_left}`"
        )
    container.add_item(discord.ui.TextDisplay(header))
    container.add_item(discord.ui.Separator())
    if is_junk:
        container.add_item(discord.ui.TextDisplay(
            f"**{E.JUNK} Bạn kéo lên được:**\n"
            f"**Món đồ:** {fish.name}\n"
            f"**Đơn giá bán:** {E.GOLD} `{fmt_vang(fish.price)}` Vàng / món"
        ))
    else:
        container.add_item(discord.ui.TextDisplay(
            f"**<:party:1543465613853327380> Chúc mừng bạn đã câu được:**\n"
            f"**Tên cá:** {fish.name}\n"
            f"**Khối lượng:** {E.WEIGHT} `{fish.weight_label}`\n"
            f"**Đơn giá bán:** {E.GOLD} `{fmt_vang(fish.price)}` Vàng / con"
        ))
    if level_info:
        container.add_item(discord.ui.Separator())
        if is_junk:
            exp_line = f"{E.ENERGY} **Năng lượng:** `{level_info['energy']}/{level_info['max_energy']}`"
        else:
            exp_line = f"<:xp:1543460237732876369> **+{level_info['exp_gained']} EXP**"
            if level_info.get("leveled_up"):
                exp_line += f"\n<:party:1543465613853327380> **LÊN CẤP {level_info['new_level']}!** Năng lượng đã được hồi đầy."
            exp_line += f"\n{E.ENERGY} **Năng lượng:** `{level_info['energy']}/{level_info['max_energy']}`"
        if level_info.get("map_item_gained"):
            exp_line += (
                f"\n🗺️ **Nhận được vật phẩm:** `{level_info['map_item_gained']}` "
                f"— mở khóa khu vực **Vực sâu Hà La**!"
            )
        container.add_item(discord.ui.TextDisplay(exp_line))
    container.add_item(discord.ui.Separator())
    if is_junk:
        container.add_item(discord.ui.TextDisplay(
            f"# {E.JUNK}\nVẫn dùng `/bán` được nếu muốn — bán ve chai kiếm ít Vàng lẻ."
        ))
    else:
        container.add_item(discord.ui.TextDisplay(
            f"# {E.FISH_NUMBER}\nDùng `/bán` để đổi cá trong kho ra Vàng."
        ))
    _add_continue_row(container, on_continue)
    view.add_item(container)
    return view


def build_weather_view(weather: Weather, expires_at: Optional[float] = None) -> discord.ui.LayoutView:
    """Khung Components V2 thông báo/hiển thị thời tiết hiện tại — dùng
    chung bởi vòng lặp tự động mỗi giờ (weather_loop) và lệnh /thời_tiết."""
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.blue())
    container.add_item(discord.ui.TextDisplay(f"# {weather.emoji} Thời Tiết: {weather.name}"))
    container.add_item(discord.ui.Separator())

    effect_lines = [weather.description, ""]
    if weather.luck_delta:
        sign = "+" if weather.luck_delta > 0 else ""
        effect_lines.append(f"{E.LUCKY} Vận may câu cá: `{sign}{weather.luck_delta:.0%}`")
    if weather.tension_mult != 1.0:
        pct = (weather.tension_mult - 1.0)
        sign = "+" if pct > 0 else ""
        effect_lines.append(f"{E.ROD} Tốc độ căng dây câu: `{sign}{pct:.0%}`")
    if weather.boss_weight_mult != 1.0:
        effect_lines.append(f"<:vuongmien:1543461013045645323> Tỷ lệ gặp cá quý hiếm/boss: `x{weather.boss_weight_mult:.1f}`")
    container.add_item(discord.ui.TextDisplay("\n".join(effect_lines)))

    if expires_at:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"{E.CLOCK} Còn hiệu lực: `{format_time_left(expires_at - time.time())}`"
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
        weather: Optional["Weather"] = None,
        on_continue: Optional[ContinueCallback] = None,
    ):
        super().__init__(timeout=REEL_TIMEOUT_SECONDS)
        self.member = member
        self.rod = rod
        self.fish = fish
        self.luck_bonus = luck_bonus
        self.weather = weather
        # Callback "Câu Tiếp" gắn vào khung kết quả cuối ván (xem
        # build_success_view/build_fail_view) — cho phép thả cần mới ngay
        # từ nút bấm, không cần gõ lại /câu_cá.
        self.on_continue = on_continue
        # Hệ số nhân tốc độ tăng độ căng dây do thời tiết hiện tại (1.0 = bình
        # thường, <1 = dễ hơn, >1 = khó hơn). Xem weather_data.py.
        self.tension_mult = weather.tension_mult if weather else 1.0
        self.rank_label = rank_label
        self.rank_badge = rank_badge
        self.bait_name = bait_name
        self.bait_time_left = bait_time_left
        self.on_finish = on_finish  # async callback(success: bool | None, energy_used: int) -> dict
        self.is_boss = is_boss
        self.is_junk = is_junk_fish(fish.key)
        self.energy = energy            # thể lực còn lại tại thời điểm bắt đầu câu (snapshot cục bộ)
        self.max_energy = max_energy
        self.energy_spent = 0            # số thể lực đã tiêu trong ván này (số lần bấm Kéo hợp lệ)

        self.target, _ = compute_challenge(rod, fish)
        self.progress = 0.0
        self.tension_max = 100.0  # % — quy về 0-100 cho dễ hiển thị, tương ứng độ dài dây câu tối đa của cần
        self.tension = 0.0
        self.tension_break_started_at: Optional[float] = None  # mốc lúc BẮT ĐẦU đếm ngược
            # LINE_BREAK_GRACE_SECONDS giây "báo động" (tension chạm max) —
            # None nghĩa là hiện KHÔNG trong trạng thái báo động.
        self.last_click = 0.0
        self.last_action_at = time.time()  # mốc để tính tension tự tăng khi đứng yên
        self.finished = False
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()  # chặn _on_pull và _idle_tick edit chồng lên nhau

        # -- Kỹ năng (skill) — tối đa SKILL_SLOTS ô. Mỗi skill dùng được tối
        # đa `skill.uses_per_session` lần/ván (mặc định 1) — xem skill_uses.
        self.skills: list[Optional[Skill]] = list(skills or [])
        self.skill_uses: dict[str, int] = {}
        self.skill_cooldown_until: dict[str, float] = {}  # skill.key -> mốc thời
            # gian (time.time()) hết hồi chiêu, chỉ set khi skill.cooldown_s > 0
        self.tension_slow_until: float = 0.0   # timestamp, còn hiệu lực "slow_tension" tới lúc này
        self.tension_slow_factor: float = 1.0    # hệ số nhân độ căng dây khi đang có "slow_tension"
        # Hàng chờ sát thương trả chậm (cho effect "slow_then_damage"): mỗi
        # phần tử là (thời điểm áp dụng, % máu cá tối đa gây thêm).
        self.pending_damage: list[tuple[float, float]] = []
        # Tên skill "Đập cá" (instant_finish) vừa TRƯỢT ở lượt bấm gần nhất
        # (None nếu không trượt) — dùng để hiện dòng cảnh báo trong _render().
        self._last_skill_missed: Optional[str] = None
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
        self.tension += IDLE_TENSION_PER_SECOND * idle_for * slow_mult * self.tension_mult
        self.last_action_at = now

    def _check_line_break(self, now: float) -> bool:
        """Kiểm tra dây có THỰC SỰ đứt hay chưa. Khi tension chạm/vượt
        tension_max LẦN ĐẦU, KHÔNG đứt ngay — bắt đầu đếm ngược
        LINE_BREAK_GRACE_SECONDS giây "báo động" (self.tension_break_started_at),
        cho người chơi cơ hội cuối bấm "Kéo!"/dùng skill giảm tension để cứu
        ván câu. Nếu tension tụt lại dưới tension_max trong lúc đó -> hủy
        báo động, coi như an toàn. Chỉ khi tension VẪN ở mức max liên tục
        SUỐT hết khoảng thời gian trên thì mới trả về True (đứt dây thật)."""
        if self.tension < self.tension_max:
            self.tension_break_started_at = None
            return False
        if self.tension_break_started_at is None:
            self.tension_break_started_at = now
            return False
        return (now - self.tension_break_started_at) >= LINE_BREAK_GRACE_SECONDS

    def _apply_pending_damage(self, now: float) -> None:
        """Áp dụng sát thương trả chậm đã đến hạn (effect "slow_then_damage",
        vd Thái Cực Điệu) — gọi cùng lúc với `_apply_idle_tension` ở mọi nơi
        cần số liệu máu cá mới nhất."""
        if not self.pending_damage:
            return
        still_pending = []
        for trigger_at, pct in self.pending_damage:
            if now >= trigger_at:
                self.progress += self.target * pct
            else:
                still_pending.append((trigger_at, pct))
        self.pending_damage = still_pending

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
            self._apply_pending_damage(now)

            if self.progress >= self.target:
                # Sát thương trả chậm (vd Thái Cực Điệu) vừa đủ để bắt được
                # cá trong lúc đứng yên — kết thúc THÀNH CÔNG, edit thẳng
                # self.message vì idle tick không có interaction sẵn.
                self.finished = True
                self._idle_tick.stop()
                self.clear_items()
                self.stop()
                result = await self.on_finish(True, self.energy_spent)
                view = build_success_view(
                    self.member, self.rod, self.rank_label, self.rank_badge, self.fish,
                    bait_name=self.bait_name, bait_luck=self.luck_bonus,
                    bait_time_left=self.bait_time_left, is_boss=self.is_boss,
                    is_junk=self.is_junk, level_info=result, on_continue=self.on_continue,
                )
                try:
                    await self.message.edit(view=view, attachments=[])
                except discord.HTTPException:
                    pass
                return

            if self.tension < self.tension_max:
                self.tension_break_started_at = None
                return  # vẫn an toàn, KHÔNG edit UI — chỉ âm thầm cộng dồn

            if not self._check_line_break(now):
                # Vừa chạm ngưỡng max — đang trong LINE_BREAK_GRACE_SECONDS
                # giây "báo động", CHƯA đứt thật. Vẫn phải edit UI mỗi tick
                # để hiện đếm ngược cho người chơi kịp phản ứng (dùng skill
                # giảm tension) — khác _apply_idle_tension bình thường vốn
                # không edit UI.
                self._render()
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass
                return

            # Chỉ tới đây (hết hẳn LINE_BREAK_GRACE_SECONDS giây báo động mà
            # tension vẫn ở max) mới thực sự đứt dây — đây là lần edit CUỐI
            # CÙNG của idle tick trong suốt vòng đời ván câu.
            self.finished = True
            self._idle_tick.stop()
            self.clear_items()
            self.stop()
            result = await self.on_finish(False, self.energy_spent)
            view, file = build_fail_view(
                self.member, self.rod, self.rank_label, self.rank_badge,
                reason="Bạn đứng câu quá lâu không kéo, dây căng hết cỡ rồi đứt phựt!",
                level_info=result, on_continue=self.on_continue,
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
            f"{E.ROD} **{self.member.display_name}** đang câu...\n"
            f"**Cần:** {self.rod.emoji} `{self.rod.name}` "
            f"(Độ dài dây câu: `{self.rod.line_len}`)"
        )
        if self.is_junk:
            header = f"{E.JUNK} **Có vẻ chỉ là rác trôi...** {E.JUNK}\n" + header
        elif self.is_boss:
            header = f"<:vuongmien:1543461013045645323>🐉 **BOSS XUẤT HIỆN: {self.fish.name}!** <:vuongmien:1543461013045645323>🐉\n" + header
        if self.bait_name:
            header += f"\n<:sao:1543465405484503160> Mồi: {E.BAIT} **{self.bait_name}** - Còn `{self.bait_time_left}`"
        if self.weather:
            header += f"\n{self.weather.emoji} Thời tiết: **{self.weather.name}**"
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
        catch_label = f"{E.JUNK} Rác:" if self.is_junk else "🐟 Cá:"
        miss_note = (
            f"\n💢 **{self._last_skill_missed} đã TRƯỢT!** Đòn đập cá hụt, không mất máu cá.\n"
            if self._last_skill_missed else ""
        )
        break_note = ""
        if self.tension_break_started_at is not None:
            remain = max(0.0, LINE_BREAK_GRACE_SECONDS - (now - self.tension_break_started_at))
            break_note = (
                f"\n🚨 **DÂY CĂNG HẾT CỠ, SẮP ĐỨT!** Còn `{remain:.0f}s` để cứu — "
                f"mau dùng skill giảm căng dây!\n"
            )
        container.add_item(discord.ui.TextDisplay(
            f"**{catch_label}** `{self.fish.name}`\n"
            f"**Có gì đó đang cắn câu!** Bấm **Kéo!** để kéo cá vào, "
            f"nhưng đừng kéo quá tay kẻo đứt dây.\n"
            f"{miss_note}"
            f"{break_note}\n"
            f"{E.HEALTH} Máu cá: `{hp_current:,}/{hp_max:,}`\n"
            f"{make_bar(hp_ratio)}\n"
            f"Độ căng dây câu: `{tension_ratio:.0%}`{slow_note}\n"
            f"{make_bar(tension_ratio)}\n"
            f"{E.ENERGY} Năng lượng: `{self.energy}/{self.max_energy}`\n"
            f"{make_bar(energy_ratio)}"
        ))
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        btn = discord.ui.Button(
            label="Kéo!", style=discord.ButtonStyle.primary, custom_id=self._cid_pull,
            emoji=E.ROD,
        )
        btn.callback = self._on_pull
        row.add_item(btn)
        container.add_item(row)

        active_skills = [s for s in self.skills if s]
        if active_skills:
            skill_row = discord.ui.ActionRow()
            for skill in active_skills:
                uses_left = skill.uses_per_session - self.skill_uses.get(skill.key, 0)
                used = uses_left <= 0
                can_afford = self.energy >= skill.energy_cost
                cooldown_left = self.skill_cooldown_until.get(skill.key, 0.0) - now
                on_cooldown = cooldown_left > 0
                uses_suffix = f" x{uses_left}" if skill.uses_per_session > 1 else ""
                cd_suffix = f" ⏳{cooldown_left:.0f}s" if on_cooldown else ""
                skill_btn = discord.ui.Button(
                    label=f"{skill.emoji} {skill.name} ({skill.energy_cost} NL){uses_suffix}{cd_suffix}",
                    style=discord.ButtonStyle.secondary,
                    disabled=used or not can_afford or on_cooldown,
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
                f"{E.ENERGY} Bạn đã hết năng lượng rồi, phải nghỉ tay cho năng lượng hồi lại đã "
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
            self._apply_pending_damage(now)

            # BUFF "op": sát thương/lần kéo cao hơn (1.3-1.8x thay vì 0.9-1.3x)
            # và luck ăn mạnh hơn (x0.8 thay vì x0.5).
            dmg = self.rod.pull * random.uniform(1.3, 1.8) * (1 + self.luck_bonus * 0.8)
            self.progress += dmg

            slow_mult = self.tension_slow_factor if now < self.tension_slow_until else 1.0
            # BUFF "op": độ căng dây tăng chậm hơn hẳn (chia cho khoảng random
            # lớn hơn) và luck giảm căng dây mạnh hơn (x0.6 thay vì x0.4),
            # đồng thời nhân thêm hệ số thời tiết (self.tension_mult).
            base_tension_gain = max(
                0.6,
                100.0 / random.uniform(9.0, 14.0) * (1 - self.luck_bonus * 0.6),
            ) * self.tension_mult
            self.tension += base_tension_gain * slow_mult

            self.energy -= 1
            self.energy_spent += 1

            if self.progress >= self.target:
                self.finished = True
                self._idle_tick.stop()
                await self._finish(interaction, success=True)
                return
            if self._check_line_break(now):
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
        if self.skill_uses.get(skill.key, 0) >= skill.uses_per_session:
            await interaction.response.send_message(
                f"⚠️ Bạn đã dùng hết lượt **{skill.name}** trong ván câu này rồi!", ephemeral=True,
            )
            return
        cooldown_left = self.skill_cooldown_until.get(skill.key, 0.0) - time.time()
        if cooldown_left > 0:
            await interaction.response.send_message(
                f"⏳ **{skill.name}** còn `{cooldown_left:.0f}s` nữa mới hồi chiêu xong!",
                ephemeral=True,
            )
            return
        if self.energy < skill.energy_cost:
            await interaction.response.send_message(
                f"{E.ENERGY} Không đủ năng lượng để dùng **{skill.name}** (cần `{skill.energy_cost}`)!",
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
            self._apply_pending_damage(now)
            self.energy -= skill.energy_cost
            self.energy_spent += skill.energy_cost
            self.skill_uses[skill.key] = self.skill_uses.get(skill.key, 0) + 1
            if skill.cooldown_s > 0:
                self.skill_cooldown_until[skill.key] = now + skill.cooldown_s
            self._last_skill_missed = None  # reset cảnh báo trượt của lượt trước

            if skill.effect == "reduce_tension":
                self.tension = max(0.0, self.tension - self.tension_max * skill.value)
            elif skill.effect == "slow_tension":
                self.tension_slow_until = now + skill.duration_s
                self.tension_slow_factor = 1.0 - skill.value
            elif skill.effect == "reduce_then_slow":
                # "Can Môn Quan" (Giật + Kéo) — trừ NGAY một phần độ căng
                # dây (như reduce_tension) VÀ đồng thời làm chậm tốc độ
                # tăng căng dây trong duration_s giây kế tiếp (như
                # slow_tension) — không gây thêm sát thương lên cá.
                self.tension = max(0.0, self.tension - self.tension_max * skill.value)
                self.tension_slow_until = now + skill.duration_s
                self.tension_slow_factor = 1.0 - skill.slow_value
            elif skill.effect == "damage_fish_hp":
                # Gây sát thương thẳng ngay lập tức, tính theo % máu tối đa
                # của cá (self.target), không liên quan tới độ căng dây.
                self.progress += self.target * skill.value
            elif skill.effect == "slow_then_damage":
                # "Thái Cực Điệu" — vừa làm chậm độ căng dây trong
                # duration_s giây, vừa xếp lịch gây thêm sát thương ngay
                # khi hiệu lực làm chậm kết thúc (xem _apply_pending_damage).
                self.tension_slow_until = now + skill.duration_s
                self.tension_slow_factor = 1.0 - skill.value
                self.pending_damage.append((now + skill.duration_s, skill.bonus_damage_pct))
            elif skill.effect == "instant_finish":
                # "Khai Thiên Môn Đập Cá" và các đòn "Đập cá" khác — bắt cá
                # NGAY LẬP TỨC nếu thành công, nhưng KHÔNG còn ăn chắc 100%
                # nữa: có INSTANT_FINISH_MISS_CHANCE (30%) tỉ lệ TRƯỢT, đòn
                # coi như hụt — mất thể lực/lượt dùng như bình thường, cá
                # KHÔNG chết, ván câu vẫn tiếp tục (KHÔNG đứt dây do trượt).
                if random.random() < INSTANT_FINISH_MISS_CHANCE:
                    self._last_skill_missed = skill.name
                else:
                    self.progress = self.target
            elif skill.effect == "damage_value":
                # Khai Thiên Môn / Phá Phủ Trầm Chu / Bắc Minh Điếu Pháp /
                # Càn Môn Khai / Tâm Thương — trước đây đều dùng
                # "instant_finish" (kết liễu ngay 100% máu cá bất kể cá
                # dai cỡ nào => quá bá đạo với cá boss máu buff cao).
                # Giờ đổi thành gây sát thương THẲNG một GIÁ TRỊ cố định
                # (quy theo lực kéo của cần đang dùng: rod.pull * value,
                # value = số "lần kéo" quy đổi — KHÔNG còn theo % máu tối
                # đa của cá), mỗi chiêu 1 giá trị `value` riêng để phân
                # biệt sức mạnh giữa các chiêu. Vẫn giữ tỉ lệ TRƯỢT
                # INSTANT_FINISH_MISS_CHANCE cho đúng cảm giác "đập cá".
                if random.random() < INSTANT_FINISH_MISS_CHANCE:
                    self._last_skill_missed = skill.name
                else:
                    self.progress += self.rod.pull * skill.value

            # Nếu phần tension ngầm đã kịp vượt ngưỡng NGAY TRƯỚC LÚC skill
            # kịp giảm nó xuống thì cũng KHÔNG đứt ngay nữa — vẫn còn
            # LINE_BREAK_GRACE_SECONDS giây báo động (xem _check_line_break),
            # đây chính là chiêu skill "cứu" ván câu vào phút chót nếu skill
            # kéo tension xuống dưới max kịp trong khoảng thời gian đó.
            if self.progress >= self.target:
                self.finished = True
                self._idle_tick.stop()
                await self._finish(interaction, success=True)
                return
            if self._check_line_break(now):
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
                    is_junk=self.is_junk, level_info=result, on_continue=self.on_continue,
                )
                await interaction.response.edit_message(view=view, attachments=[])
            else:
                view, file = build_fail_view(
                    self.member, self.rod, self.rank_label, self.rank_badge,
                    level_info=result, on_continue=self.on_continue,
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
            _add_continue_row(container, self.on_continue)
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
        # LƯU Ý: trước đây hiển thị rod.dps ("Sát thương/giây") ở đây, nhưng
        # số này KHÔNG được dùng trong công thức tính sát thương thật lúc
        # câu (xem `dmg = self.rod.pull * uniform(1.3, 1.8) * ...` trong
        # ReelView._on_pull) -> hiện số dps to hơn hẳn (vd 350) trong khi
        # sát thương thực tế mỗi lần bấm "Kéo!" chỉ dựa theo Lực kéo (vd 50
        # -> ra khoảng 50-150 tùy may mắn), khiến người chơi thấy lệch số
        # liệu. Đổi sang hiển thị đúng khoảng sát thương THỰC TẾ mỗi lần
        # kéo, tính trực tiếp từ rod.pull để luôn khớp với gameplay.
        # Khớp đúng công thức trong ReelView._on_pull: dmg = pull * U(1.3,1.8)
        # * (1 + luck_bonus*0.8) — luck_bonus tối đa thực tế = mồi Hoàng Kim
        # (0.30) + thời tiết Cầu Vồng (0.50) = 0.80 -> hệ số nhân tối đa 1.64.
        dmg_low = round(rod.pull * 1.3)
        dmg_high = round(rod.pull * 1.8 * 1.64)
        stats = (
            f"**Sát thương/lần kéo:** `{dmg_low:,} - {dmg_high:,}`\n"
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

        # LƯU Ý: KHÔNG self.add_item(container) ở đây — hàm này được cả
        # _render() (trường hợp đứng độc lập) VÀ UnifiedShopView (trường hợp
        # nhúng, truyền vào container CỦA UNIFIED chứ không phải của
        # RodShopView) cùng gọi. Trước đây có 1 dòng self.add_item(container)
        # thừa ở đây khiến: (1) đứng độc lập thì container bị add 2 LẦN vào
        # cùng 1 view (add lại ở _render), và (2) khi bị UnifiedShopView
        # nhúng vào, mỗi lần đổi tab/trang/mua đồ lại vô tình nhét thêm 1
        # bản container VÀO CHÍNH self.rod_shop (không phải view đang hiển
        # thị) — rò rỉ item tích lũy dần qua mỗi lần bấm nút, tới khi vượt
        # giới hạn số children của 1 View thì toàn bộ shop bấm gì cũng lỗi
        # ("Tương tác này thất bại" / không phản hồi). Chỉ nơi thực sự sở
        # hữu view đang hiển thị (RodShopView._render() hoặc
        # UnifiedShopView._render()) mới được add_item(container).

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
        self._cid_buy_slot = f"skillshop_buyslot_{uuid.uuid4().hex}"
        # Số ô có thể tăng khi mua thêm giữa lúc dùng view -> tạo custom_id
        # theo đúng số ô hiện tại của data (không fix cứng SKILL_SLOTS nữa).
        self._cid_slots = [f"skillshop_slot{i}_{uuid.uuid4().hex}" for i in range(slot_count(data))]
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
        n_slots = slot_count(data)
        equipped_keys = (list(data.get("equipped_skills", [None] * n_slots))
                         + [None] * n_slots)[:n_slots]
        # custom_id các ô có thể chưa đủ nếu vừa mua thêm ô giữa lúc dùng
        # view này (self._cid_slots được tạo lúc __init__ theo số ô lúc đó).
        while len(self._cid_slots) < n_slots:
            self._cid_slots.append(f"skillshop_slot{len(self._cid_slots)}_{uuid.uuid4().hex}")

        container.add_item(discord.ui.TextDisplay(
            f"## {skill.emoji} {skill.name}  ({self.index + 1}/{len(SKILL_SHOP)})"
        ))

        if skill.effect == "reduce_tension":
            effect_line = f"Trừ ngay `{skill.value:.0%}` độ căng dây khi dùng."
        elif skill.effect == "slow_tension":
            effect_line = f"Giảm `{skill.value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s`."
        elif skill.effect == "reduce_then_slow":
            effect_line = (
                f"Trừ ngay `{skill.value:.0%}` độ căng dây, đồng thời giảm "
                f"`{skill.slow_value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s` kế tiếp."
            )
        elif skill.effect == "damage_fish_hp":
            effect_line = f"Gây sát thương ngay bằng `{skill.value:.0%}` máu tối đa của cá."
        elif skill.effect == "slow_then_damage":
            effect_line = (
                f"Giảm `{skill.value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s`. "
                f"Sau khi hiệu lực kết thúc, gây thêm `{skill.bonus_damage_pct:.0%}` máu tối đa của cá."
            )
        elif skill.effect == "damage_value":
            effect_line = (
                f"Gây sát thương ngay bằng `{skill.value:.1f}x` lực kéo của cần đang dùng "
                f"(KHÔNG theo % máu cá) — có `{1 - INSTANT_FINISH_MISS_CHANCE:.0%}` cơ hội "
                f"trúng đòn, nếu trượt thì coi như hụt (không mất cá)."
            )
        else:  # instant_finish — KHÔNG hiện % (né hết số liệu vì đã có tỉ
            # lệ trượt riêng, hiện % ở đây dễ gây hiểu lầm là % sát thương).
            effect_line = (
                f"Dồn toàn lực kết liễu con mồi — có `{1 - INSTANT_FINISH_MISS_CHANCE:.0%}` "
                f"cơ hội BẮT CÁ NGAY LẬP TỨC, nếu trượt thì coi như hụt đòn (không mất cá)."
            )

        uses_note = (
            f"{skill.uses_per_session} lần/ván câu" if skill.uses_per_session > 1 else "1 lần/ván câu"
        )
        cooldown_note = f", hồi chiêu `{skill.cooldown_s:.0f}s`/lần" if skill.cooldown_s > 0 else ""
        stats = (
            f"{skill.description}\n"
            f"**Hiệu ứng:** {effect_line}\n"
            f"**Năng lượng tiêu hao:** `{skill.energy_cost}` mỗi lần dùng (`{uses_note}`{cooldown_note})\n"
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
            container.add_item(action_row)
        else:
            # Tối đa 5 nút/hàng (giới hạn Discord) -> chia thành nhiều hàng
            # nếu người chơi đã mua thêm ô vượt quá 5.
            for start in range(0, n_slots, 5):
                row = discord.ui.ActionRow() if start > 0 else action_row
                for i in range(start, min(start + 5, n_slots)):
                    in_slot = equipped_keys[i] == skill.key
                    slot_btn = discord.ui.Button(
                        label=f"{'✅ ' if in_slot else ''}Ô {i + 1}",
                        style=discord.ButtonStyle.success if in_slot else discord.ButtonStyle.secondary,
                        custom_id=self._cid_slots[i],
                    )
                    slot_btn.callback = self._make_slot_cb(i)
                    row.add_item(slot_btn)
                container.add_item(row)

        # Nút mua thêm ô trang bị — hiện luôn (không phụ thuộc skill đang
        # xem), giá tăng dần theo skill_data.next_slot_price().
        price = next_slot_price(data)
        if price is not None:
            slot_row = discord.ui.ActionRow()
            buy_slot_btn = discord.ui.Button(
                label=f"🧩 Mua Thêm Ô Trang Bị ({fmt_gia_trieu(price)})",
                style=discord.ButtonStyle.blurple,
                disabled=data["vang"] < price,
                custom_id=self._cid_buy_slot,
            )
            buy_slot_btn.callback = self._buy_slot
            slot_row.add_item(buy_slot_btn)
            container.add_item(slot_row)

        if owned:
            equipped_line = " · ".join(
                f"Ô{i + 1}: {SKILLS[k].emoji} {SKILLS[k].name}" if k in SKILLS else f"Ô{i + 1}: —"
                for i, k in enumerate(equipped_keys)
            )
            container.add_item(discord.ui.TextDisplay(
                f"_Bấm 1 ô để trang bị/gỡ kỹ năng này khỏi ô đó._\n"
                f"**Đang có {n_slots} ô · Đang trang bị:** {equipped_line}"
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
            n_slots = slot_count(data)
            equipped = (list(data.get("equipped_skills", [None] * n_slots))
                        + [None] * n_slots)[:n_slots]
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

    async def _buy_slot(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        data = await aget_user_data(self.user_id)
        price = next_slot_price(data)
        if price is None:
            await interaction.followup.send("Bạn đã mua tối đa số ô trang bị rồi!", ephemeral=True)
            return
        if data["vang"] < price:
            await interaction.followup.send(
                f"Bạn không đủ Vàng! Cần `{fmt_gia_trieu(price)}` Vàng.", ephemeral=True
            )
            return
        data["vang"] -= price
        data["extra_skill_slots"] = int(data.get("extra_skill_slots", 0) or 0) + 1
        # Mở rộng luôn mảng equipped_skills để khớp số ô mới (ô mới = None).
        n_slots = slot_count(data)
        equipped = (list(data.get("equipped_skills", [])) + [None] * n_slots)[:n_slots]
        data["equipped_skills"] = equipped
        await asave_user_data(self.user_id, data)
        await self._refresh(interaction, data)


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
                f"<:sao:1543465405484503160> Đang dùng: {E.BAIT} **{bait_data.get('name', '?')}** "
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
# Nút "🎁 Nhập Code" trong /đồ_câu_lão_bát — mở modal nhập text, đổi thưởng
# qua firebase_db.aredeem_code (xem CODES_ROOT/reward ở đó). Admin tạo code
# bằng lệnh /tạo-code (cuối file, trong CauCaVanCan).
# ---------------------------------------------------------------------------
class RedeemCodeModal(discord.ui.Modal, title="🎁 Nhập Code"):
    code_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Nhập code",
        placeholder="VD: VANCAN2026",
        min_length=1,
        max_length=64,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        code = self.code_input.value.strip().upper()

        outcome = await aredeem_code(code, interaction.user.id)
        status = outcome["status"]
        if status == "not_found":
            await interaction.followup.send(
                f"❌ Không tìm thấy code `{code}` (sai hoặc chưa từng tồn tại)!",
                ephemeral=True,
            )
            return
        if status == "already_used":
            await interaction.followup.send(
                f"⚠️ Bạn đã đổi code `{code}` rồi, mỗi người chỉ đổi được 1 lần!",
                ephemeral=True,
            )
            return
        if status == "exhausted":
            await interaction.followup.send(
                f"⚠️ Code `{code}` đã hết lượt đổi!", ephemeral=True,
            )
            return
        if status == "expired":
            await interaction.followup.send(
                f"{E.CLOCK} Code `{code}` đã hết hạn sử dụng, không thể đổi được nữa!",
                ephemeral=True,
            )
            return

        reward: dict = outcome.get("reward") or {}
        data = await aget_user_data(interaction.user.id)
        lines: list[str] = []

        vang = reward.get("vang")
        if vang:
            data["vang"] = data.get("vang", 0) + vang
            lines.append(f"{E.GOLD} **+{fmt_vang(vang)}** Vàng")

        rod_key = reward.get("rod")
        if rod_key and rod_key in RODS:
            unlocked_rods = set(data.get("unlocked_rods", []))
            unlocked_rods.add(rod_key)
            data["unlocked_rods"] = list(unlocked_rods)
            rod = RODS[rod_key]
            lines.append(f"{E.ROD} Cần câu **{rod.emoji} {rod.name}**")

        skill_key = reward.get("skill")
        if skill_key and skill_key in SKILLS:
            unlocked_skills = set(data.get("unlocked_skills", []))
            unlocked_skills.add(skill_key)
            data["unlocked_skills"] = list(unlocked_skills)
            skill = SKILLS[skill_key]
            lines.append(f"🧩 Kỹ năng **{skill.emoji} {skill.name}** (mở khóa — dùng `/đồ_câu_lão_bát` để trang bị)")

        bait_key = reward.get("bait")
        if bait_key and bait_key in BAITS:
            bait = BAITS[bait_key]
            data["bait"] = {
                "name": bait.name,
                "luck": bait.luck,
                "expires_at": time.time() + bait.duration_s,
            }
            lines.append(f"{E.BAIT} Mồi **{bait.name}** (+{bait.luck:.0%} may mắn, dùng ngay)")

        if not lines:
            # Code hợp lệ nhưng reward rỗng (không nên xảy ra nếu tạo bằng
            # /tạo-code — chỉ phòng hờ dữ liệu Firebase bị sửa tay).
            await interaction.followup.send(
                f"⚠️ Code `{code}` không có phần thưởng hợp lệ nào!", ephemeral=True,
            )
            return

        await asave_user_data(interaction.user.id, data)

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=discord.Colour.green())
        container.add_item(discord.ui.TextDisplay(
            f"## 🎁 Đổi code `{code}` thành công!\n" + "\n".join(f"- {l}" for l in lines)
        ))
        view.add_item(container)
        await interaction.followup.send(view=view, ephemeral=True)


# ---------------------------------------------------------------------------
# Shop gộp — "/đồ_câu_Lão_Bát": 1 view duy nhất với tab lớn trên cùng
# [Cần Câu] [Kỹ Năng] [Mồi Câu]. Mỗi tab NHÚNG lại nguyên logic phân trang/
# mua/trang bị của shop con tương ứng (RodShopView/SkillShopView/
# BaitShopView) thông qua _build_container() + hook _on_change — không
# copy-paste lại code, chỉ khác phần khung tab lớn bên ngoài.
# ---------------------------------------------------------------------------
class UnifiedShopView(discord.ui.LayoutView):
    TABS = ("can_cau", "ky_nang", "moi_cau")
    # Icon custom PHẢI truyền qua tham số `emoji=` riêng (không nhúng vào
    # label text) — xem TAB_EMOJIS, giống UnifiedShopView/LeaderboardView.
    TAB_LABELS = {"can_cau": "Cần Câu", "ky_nang": "🧩 Kỹ Năng", "moi_cau": "Mồi Câu"}
    TAB_EMOJIS = {"can_cau": E.ROD, "moi_cau": E.BAIT}

    def __init__(self, user_id: int, data: dict, tab: str = "can_cau"):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.tab = tab
        self._cid_tabs = {t: f"unishop_tab_{t}_{uuid.uuid4().hex}" for t in self.TABS}
        self._cid_redeem = f"unishop_redeem_{uuid.uuid4().hex}"

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
                emoji=self.TAB_EMOJIS.get(t),
            )
            btn.callback = self._make_switch_tab_cb(t)
            tab_row.add_item(btn)
        redeem_btn = discord.ui.Button(
            label="🎁 Nhập Code", style=discord.ButtonStyle.success, custom_id=self._cid_redeem,
        )
        redeem_btn.callback = self._on_redeem_code
        tab_row.add_item(redeem_btn)
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

    async def _on_redeem_code(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        # send_modal() PHẢI là phản hồi ĐẦU TIÊN cho interaction này — không
        # được defer()/gọi response nào khác trước đó.
        await interaction.response.send_modal(RedeemCodeModal())


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
        tier = SELL_TIERS[self.tier_index]
        owned = self._owned_in_tier(data, tier.key)
        tier_total = sum(f.price * q for f, q in owned)
        grand_total = sum(
            f.price * q for f in ALL_SELLABLE for k, q in [(f.key, data.get("inventory", {}).get(f.key, 0))] if q > 0
        )

        container = discord.ui.Container(accent_colour=discord.Colour.green())
        container.add_item(discord.ui.TextDisplay(
            f"## 🐟 Kho Cá — {tier.label}  ({self.tier_index + 1}/{len(SELL_TIERS)})"
        ))

        if not owned:
            container.add_item(discord.ui.TextDisplay("_Bạn chưa có gì ở mục này._"))
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
                                       disabled=self.tier_index == len(SELL_TIERS) - 1,
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
        self.tier_index = min(len(SELL_TIERS) - 1, self.tier_index + 1)
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
        owned = self._owned_in_tier(data, SELL_TIERS[self.tier_index].key)
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
        for fish in ALL_SELLABLE:
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
        owned_items = set(data.get("map_items", []) or [])
        unlocked = [m for m in MAPS if map_is_unlocked(m.key, level, owned_items)]
        locked = [m for m in MAPS if not map_is_unlocked(m.key, level, owned_items)]

        container = discord.ui.Container(accent_colour=discord.Colour.blurple())
        container.add_item(discord.ui.TextDisplay("## 🗺️ Chọn Khu Vực Câu"))
        container.add_item(discord.ui.Separator())

        current_label = "🌐 Tất cả khu vực (mặc định)"
        if current and current in MAP_BY_KEY:
            m = MAP_BY_KEY[current]
            current_label = f"{m.emoji} {m.label}"
        lines = [f"**Đang chọn:** {current_label}"]
        if locked:
            lock_bits = []
            for m in locked:
                reason = f"mở ở Lv.{m.unlock_level}"
                if m.requires_item and m.requires_item not in owned_items:
                    reason += " + cần vật phẩm bản đồ"
                lock_bits.append(f"🔒 {m.emoji} {m.label} — {reason}")
            lines.append("\n**Chưa mở khóa:**\n" + "\n".join(lock_bits))
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
# Bảng xếp hạng — "/bảng_xếp_hạng": 1 view gộp 2 tab [Cân Nặng] [Vàng], style
# tab y hệt UnifiedShopView. Top 10 mỗi bảng, đọc 1 LẦN toàn bộ fishing/users
# (aget_all_users) rồi tự sắp xếp — không cần index/nhánh riêng trên Firebase
# vì lượng user của 1 bot Discord quy mô này đọc trọn nhánh vẫn rẻ.
# ---------------------------------------------------------------------------
class LeaderboardView(discord.ui.LayoutView):
    TABS = ("can_nang", "vang")
    # LƯU Ý: label của discord.ui.Button chỉ nhận TEXT THUẦN — cú pháp emoji
    # custom `<:tên:id>` KHÔNG được Discord parse trong label (khác với
    # TextDisplay/nội dung tin nhắn thường), nên nếu nhét thẳng vào label sẽ
    # hiện nguyên văn `<:xu:...>` thay vì icon (bug đã gặp ở nút "Vàng" cũ).
    # Icon custom PHẢI truyền qua tham số `emoji=` riêng — xem TAB_EMOJIS.
    TAB_LABELS = {"can_nang": "Cân Nặng Cá", "vang": "Xu"}
    TAB_EMOJIS = {"can_nang": E.WEIGHT, "vang": E.GOLD}
    TOP_N = 10
    _MEDALS = ("🥇", "🥈", "🥉")

    def __init__(
        self,
        bot: commands.Bot,
        rows_weight: list[tuple[int, float]],
        rows_vang: list[tuple[int, float]],
        names: dict[int, str],
        tab: str = "can_nang",
    ):
        super().__init__(timeout=120)
        self.bot = bot
        self.rows_weight = rows_weight
        self.rows_vang = rows_vang
        self.names = names
        self.tab = tab
        self._cid_tabs = {t: f"lb_tab_{t}_{uuid.uuid4().hex}" for t in self.TABS}
        self._render()

    @classmethod
    async def create(
        cls, bot: commands.Bot, guild: Optional[discord.Guild], tab: str = "can_nang",
    ) -> "LeaderboardView":
        raw_users = await aget_all_users()

        rows_weight: list[tuple[int, float]] = []
        rows_vang: list[tuple[int, float]] = []
        for uid_str, data in raw_users.items():
            if not isinstance(data, dict):
                continue
            try:
                uid = int(uid_str)
            except (TypeError, ValueError):
                continue
            weight = data.get("total_weight_can") or 0
            vang = data.get("vang") or 0
            if weight > 0:
                rows_weight.append((uid, float(weight)))
            if vang and vang != float("inf"):
                rows_vang.append((uid, float(vang)))

        rows_weight.sort(key=lambda pair: pair[1], reverse=True)
        rows_vang.sort(key=lambda pair: pair[1], reverse=True)
        rows_weight = rows_weight[: cls.TOP_N]
        rows_vang = rows_vang[: cls.TOP_N]

        needed_ids = {uid for uid, _ in rows_weight} | {uid for uid, _ in rows_vang}
        names: dict[int, str] = {}
        for uid in needed_ids:
            names[uid] = await cls._resolve_name(bot, guild, uid)

        return cls(bot, rows_weight, rows_vang, names, tab)

    @staticmethod
    async def _resolve_name(bot: commands.Bot, guild: Optional[discord.Guild], user_id: int) -> str:
        """Ưu tiên nickname trong server (display_name) — fallback về
        username toàn cục nếu không còn ở server / bot chưa cache, và
        cuối cùng là "Người chơi <id>" nếu không tra được (đã rời Discord)."""
        if guild is not None:
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.HTTPException:
                    member = None
            if member is not None:
                return member.display_name
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.HTTPException:
                user = None
        return user.name if user is not None else f"Người chơi {user_id}"

    def _rank_badge(self, index: int) -> str:
        if index < len(self._MEDALS):
            return self._MEDALS[index]
        return f"`#{index + 1}`"

    def _render(self) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_colour=discord.Colour.gold())
        container.add_item(discord.ui.TextDisplay("# <:cup:1543460863170707466> Bảng Xếp Hạng Câu Cá Vạn Cân"))

        tab_row = discord.ui.ActionRow()
        for t in self.TABS:
            btn = discord.ui.Button(
                label=self.TAB_LABELS[t],
                emoji=self.TAB_EMOJIS.get(t),
                style=discord.ButtonStyle.primary if self.tab == t else discord.ButtonStyle.secondary,
                custom_id=self._cid_tabs[t],
            )
            btn.callback = self._make_switch_tab_cb(t)
            tab_row.add_item(btn)
        container.add_item(tab_row)
        container.add_item(discord.ui.Separator())

        rows = self.rows_weight if self.tab == "can_nang" else self.rows_vang
        if not rows:
            container.add_item(discord.ui.TextDisplay(
                "_Chưa có ai lọt bảng xếp hạng này — đi câu vài con rồi quay lại xem!_"
            ))
        else:
            lines = []
            for i, (uid, value) in enumerate(rows):
                name = self.names.get(uid, f"Người chơi {uid}")
                if self.tab == "can_nang":
                    value_str = f"`{fmt_vang(value)} cân`"
                else:
                    value_str = f"{E.GOLD} `{fmt_vang(value)}` Vàng"
                lines.append(f"{self._rank_badge(i)} **{name}** — {value_str}")
            container.add_item(discord.ui.TextDisplay("\n".join(lines)))

        if self.tab == "can_nang":
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                "-# Tổng khối lượng cá đã câu được cả đời (cộng dồn, không "
                "trừ khi bán cá). Cá chưa xác định khối lượng không được tính."
            ))

        self.add_item(container)

    def _make_switch_tab_cb(self, tab: str):
        async def _cb(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            self.tab = tab
            self._render()
            await interaction.edit_original_response(view=self)
        return _cb


# ---------------------------------------------------------------------------
# PvP — logic trận đấu (không phải minigame riêng, TỰ ĐỘNG roll kết quả có
# trọng số dựa trên pvp_power() của 2 bên — xem pvp_win_probability) +
# Container V2 hiển thị kết quả, dùng chung cho cả 2 luồng vào trận:
# ghép ngẫu nhiên (PvPQueueView) và thách đấu trực tiếp (PvPChallengeView).
# ---------------------------------------------------------------------------
@dataclass
class PvPResult:
    winner_id: int
    loser_id: int
    winner_delta: int
    loser_delta: int
    gold_reward: int
    winner_dtb_after: int
    loser_dtb_after: int


async def run_pvp_battle(
    user_a: discord.abc.User, user_b: discord.abc.User, friendly: bool = False,
) -> tuple[PvPResult, dict, dict]:
    """Chạy 1 trận PvP hoàn chỉnh: đọc data 2 bên, roll thắng/thua theo
    trọng số sức mạnh. Nếu `friendly=False` (mặc định, trận xếp hạng):
    cập nhật + LƯU ĐĐB/Vàng/thắng-thua/lượt trận trong ngày cho CẢ HAI.
    Nếu `friendly=True` (đấu giao hữu): CHỈ roll kết quả để xem ai thắng,
    KHÔNG đụng tới ĐĐB/Vàng/lượt trận/thắng-thua — chơi cho vui, không
    tốn lượt PvP trong ngày. Trả về (PvPResult, data_a mới, data_b mới)."""
    data_a = await aget_user_data(user_a.id)
    data_b = await aget_user_data(user_b.id)

    power_a = pvp_power(data_a)
    power_b = pvp_power(data_b)
    a_wins = random.random() < pvp_win_probability(power_a, power_b)

    winner_id, loser_id = (user_a.id, user_b.id) if a_wins else (user_b.id, user_a.id)
    winner_data, loser_data = (data_a, data_b) if a_wins else (data_b, data_a)

    dtb_winner = winner_data.get("dtb", 1000)
    dtb_loser = loser_data.get("dtb", 1000)

    if friendly:
        # Giao hữu: không đổi ĐĐB/Vàng/lượt/thống kê — chỉ hiển thị kết quả.
        result = PvPResult(
            winner_id=winner_id, loser_id=loser_id,
            winner_delta=0, loser_delta=0, gold_reward=0,
            winner_dtb_after=dtb_winner, loser_dtb_after=dtb_loser,
        )
        return result, data_a, data_b

    winner_delta = pvp_dtb_delta(dtb_winner, dtb_loser, win=True)
    loser_delta = pvp_dtb_delta(dtb_loser, dtb_winner, win=False)
    # Thắng luôn được ít nhất +1 ĐĐB, thua luôn mất ít nhất -1 (tránh delta
    # 0 khi chênh lệch sức mạnh quá lớn khiến kết quả cảm giác vô nghĩa).
    winner_delta = max(1, winner_delta)
    loser_delta = min(-1, loser_delta)

    gold_reward = random.randint(PVP_WIN_GOLD_MIN, PVP_WIN_GOLD_MAX)

    winner_data["dtb"] = max(0, dtb_winner + winner_delta)
    winner_data["pvp_wins"] = winner_data.get("pvp_wins", 0) + 1
    if winner_data.get("vang") != float("inf"):
        winner_data["vang"] = winner_data.get("vang", 0) + gold_reward
    winner_data = pvp_consume_match(winner_data)

    loser_data["dtb"] = max(0, dtb_loser + loser_delta)
    loser_data["pvp_losses"] = loser_data.get("pvp_losses", 0) + 1
    loser_data = pvp_consume_match(loser_data)

    await asave_user_data(winner_id, winner_data)
    await asave_user_data(loser_id, loser_data)

    result = PvPResult(
        winner_id=winner_id, loser_id=loser_id,
        winner_delta=winner_delta, loser_delta=loser_delta,
        gold_reward=gold_reward,
        winner_dtb_after=winner_data["dtb"], loser_dtb_after=loser_data["dtb"],
    )
    new_data_a = winner_data if winner_id == user_a.id else loser_data
    new_data_b = winner_data if winner_id == user_b.id else loser_data
    return result, new_data_a, new_data_b


def build_pvp_result_view(
    user_a: discord.abc.User, user_b: discord.abc.User, result: PvPResult,
    friendly: bool = False,
) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    winner = user_a if result.winner_id == user_a.id else user_b
    loser = user_b if result.winner_id == user_a.id else user_a

    container = discord.ui.Container(
        accent_colour=discord.Colour.teal() if friendly else discord.Colour.red()
    )
    container.add_item(discord.ui.TextDisplay(
        f"# {'🤝 Giao Hữu PvP' if friendly else '⚔️ Kết Quả PvP'}"
    ))
    container.add_item(discord.ui.TextDisplay(
        f"**{user_a.display_name}** 🆚 **{user_b.display_name}**"
    ))
    container.add_item(discord.ui.Separator())

    if friendly:
        container.add_item(discord.ui.TextDisplay(
            f"🏆 **{winner.display_name}** thắng ván giao hữu!\n"
            f"💀 **{loser.display_name}** thua ván này."
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "-# Đấu giao hữu: không tính ĐĐB, không thưởng Vàng, không tốn "
            "lượt PvP trong ngày — chỉ để xem ai mạnh hơn."
        ))
    else:
        w_label, w_badge = pvp_rank_for_dtb(result.winner_dtb_after)
        l_label, l_badge = pvp_rank_for_dtb(result.loser_dtb_after)
        container.add_item(discord.ui.TextDisplay(
            f"🏆 **{winner.display_name}** chiến thắng!\n"
            f"{w_badge} `[{w_label}]` — ĐĐB: `{result.winner_dtb_after}` "
            f"(`+{result.winner_delta}`)\n"
            f"{E.GOLD} Thưởng: `+{fmt_vang(result.gold_reward)}` Vàng"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"💀 **{loser.display_name}** thất bại.\n"
            f"{l_badge} `[{l_label}]` — ĐĐB: `{result.loser_dtb_after}` "
            f"(`{result.loser_delta}`)"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "-# Kết quả PvP tính tự động dựa trên lực kéo cần câu, cấp độ và "
            "ĐĐB hiện tại của cả 2 bên — càng mạnh, tỉ lệ thắng càng cao "
            "(không phải chắc thắng tuyệt đối)."
        ))
    view.add_item(container)
    return view


class PvPChallengeView(discord.ui.LayoutView):
    """Lời mời thách đấu trực tiếp ("/pvp thách_đấu" hoặc "/pvp giao_hữu")
    — người được mời bấm nút Chấp Nhận/Từ Chối. Chỉ đúng người được mời
    (và người mời, để tự hủy) mới thao tác được nút.
    `friendly=True` -> trận giao hữu (không tính ĐĐB/Vàng/lượt, xem
    run_pvp_battle/build_pvp_result_view)."""

    def __init__(self, challenger: discord.abc.User, opponent: discord.abc.User, friendly: bool = False):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.opponent = opponent
        self.friendly = friendly
        self._render()

    def _render(self) -> None:
        self.clear_items()
        container = discord.ui.Container(
            accent_colour=discord.Colour.teal() if self.friendly else discord.Colour.orange()
        )
        title = "🤝 Lời Mời Giao Hữu PvP" if self.friendly else "⚔️ Lời Thách Đấu PvP"
        verb = "rủ giao hữu" if self.friendly else "thách đấu"
        container.add_item(discord.ui.TextDisplay(f"# {title}"))
        container.add_item(discord.ui.TextDisplay(
            f"**{self.challenger.display_name}** {verb} **{self.opponent.display_name}**!\n"
            f"`{self.opponent.display_name}` có 120 giây để phản hồi."
            + ("\n-# Trận giao hữu: không tính ĐĐB, không thưởng, không tốn lượt PvP." if self.friendly else "")
        ))
        row = discord.ui.ActionRow()
        accept_btn = discord.ui.Button(label="Chấp Nhận", style=discord.ButtonStyle.success, emoji="⚔️")
        decline_btn = discord.ui.Button(label="Từ Chối", style=discord.ButtonStyle.danger, emoji="🚫")
        accept_btn.callback = self._on_accept
        decline_btn.callback = self._on_decline
        row.add_item(accept_btn)
        row.add_item(decline_btn)
        container.add_item(row)
        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction, allowed: set[int]) -> bool:
        if interaction.user.id not in allowed:
            await interaction.response.send_message(
                "⚠️ Lời mời này không dành cho bạn!", ephemeral=True,
            )
            return False
        return True

    async def _on_accept(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction, {self.opponent.id}):
            return
        await interaction.response.defer()

        if not self.friendly:
            data_c = await aget_user_data(self.challenger.id)
            data_o = await aget_user_data(self.opponent.id)
            if pvp_matches_left(data_c) <= 0:
                await interaction.followup.send(
                    f"⚠️ **{self.challenger.display_name}** đã hết lượt PvP hôm nay "
                    f"(`{PVP_DAILY_MATCH_LIMIT}` trận/ngày), không thể thi đấu.",
                )
                return
            if pvp_matches_left(data_o) <= 0:
                await interaction.followup.send(
                    f"⚠️ Bạn đã hết lượt PvP hôm nay (`{PVP_DAILY_MATCH_LIMIT}` trận/ngày)!",
                    ephemeral=True,
                )
                return

        self.clear_items()
        result, _data_c, _data_o = await run_pvp_battle(self.challenger, self.opponent, friendly=self.friendly)
        result_view = build_pvp_result_view(self.challenger, self.opponent, result, friendly=self.friendly)
        await interaction.edit_original_response(view=result_view)
        self.stop()

    async def _on_decline(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction, {self.opponent.id, self.challenger.id}):
            return
        await interaction.response.defer()
        container = discord.ui.Container(accent_colour=discord.Colour.greyple())
        container.add_item(discord.ui.TextDisplay(
            f"🚫 **{self.opponent.display_name}** đã từ chối lời mời của "
            f"**{self.challenger.display_name}**."
        ))
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        await interaction.edit_original_response(view=view)
        self.stop()

    async def on_timeout(self) -> None:
        try:
            container = discord.ui.Container(accent_colour=discord.Colour.greyple())
            container.add_item(discord.ui.TextDisplay(
                f"⏱️ Lời mời của **{self.challenger.display_name}** đã hết hạn "
                f"(không phản hồi trong 120s)."
            ))
            view = discord.ui.LayoutView(timeout=None)
            view.add_item(container)
            await self.message.edit(view=view)
        except (discord.HTTPException, AttributeError):
            pass


def build_pvp_menu_view(bot: commands.Bot) -> discord.ui.LayoutView:
    """Khung menu "/pvp ngẫu_nhiên" — nút "Ghép Ngẫu Nhiên" để vào hàng đợi
    thật (xem _pvp_queue_button_cb). Thách đấu đích danh/giao hữu dùng
    subcommand riêng "/pvp thách_đấu" và "/pvp giao_hữu" (cần tham số
    người chơi nên không gộp vào đây)."""
    view = discord.ui.LayoutView(timeout=180)
    container = discord.ui.Container(accent_colour=discord.Colour.dark_red())
    container.add_item(discord.ui.TextDisplay("# ⚔️ Đấu Trường PvP"))
    container.add_item(discord.ui.TextDisplay(
        "Đang ghép bạn với 1 đối thủ ngẫu nhiên. Muốn rủ đích danh 1 người? "
        "Dùng `/pvp thách_đấu` (tính ĐĐB) hoặc `/pvp giao_hữu` (chỉ chơi vui, "
        "không tính ĐĐB)."
    ))
    row = discord.ui.ActionRow()
    btn = discord.ui.Button(label="Ghép Ngẫu Nhiên", style=discord.ButtonStyle.danger, emoji="🎲")
    btn.callback = lambda interaction: _pvp_queue_button_cb(interaction, bot)
    row.add_item(btn)
    container.add_item(row)
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"-# Tối đa `{PVP_DAILY_MATCH_LIMIT}` trận PvP xếp hạng/ngày (reset lúc "
        f"00:00 UTC). Kết quả tự tính theo lực kéo cần, cấp độ và ĐĐB hiện tại."
    ))
    view.add_item(container)
    return view


async def _pvp_queue_button_cb(interaction: discord.Interaction, bot: commands.Bot) -> None:
    try:
        await _pvp_queue_button_cb_inner(interaction, bot)
    except Exception:
        # Bọc toàn bộ luồng ghép trận: nếu có lỗi bất ngờ (Firebase timeout,
        # user rời server giữa chừng...) mà không catch, Discord client sẽ
        # hiện nút bấm "quay/suy nghĩ mãi" rồi báo lỗi mơ hồ — báo rõ cho
        # người chơi thay vì im lặng treo, đồng thời KHÔNG che giấu lỗi
        # thật (vẫn re-raise để log/console thấy được nếu bot có logging).
        try:
            await interaction.followup.send(
                "⚠️ Có lỗi xảy ra khi ghép trận PvP, vui lòng thử lại!", ephemeral=True,
            )
        except discord.HTTPException:
            pass
        raise


async def _pvp_queue_button_cb_inner(interaction: discord.Interaction, bot: commands.Bot) -> None:
    await interaction.response.defer()

    data = await aget_user_data(interaction.user.id)
    if pvp_matches_left(data) <= 0:
        await interaction.followup.send(
            f"⚠️ Bạn đã hết lượt PvP hôm nay (`{PVP_DAILY_MATCH_LIMIT}` trận/ngày), "
            f"quay lại vào ngày mai nhé!",
            ephemeral=True,
        )
        return

    waiting_container = discord.ui.Container(accent_colour=discord.Colour.dark_red())
    waiting_container.add_item(discord.ui.TextDisplay(
        f"🔎 **{interaction.user.display_name}** đang tìm đối thủ ngẫu nhiên...\n"
        f"-# Hàng đợi hết hạn sau 180s nếu không ai ghép được."
    ))
    waiting_view = discord.ui.LayoutView(timeout=None)
    waiting_view.add_item(waiting_container)
    msg = await interaction.followup.send(view=waiting_view, wait=True)

    match = await apvp_queue_join_or_match(interaction.user.id, interaction.channel_id, msg.id)

    if match["status"] == "waiting":
        # Không có ai chờ sẵn — bạn giờ là người chờ. Tin nhắn `msg` (đã
        # lưu message_id vào Firebase ở trên) sẽ được người ghép SAU tự
        # fetch + sửa lại thành kết quả trận đấu khi họ bấm nút kế tiếp
        # (xem nhánh "matched" bên dưới) — không cần làm gì thêm ở đây.
        return

    opponent_id = match["opponent_id"]
    opponent = bot.get_user(opponent_id)
    if opponent is None:
        try:
            opponent = await bot.fetch_user(opponent_id)
        except discord.HTTPException:
            opponent = None
    if opponent is None:
        # Đối thủ ghép được nhưng không tra được user Discord (hiếm, vd bị
        # xóa tài khoản) -> hủy trận, trả lại lượt bằng cách không trừ gì
        # (pvp_consume_match chưa chạy) và báo lỗi.
        err_container = discord.ui.Container(accent_colour=discord.Colour.greyple())
        err_container.add_item(discord.ui.TextDisplay(
            "⚠️ Không thể xác định đối thủ đã ghép — vui lòng thử lại."
        ))
        err_view = discord.ui.LayoutView(timeout=None)
        err_view.add_item(err_container)
        await msg.edit(view=err_view)
        return

    opp_data = await aget_user_data(opponent_id)
    if pvp_matches_left(opp_data) <= 0:
        # Đối thủ ghép được nhưng đã hết lượt hôm nay giữa lúc bạn đang
        # chờ -> hủy trận, không trừ lượt của bạn.
        err_container = discord.ui.Container(accent_colour=discord.Colour.greyple())
        err_container.add_item(discord.ui.TextDisplay(
            f"⚠️ **{opponent.display_name}** vừa hết lượt PvP hôm nay — không thể "
            f"ghép trận. Thử lại sau nhé!"
        ))
        err_view = discord.ui.LayoutView(timeout=None)
        err_view.add_item(err_container)
        await msg.edit(view=err_view)
        return

    result, _data_you, _data_opp = await run_pvp_battle(interaction.user, opponent)
    result_view = build_pvp_result_view(interaction.user, opponent, result)
    # Sửa tin nhắn của CHÍNH BẠN (người vừa ghép, tới sau).
    await msg.edit(view=result_view)

    # Sửa NỐT tin nhắn "đang tìm đối thủ..." của ĐỐI THỦ (người đã chờ sẵn
    # trước đó, tới trước) thành cùng 1 kết quả — đây là bản sửa quan trọng
    # khiến người chờ đầu tiên KHÔNG còn bị kẹt mãi ở màn hình "đang tìm
    # đối thủ..." như trước (bug gốc). Dùng channel_id/message_id lưu lại
    # lúc họ vào hàng đợi, không phụ thuộc followup token đã hết hạn.
    opp_channel_id = match.get("opponent_channel_id")
    opp_message_id = match.get("opponent_message_id")
    if opp_channel_id and opp_message_id:
        try:
            opp_channel = bot.get_channel(opp_channel_id) or await bot.fetch_channel(opp_channel_id)
            opp_msg = await opp_channel.fetch_message(opp_message_id)
            await opp_msg.edit(view=build_pvp_result_view(opponent, interaction.user, result))
        except (discord.HTTPException, discord.NotFound, discord.Forbidden):
            # Không sửa được tin nhắn cũ của đối thủ (vd bị xóa, bot mất
            # quyền) -> vẫn gửi thêm 1 bản công khai trong kênh bên dưới để
            # họ không bị bỏ sót kết quả hoàn toàn.
            pass

    # Thông báo thêm công khai trong kênh (mention cả 2 bên) — đảm bảo dù
    # sửa tin nhắn cũ có thất bại thì cả 2 vẫn thấy được kết quả ở đâu đó.
    channel = interaction.channel
    if channel is not None:
        try:
            await channel.send(
                content=f"<@{interaction.user.id}> <@{opponent_id}>",
                view=build_pvp_result_view(interaction.user, opponent, result),
            )
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
class CauCaVanCan(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weather_loop.start()

    def cog_unload(self) -> None:
        self.weather_loop.cancel()

    # -- Thời tiết: tự random 1 lần MỖI GIỜ, lưu Firebase + thông báo trong
    # đúng kênh WEATHER_CHANNEL_ID. tasks.loop chạy ngay lần đầu khi start()
    # (sau khi bot sẵn sàng nhờ before_loop) rồi lặp lại mỗi 3600s sau đó,
    # nên tự đáp ứng đúng yêu cầu "mỗi 1 tiếng có 1 weather random".
    @tasks.loop(hours=1)
    async def weather_loop(self) -> None:
        weather = roll_weather()
        now = time.time()
        expires_at = now + 3600
        await aset_current_weather({
            "key": weather.key, "name": weather.name, "emoji": weather.emoji,
            "started_at": now, "expires_at": expires_at,
        })

        channel = self.bot.get_channel(WEATHER_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(WEATHER_CHANNEL_ID)
            except discord.HTTPException:
                channel = None
        if channel is not None:
            view = build_weather_view(weather, expires_at)
            try:
                await channel.send(view=view)
            except discord.HTTPException:
                pass

    @weather_loop.before_loop
    async def _before_weather_loop(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="thời_tiết", description="Xem thời tiết câu cá hiện tại")
    async def thoi_tiet(self, interaction: discord.Interaction) -> None:
        # Chỉ dùng được đúng 1 kênh thời tiết — dùng ở kênh khác đều từ chối.
        if interaction.channel_id != WEATHER_CHANNEL_ID:
            await interaction.response.send_message(
                f"⚠️ Lệnh này chỉ dùng được ở <#{WEATHER_CHANNEL_ID}>!",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        raw = await aget_current_weather()
        if raw is None:
            # Chưa có thời tiết nào được random (vd bot vừa deploy lần đầu,
            # weather_loop chưa kịp chạy) -> random ngay 1 cái để không trống.
            weather = roll_weather()
            now = time.time()
            expires_at = now + 3600
            await aset_current_weather({
                "key": weather.key, "name": weather.name, "emoji": weather.emoji,
                "started_at": now, "expires_at": expires_at,
            })
        else:
            weather = WEATHER_BY_KEY.get(raw.get("key"), WEATHERS[0])
            expires_at = raw.get("expires_at")
        await interaction.followup.send(view=build_weather_view(weather, expires_at))

    @app_commands.command(name="câu_cá", description="Thả cần câu cá!")
    async def cau_ca(self, interaction: discord.Interaction) -> None:
        await self._do_cau_ca(interaction)

    async def _do_cau_ca(self, interaction: discord.Interaction) -> None:
        """Thân lệnh /câu_cá thật sự — tách riêng thành method để nút
        "🎣 Câu Tiếp" (gắn ở cuối khung kết quả, xem build_success_view/
        build_fail_view) có thể gọi lại y hệt, không cần user gõ lại lệnh.
        Nút "Câu Tiếp" gửi tới đây 1 interaction (component) MỚI, hoạt động
        y hệt 1 lượt /câu_cá bình thường — vẫn tôn trọng đầy đủ cooldown/
        thể lực như thường lệ."""
        # defer() ngay lập tức trước khi đụng tới Firebase — tránh lỗi
        # "Ứng dụng không phản hồi" nếu việc đọc/ghi DB mất hơn 3 giây.
        await interaction.response.defer()

        data = await aget_user_data(interaction.user.id)
        data = apply_energy_regen(data)

        now = time.time()
        remaining = CAST_COOLDOWN_SECONDS - (now - data["last_cast"])
        if remaining > 0 and interaction.user.id not in OWNER_IDS:
            await interaction.followup.send(
                f"{E.CLOCK} Cần câu đang hồi chiêu, chờ thêm `{remaining:.1f}s` nữa nhé!",
                ephemeral=True,
            )
            return

        if data.get("energy", 0) <= 0 and interaction.user.id not in OWNER_IDS:
            await interaction.followup.send(
                f"{E.ENERGY} Bạn đã hết năng lượng rồi! Năng lượng tự hồi theo thời gian "
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

        # Thời tiết hiện tại (toàn server) — áp dụng cho suốt ván câu này dù
        # thời tiết có đổi giữa chừng (snapshot tại lúc thả cần).
        weather: Optional[Weather] = None
        weather_raw = await aget_current_weather()
        if weather_raw and weather_raw.get("expires_at", 0) > now:
            weather = WEATHER_BY_KEY.get(weather_raw.get("key"))
        if weather:
            luck_bonus += weather.luck_delta

        fish = roll_catch(rod, map_key=data.get("current_map"), weather=weather)
        is_boss = fish.key in BOSS_FISH_KEYS
        is_junk = is_junk_fish(fish.key)
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
                "map_item_gained": None,
            }

            if success is True:
                # Rác vẫn được thêm vào kho (bán được ve chai lấy chút Vàng
                # lẻ) nhưng KHÔNG cộng điểm/EXP/cân nặng cộng dồn — chỉ cá
                # thật mới tính vào tiến trình (bảng xếp hạng, lên cấp...).
                inv = fresh.get("inventory", {})
                inv[fish.key] = inv.get(fish.key, 0) + 1
                fresh["inventory"] = inv

                if not is_junk:
                    fresh["score"] = fresh.get("score", 0) + 10
                    if fish.weight_can:
                        fresh["total_weight_can"] = fresh.get("total_weight_can", 0.0) + fish.weight_can

                    # Câu được 1 trong các cá boss của Map 6 (Hố Đen) ->
                    # thưởng "Bản Đồ Vực Sâu Hà La", vật phẩm mở khóa Map 7.
                    if is_boss and fish.map_key == MAP6_KEY:
                        owned_items = set(fresh.get("map_items", []) or [])
                        if MAP7_ITEM_KEY not in owned_items:
                            owned_items.add(MAP7_ITEM_KEY)
                            fresh["map_items"] = list(owned_items)
                            result["map_item_gained"] = MAP7_ITEM_LABEL

                    exp_gain = exp_for_fish(fish)
                    fresh, leveled_up, _levels_gained = add_exp(fresh, exp_gain)
                    # Lên cấp KHÔNG hồi đầy năng lượng nữa — chỉ tăng
                    # max_energy (qua max_energy_for_level), năng lượng hiện
                    # tại giữ nguyên (clamp lại nếu max mới nhỏ hơn, dù bình
                    # thường max tăng theo cấp nên hiếm khi xảy ra).
                    fresh["energy"] = min(fresh.get("energy", 0), max_energy_for_level(fresh["level"]))

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

        async def on_continue(continue_interaction: discord.Interaction) -> None:
            await self._do_cau_ca(continue_interaction)

        view = ReelView(
            interaction.user, rod, fish, luck_bonus, rank_label, rank_badge,
            bait_name, bait_time_left, on_finish,
            is_boss=is_boss, energy=energy, max_energy=max_energy, skills=skills,
            weather=weather, on_continue=on_continue,
        )
        view.message = await interaction.followup.send(view=view, wait=True)

    @app_commands.command(name="chọn_map", description="Chọn khu vực câu cá")
    async def chon_map(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await MapSelectView.create(user_id=interaction.user.id)
        await interaction.followup.send(view=view)

    @app_commands.command(
        name="bảng_xếp_hạng",
        description="Bảng xếp hạng câu cá — cân nặng cá đã câu & Vàng đang có",
    )
    async def bang_xep_hang(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = await LeaderboardView.create(self.bot, interaction.guild)
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

    @app_commands.command(name="thông-tin", description="Xem thông tin nhân vật (Vàng, Cấp, EXP...) — mọi người đều xem được")
    async def thong_tin(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
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
        pvp_label, pvp_badge = pvp_rank_for_dtb(data.get("dtb", 1000))
        container.add_item(discord.ui.TextDisplay(
            f"## 👛 Thông Tin của {interaction.user.display_name}\n"
            f"{rank_badge} `[{rank_label}]` — Điểm: `{data['score']}`"
            + (f"\n{aura[1]} `[{aura[0]}]`" if (aura := aura_for_level(level)) else "")
            + f"\n{pvp_badge} `[{pvp_label}]` — ĐĐB: `{data.get('dtb', 1000)}` "
              f"(`{data.get('pvp_wins', 0)}`T/`{data.get('pvp_losses', 0)}`B)"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"{E.GOLD} **Vàng:** `{fmt_vang(data['vang'])}`\n"
            f"{E.ROD} **Cần đang dùng:** {rod.emoji} `{rod.name}`"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"<:xp:1543460237732876369> **Cấp:** `{level}` — EXP: `{exp}/{exp_needed}`\n"
            f"{make_bar(exp / exp_needed if exp_needed else 0)}\n"
            f"{E.ENERGY} **Năng lượng:** `{energy}/{max_energy}`\n"
            f"{make_bar(energy / max_energy if max_energy else 0)}"
        ))
        container.add_item(discord.ui.Separator())
        equipped = equipped_skill_objects(data)
        skill_lines = " · ".join(
            f"Ô{i + 1}: {s.emoji} {s.name}" if s else f"Ô{i + 1}: —"
            for i, s in enumerate(equipped)
        )
        container.add_item(discord.ui.TextDisplay(f"🧩 **Kỹ năng đang trang bị:** {skill_lines}"))
        view.add_item(container)
        await interaction.followup.send(view=view)

    # -- PvP: gộp thành 1 nhóm lệnh "/pvp <subcommand>" --
    # LƯU Ý QUAN TRỌNG: tên THAM SỐ (không phải tên lệnh) của app_commands
    # PHẢI là ASCII (a-z0-9_) — Discord từ chối đăng ký lệnh có tham số
    # chứa ký tự có dấu tiếng Việt (đây là lý do "/pvp_thách_đấu" bản cũ
    # với tham số "đối_thủ"/"người_chơi" không sync/không dùng được). Tên
    # THAM SỐ giữ ASCII (doi_thu, nguoi_choi) và hiển thị tiếng Việt có dấu
    # qua @app_commands.rename — giống pattern "code/vang/can_cau..." đã
    # dùng ổn định ở lệnh /tạo-code bên dưới.
    pvp_group = app_commands.Group(name="pvp", description="Đấu trường PvP")

    @pvp_group.command(name="ngẫu_nhiên", description="Ghép ngẫu nhiên với người khác đang chờ (tính ĐĐB)")
    async def pvp_ngau_nhien(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        data = await aget_user_data(interaction.user.id)
        left = pvp_matches_left(data)
        if left <= 0:
            await interaction.followup.send(
                f"⚠️ Bạn đã hết lượt PvP hôm nay (`{PVP_DAILY_MATCH_LIMIT}` trận/ngày), "
                f"quay lại vào ngày mai nhé!",
                ephemeral=True,
            )
            return
        await interaction.followup.send(view=build_pvp_menu_view(self.bot))

    @pvp_group.command(name="thách_đấu", description="Rủ đích danh 1 người chơi vào trận PvP xếp hạng (tính ĐĐB)")
    @app_commands.describe(doi_thu="Người chơi bạn muốn thách đấu")
    @app_commands.rename(doi_thu="đối_thủ")
    async def pvp_thach_dau(self, interaction: discord.Interaction, doi_thu: discord.Member) -> None:
        if doi_thu.bot:
            await interaction.response.send_message("⚠️ Không thể thách đấu bot!", ephemeral=True)
            return
        if doi_thu.id == interaction.user.id:
            await interaction.response.send_message("⚠️ Không thể tự thách đấu chính mình!", ephemeral=True)
            return

        await interaction.response.defer()
        data = await aget_user_data(interaction.user.id)
        if pvp_matches_left(data) <= 0:
            await interaction.followup.send(
                f"⚠️ Bạn đã hết lượt PvP hôm nay (`{PVP_DAILY_MATCH_LIMIT}` trận/ngày)!",
                ephemeral=True,
            )
            return
        opp_data = await aget_user_data(doi_thu.id)
        if pvp_matches_left(opp_data) <= 0:
            await interaction.followup.send(
                f"⚠️ **{doi_thu.display_name}** đã hết lượt PvP hôm nay, thử người khác nhé!",
                ephemeral=True,
            )
            return

        view = PvPChallengeView(interaction.user, doi_thu, friendly=False)
        view.message = await interaction.followup.send(
            content=f"<@{doi_thu.id}>", view=view, wait=True,
        )

    @pvp_group.command(name="giao_hữu", description="Rủ đấu giao hữu cho vui — không tính ĐĐB, không thưởng, không tốn lượt")
    @app_commands.describe(doi_thu="Người chơi bạn muốn rủ giao hữu")
    @app_commands.rename(doi_thu="đối_thủ")
    async def pvp_giao_huu(self, interaction: discord.Interaction, doi_thu: discord.Member) -> None:
        if doi_thu.bot:
            await interaction.response.send_message("⚠️ Không thể giao hữu với bot!", ephemeral=True)
            return
        if doi_thu.id == interaction.user.id:
            await interaction.response.send_message("⚠️ Không thể tự giao hữu với chính mình!", ephemeral=True)
            return

        await interaction.response.defer()
        view = PvPChallengeView(interaction.user, doi_thu, friendly=True)
        view.message = await interaction.followup.send(
            content=f"<@{doi_thu.id}>", view=view, wait=True,
        )

    @pvp_group.command(name="hạng", description="Xem hạng Điểm Đấu Bậc (ĐĐB) của bạn hoặc người khác")
    @app_commands.describe(nguoi_choi="Bỏ trống để xem hạng của chính bạn")
    @app_commands.rename(nguoi_choi="người_chơi")
    async def pvp_hang(self, interaction: discord.Interaction, nguoi_choi: Optional[discord.Member] = None) -> None:
        await interaction.response.defer()
        target = nguoi_choi or interaction.user
        data = await aget_user_data(target.id)
        dtb = data.get("dtb", 1000)
        label, badge = pvp_rank_for_dtb(dtb)
        left = pvp_matches_left(data)

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=discord.Colour.dark_red())
        container.add_item(discord.ui.TextDisplay(f"# ⚔️ Hạng PvP của {target.display_name}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"{badge} `[{label}]` — ĐĐB: `{dtb}`\n"
            f"🏆 Thắng: `{data.get('pvp_wins', 0)}` — 💀 Thua: `{data.get('pvp_losses', 0)}`\n"
            f"🎯 Lượt PvP xếp hạng còn lại hôm nay: `{left}/{PVP_DAILY_MATCH_LIMIT}`"
        ))
        view.add_item(container)
        await interaction.followup.send(view=view)

    # -- Admin: tạo code đổi thưởng (Vàng / cần câu / kỹ năng / mồi câu) --
    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in OWNER_IDS:
            return True
        member = interaction.user
        return isinstance(member, discord.Member) and member.guild_permissions.administrator

    @app_commands.command(
        name="tạo-code",
        description="[Admin] Tạo code đổi thưởng (Vàng / cần câu / kỹ năng / mồi câu)",
    )
    @app_commands.describe(
        code="Mã code (để trống sẽ tự sinh ngẫu nhiên 8 ký tự)",
        vang="Số Vàng thưởng khi đổi code",
        can_cau="Cần câu tặng kèm (mở khóa, chưa tự trang bị)",
        ky_nang="Kỹ năng tặng kèm (mở khóa, chưa tự trang bị)",
        moi_cau="Mồi câu tặng kèm (dùng ngay khi đổi code)",
        so_lan_dung="Số lượt đổi tối đa cho cả server (để trống = không giới hạn)",
        thoi_han_ngay="Hạn dùng code, đơn vị NGÀY (để trống = random 1-2 ngày)",
    )
    async def createcode(
        self,
        interaction: discord.Interaction,
        code: Optional[str] = None,
        vang: Optional[int] = None,
        can_cau: Optional[str] = None,
        ky_nang: Optional[str] = None,
        moi_cau: Optional[str] = None,
        so_lan_dung: Optional[int] = None,
        thoi_han_ngay: Optional[float] = None,
    ) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "⛔ Chỉ Admin mới dùng được lệnh này!", ephemeral=True,
            )
            return

        if can_cau and can_cau not in RODS:
            await interaction.response.send_message(
                f"⚠️ Không tìm thấy cần câu với key `{can_cau}` (gõ tên để bot gợi ý)!",
                ephemeral=True,
            )
            return
        if ky_nang and ky_nang not in SKILLS:
            await interaction.response.send_message(
                f"⚠️ Không tìm thấy kỹ năng với key `{ky_nang}` (gõ tên để bot gợi ý)!",
                ephemeral=True,
            )
            return
        if moi_cau and moi_cau not in BAITS:
            await interaction.response.send_message(
                f"⚠️ Không tìm thấy mồi câu với key `{moi_cau}` (gõ tên để bot gợi ý)!",
                ephemeral=True,
            )
            return
        if so_lan_dung is not None and so_lan_dung <= 0:
            await interaction.response.send_message(
                "⚠️ Số lượt dùng phải lớn hơn 0 (để trống nếu muốn không giới hạn)!",
                ephemeral=True,
            )
            return
        if thoi_han_ngay is not None and thoi_han_ngay <= 0:
            await interaction.response.send_message(
                "⚠️ Thời hạn code phải lớn hơn 0 ngày (để trống để bot tự random 1-2 ngày)!",
                ephemeral=True,
            )
            return

        reward: dict = {}
        if vang:
            reward["vang"] = vang
        if can_cau:
            reward["rod"] = can_cau
        if ky_nang:
            reward["skill"] = ky_nang
        if moi_cau:
            reward["bait"] = moi_cau

        if not reward:
            await interaction.response.send_message(
                "⚠️ Phải cho ít nhất 1 phần thưởng: `vang`, `can_cau`, `ky_nang` hoặc `moi_cau`!",
                ephemeral=True,
            )
            return

        final_code = (code or "").strip().upper()
        if not final_code:
            final_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

        existing = await aget_code(final_code)
        if existing:
            await interaction.response.send_message(
                f"⚠️ Code `{final_code}` đã tồn tại, chọn mã khác hoặc để trống để bot tự sinh!",
                ephemeral=True,
            )
            return

        # Mỗi code PHẢI có hạn dùng — nếu admin không tự nhập số ngày, random
        # đều trong khoảng 1-2 ngày (xem firebase_db.DEFAULT_CODE_EXPIRY_*).
        expiry_days = thoi_han_ngay if thoi_han_ngay is not None else random.uniform(
            DEFAULT_CODE_EXPIRY_MIN_DAYS, DEFAULT_CODE_EXPIRY_MAX_DAYS,
        )
        expires_at = time.time() + expiry_days * 86400

        await acreate_code(final_code, reward, so_lan_dung, interaction.user.id, expires_at)

        reward_lines = []
        if "vang" in reward:
            reward_lines.append(f"{E.GOLD} `{fmt_vang(reward['vang'])}` Vàng")
        if "rod" in reward:
            r = RODS[reward["rod"]]
            reward_lines.append(f"{E.ROD} {r.emoji} {r.name}")
        if "skill" in reward:
            s = SKILLS[reward["skill"]]
            reward_lines.append(f"🧩 {s.emoji} {s.name}")
        if "bait" in reward:
            b = BAITS[reward["bait"]]
            reward_lines.append(f"{E.BAIT} {b.name}")

        view = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=discord.Colour.green())
        container.add_item(discord.ui.TextDisplay(
            f"## ✅ Đã tạo code `{final_code}`\n"
            + "\n".join(f"- {l}" for l in reward_lines)
            + f"\n\n**Số lượt đổi:** `{so_lan_dung if so_lan_dung else 'Không giới hạn'}`\n"
            f"**Hạn dùng:** `{format_time_left(expiry_days * 86400)}` "
            f"(hết hạn lúc <t:{int(expires_at)}:f>)\n"
            f"Người chơi bấm nút **🎁 Nhập Code** trong `/đồ_câu_lão_bát` để đổi."
        ))
        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)

    @createcode.autocomplete("can_cau")
    async def _createcode_rod_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        current_l = current.lower()
        options = [
            r for r in (ROD_LIST + LIMITED_ROD_LIST)
            if current_l in r.name.lower() or current_l in r.key.lower()
        ]
        return [app_commands.Choice(name=f"{r.emoji} {r.name}", value=r.key) for r in options[:25]]

    @createcode.autocomplete("ky_nang")
    async def _createcode_skill_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        current_l = current.lower()
        options = [
            s for s in SKILL_SHOP
            if current_l in s.name.lower() or current_l in s.key.lower()
        ]
        return [app_commands.Choice(name=f"{s.emoji} {s.name}", value=s.key) for s in options[:25]]

    @createcode.autocomplete("moi_cau")
    async def _createcode_bait_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        current_l = current.lower()
        options = [
            b for b in BAIT_SHOP
            if current_l in b.name.lower() or current_l in b.key.lower()
        ]
        return [app_commands.Choice(name=b.name, value=b.key) for b in options[:25]]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CauCaVanCan(bot))
