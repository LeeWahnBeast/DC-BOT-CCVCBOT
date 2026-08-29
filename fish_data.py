"""
fish_data.py
============
Dữ liệu các loài cá, chia theo cấp bậc (tier), lấy từ shop "Bán Cá" bạn đã
chụp gửi (Cấp Mười Cân -> Cấp Triệu Cân). Mỗi loài cá có tên, khối lượng
hiển thị (chỉ để show, không random) và đơn giá bán (Vàng/con).

GHI CHÚ QUAN TRỌNG
------------------
- 4 cấp cuối trong menu shop gốc (Ngàn Vạn Cân, Sơn Hải, Cá Giới Hạn,
  Cá Đặc Biệt) đều đang bị khóa (hình cá tô đen, chưa lộ tên/giá) trong
  toàn bộ ảnh bạn gửi -> chưa có dữ liệu thật để đưa vào. Đã để sẵn tier
  rỗng bên dưới, bạn gửi thêm ảnh khi các cấp đó mở khóa là điền được ngay
  (đúng format `(tên, khối_lượng_hiển_thị, đơn_giá_vàng)`).
- "SL" trong ảnh là số lượng cá NGƯỜI CHƠI đang có trong kho, không phải
  thuộc tính loài cá nên không đưa vào đây.
- Vài con bị cắt hình / giá bị che (vd "Cá Trai Đá Biển Dị", "Cá Hổ Biển
  Dị", "Vua Cá Mập Xanh - 4 Triệu Cân" ở cuối ảnh Cấp Triệu Cân) nên
  không đưa vào để tránh sai giá — thêm sau khi có ảnh rõ hơn.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "ca"


@dataclass(frozen=True)
class FishSpecies:
    key: str
    name: str
    weight_label: str   # hiển thị, vd "500.000 Cân" — KHÔNG random, cố định theo loài
    price: int           # Đơn giá bán, đơn vị Vàng / con
    tier_key: str


@dataclass(frozen=True)
class FishTier:
    key: str
    label: str            # tên hiển thị giống menu bên trái trong game
    required_pull: int     # Lực kéo tối thiểu của cần câu để có thể ra cá tier này


# ---------------------------------------------------------------------------
# Thứ tự các cấp — required_pull tăng dần theo lực kéo cần câu thực tế
# (xem rod_data.py): cần khởi điểm ~25 lực kéo, cần cao nhất 3000.
# ---------------------------------------------------------------------------
TIERS: list[FishTier] = [
    FishTier("muoi_can", "Cấp Mười Cân", 0),
    FishTier("tram_can", "Cấp Trăm Cân", 60),
    FishTier("ngan_can", "Cấp Ngàn Cân", 150),
    FishTier("van_can", "Vạn Cân", 300),
    FishTier("muoi_van_can", "Mười Vạn Cân", 500),
    FishTier("trieu_can", "Cấp Triệu Cân", 700),
    # Chưa có dữ liệu thật (vẫn khóa/tô đen trong mọi ảnh đã gửi) — điền
    # theo cùng format (tên, khối_lượng_hiển_thị, đơn_giá) khi có ảnh rõ.
    FishTier("ngan_van_can", "Ngàn Vạn Cân", 1200),
    FishTier("son_hai", "Sơn Hải", 2000),
    FishTier("ca_gioi_han", "Cá Giới Hạn", 2500),
    FishTier("ca_dac_biet", "Cá Đặc Biệt", 3000),
]
TIER_BY_KEY: dict[str, FishTier] = {t.key: t for t in TIERS}

# (tên, khối_lượng_hiển_thị, đơn_giá_vàng) theo từng tier — trích từ ảnh gốc.
_RAW_FISH: dict[str, list[tuple[str, str, int]]] = {
    "muoi_can": [
        ("Cá Thanh Hoa", "5 cân", 15_000),
        ("Cá Vàng", "10 cân", 20_000),
        ("Cá Chép Nhỏ", "10 cân", 25_000),
        ("Cá Liên Trắng", "20 cân", 30_000),
        ("Cá Trê", "30 cân", 40_000),
        ("Cá Diếc", "40 cân", 50_000),
        ("Cá Nheo Biến Dị", "80 cân", 100_000),
    ],
    "tram_can": [
        ("Cá Chép Đỏ Đột Biến", "100 cân", 150_000),
        ("Cá Chép Xanh Biến Dị", "100 cân", 150_000),
        ("Cá Liên Dung Biến Dị", "180 cân", 200_000),
        ("La Phi Khổng Lồ", "300 cân", 500_000),
        ("Tổ Ngư Hoàng Kim", "400 cân", 800_000),
        ("Vương Cá Chép", "500 cân", 1_000_000),
        ("Đối Thiên Kiều", "500 cân", 1_000_000),
    ],
    "ngan_can": [
        ("Bạch Điêu Ngàn Cân", "1.000 cân", 1_200_000),
        ("Cá Thanh Râu Vàng", "1.200 cân", 1_500_000),
        ("Cá Cờ Vây Đen", "1.400 cân", 2_000_000),
        ("Cá Cờ Vây Đỏ", "1.600 cân", 2_500_000),
        ("Cá Trắng Vây Vàng", "1.800 cân", 2_800_000),
        ("Cá Cờ Vây Xanh", "2.500 cân", 3_000_000),
        ("La Phi Đầu Rồng (Nhỏ)", "2.500 cân", 2_000_000),
        ("Vua Cá Cờ", "5.000 cân", 4_500_000),
        ("La Phi Đầu Rồng (Lớn)", "6.000 cân", 5_000_000),
        ("Quy Ngư Đột Biến", "5.000 cân", 4_000_000),
        ("Thạch Bản Đột Biến", "5.000 cân", 4_200_000),
        ("Bá Ngư Đột Biến", "5.000 cân", 4_500_000),
        ("Giao Ngư Đột Biến", "6.000 cân", 4_800_000),
        ("Xước Ngư Đột Biến", "7.000 cân", 5_000_000),
        ("Điêu Ngư Đột Biến", "7.000 cân", 5_200_000),
        ("Xích Nhãn", "8.000 cân", 6_500_000),
    ],
    "van_can": [
        ("Cá Biển Đột Biến", "1 vạn cân", 8_500_000),
        ("Giao Ngư Long", "10.000 cân", 8_000_000),
        ("Cá Mập Biến Dị", "1 vạn cân", 9_500_000),
        ("Tam Đương Gia Bá Địa Hổ", "10.000 cân", 7_800_000),
        ("Nhị Đương Gia Bá Địa Hổ", "10.000 cân", 8_000_000),
        ("Đại Đương Gia Bá Địa Hổ", "10.000 cân", 8_200_000),
        ("Cá Chép Nuốt Trời", "2 vạn cân", 12_000_000),
        ("Liên Ưng Lôi Điện", "30.000 cân", 15_000_000),
        ("Thanh Ngư Sùng Bạc", "50.000 cân", 17_500_000),
        ("Cá Đầu Chó", "50.000 cân", 18_000_000),
        ("Cá Cờ Đầu Bò", "20.000 cân", 17_000_000),
        ("Song Thổ Lăng Ngư", "30.000 cân", 18_000_000),
        ("Âm·Trúc Thanh Bạch Điêu", "5 vạn cân", 17_000_000),
    ],
    "muoi_van_can": [
        ("Cá Piranha", "100.000 cân", 40_000_000),
        ("Ngư Châu", "—", 200_000_000),
        ("Vua Cá Mập Biển", "10 vạn cân", 30_000_000),
        ("Cá Koi Hình Rồng", "100.000 cân", 30_000_000),
        ("Âm·Cá Mào Gà", "10 vạn cân", 30_000_000),
        ("Âm·Lý Ngư Sừng Đỏ", "15 vạn cân", 35_000_000),
        ("Âm·Cá Lưng Gai", "20 vạn cân", 40_000_000),
        ("Cá Rắn Xương Khổng Lồ", "20 vạn cân", 40_000_000),
        ("Cá Trắm Đen", "400.000 cân", 20_000_000),
        ("Âm·Cá Ăn Thịt", "30 vạn cân", 40_000_000),
        ("Cá Liếc Biến Dị", "500.000 cân", 50_000_000),
        ("Cá Diếc Sừng Khổng Lồ", "500.000 cân", 50_000_000),
        ("Cư Lân Ngư Biến Dị", "500.000 cân", 50_000_000),
        ("Âm·Cá Lưng Xanh Mắt Đỏ", "40 vạn cân", 45_000_000),
        ("Cá Chép Râu Vàng Đỏ", "600.000 cân", 60_000_000),
        ("Cá Chép Râu Vàng Xanh", "600.000 cân", 60_000_000),
        ("Bàng Tỵ Biến Dị", "600.000 cân", 60_000_000),
        ("Bạch Lư Răng Cưa", "600.000 cân", 60_000_000),
        ("Cá Sấu Hoa", "600.000 cân", 70_000_000),
        ("Âm·Thanh Ngư Sừng Trâu", "500.000 cân", 50_000_000),
        ("Thanh Ngư Xích Nhãn", "800.000 cân", 70_000_000),
        ("Liên Ưng Vây Đao", "800.000 cân", 70_000_000),
        ("Hắc Lư Mắt Đỏ", "800.000 cân", 70_000_000),
        ("La Phi Dã Biến Dị", "800.000 cân", 70_000_000),
        ("Quế Ngư Biến Dị", "800.000 cân", 80_000_000),
        ("Đuôi Đỏ", "800.000 cân", 70_000_000),
    ],
    "trieu_can": [
        ("Vua Cá Mập Xanh", "1 triệu cân", 85_000_000),
        ("Cá Mú Vây Dao", "1 triệu cân", 85_000_000),
        ("Cá Voi Đột Biến", "1,2 triệu cân", 95_000_000),
        ("Cá Đèn Biển", "1 triệu cân", 95_000_000),
        ("Anh Phiêu Tuyết", "—", 150_000_000),
        ("Răng Lốt Hóa", "1.500.000 cân", 110_000_000),
        ("Cá Chép Đổi Màu", "1.000.000 cân", 110_000_000),
        ("Cá Koi Hình Rồng (Triệu Cân)", "1 triệu cân", 110_000_000),
        ("Cá Lưỡi Xương Khổng Lồ Amazon", "3 triệu cân", 150_000_000),
        ("Cá Diếp Vân Rồng", "1.000.000 cân", 72_000_000),
        ("Cá Dao Khổng Lồ", "1.000.000 cân", 72_000_000),
        ("Cá Ngừ Độc Bích", "1.000.000 cân", 72_000_000),
        ("Cá Sừng Nâu", "1.000.000 cân", 72_000_000),
        ("Cá Nóc Quái Thú", "—", 230_000_000),
        ("Cá Nóc Lam", "—", 250_000_000),
        ("Thanh Ngư Xoắn", "2 triệu cân", 120_000_000),
        ("Đèn Lồng Khổng Lồ", "5 triệu cân", 170_000_000),
        ("Cá Kiếm Biển Dị", "2 triệu cân", 120_000_000),
        ("Cá Sói Biển Dị", "2 triệu cân", 120_000_000),
        ("Cá Bơn Biển Dị", "2 triệu cân", 120_000_000),
        ("Cá Voi Lưng Gù", "—", 270_000_000),
        ("Cá Koi Hình Rồng Khổng Lồ", "3 triệu cân", 150_000_000),
        ("Cá Chép Rồng Vàng", "3 triệu cân", 150_000_000),
        ("Cá Chép Rồng Bạc", "3 triệu cân", 150_000_000),
        ("Cá Trê Lãnh Thổ", "—", 285_000_000),
        ("Ngân Giáp Cán Ngư", "3 triệu cân", 150_000_000),
        ("Cá Koi May Mắn", "3 triệu cân", 150_000_000),
        ("Xích Giáp Cán Vương", "—", 240_000_000),
        ("Cá Điêu Râu Bạc", "—", 295_000_000),
        ("Vua Cá Diếc Vảy Vàng", "—", 200_000_000),
        ("Lươn Điện Biến Dị", "—", 200_000_000),
        ("Rùa Cá Sấu Trăm", "—", 200_000_000),
    ],
    # Các tier bên dưới để trống — chưa có ảnh mở khóa để lấy tên/giá thật.
    "ngan_van_can": [],
    "son_hai": [],
    "ca_gioi_han": [],
    "ca_dac_biet": [],
}


def _build_fish() -> tuple[list[FishSpecies], dict[str, FishSpecies], dict[str, list[FishSpecies]]]:
    all_fish: list[FishSpecies] = []
    used_keys: set[str] = set()
    by_tier: dict[str, list[FishSpecies]] = {t.key: [] for t in TIERS}

    for tier_key, entries in _RAW_FISH.items():
        for name, weight_label, price in entries:
            base_key = f"{tier_key}_{_slugify(name)}"
            key = base_key
            n = 2
            while key in used_keys:
                key = f"{base_key}_{n}"
                n += 1
            used_keys.add(key)

            fish = FishSpecies(key=key, name=name, weight_label=weight_label,
                                price=price, tier_key=tier_key)
            all_fish.append(fish)
            by_tier[tier_key].append(fish)

    return all_fish, {f.key: f for f in all_fish}, by_tier


ALL_FISH, FISH_BY_KEY, FISH_BY_TIER = _build_fish()


def _compute_boss_keys() -> set[str]:
    """Con cá đắt nhất trong mỗi tier (đã có dữ liệu) được coi là 'Boss' của
    tier đó — vừa hiếm nhất (do trọng số random theo giá trong roll_fish),
    vừa đáng để hiển thị tên nổi bật trong khung Kéo khi câu trúng."""
    boss_keys: set[str] = set()
    for fishes in FISH_BY_TIER.values():
        if not fishes:
            continue
        boss = max(fishes, key=lambda f: f.price)
        boss_keys.add(boss.key)
    return boss_keys


BOSS_FISH_KEYS: set[str] = _compute_boss_keys()


def is_boss_fish(fish_key: str) -> bool:
    return fish_key in BOSS_FISH_KEYS


def tiers_unlocked_for_pull(pull: int) -> list[FishTier]:
    """Trả về các tier mà 1 cần câu với lực kéo `pull` có thể câu được
    (chỉ tính tier đã có dữ liệu cá thật, bỏ qua tier còn rỗng)."""
    return [t for t in TIERS if pull >= t.required_pull and FISH_BY_TIER[t.key]]
