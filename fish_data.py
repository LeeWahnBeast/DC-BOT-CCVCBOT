"""
fish_data.py
============
Dữ liệu các loài cá, chia theo cấp bậc giá (tier, dùng cho menu "Bán Cá")
và khu vực câu (map, dùng cho /chọn_map + roll cá lúc /câu_cá). 2 trục này
ĐỘC LẬP với nhau: 1 map có thể chứa cá thuộc nhiều tier giá khác nhau.

GHI CHÚ QUAN TRỌNG
------------------
- MAPS đã được LÀM LẠI HOÀN TOÀN theo đúng 9 khu vực + danh sách cá cụ thể
  do người dùng cung cấp (thay cho bộ map cũ 13 khu vực nhiều map trống).
- BOSS giờ được đánh dấu TƯỜNG MINH qua is_boss=True trên từng dòng cá
  (khớp đúng con nào là boss của map nào theo yêu cầu), KHÔNG còn tự động
  suy ra "cá đắt nhất trong tier" như bản cũ. Với các tier CHƯA đụng tới
  trong đợt làm lại này (vd Cấp Triệu Cân) vẫn giữ fallback tự động chọn
  cá đắt nhất trong tier làm boss, để không phá vỡ hành vi cũ ở phần chưa
  có yêu cầu mới.
- Map 7 (Vực Sâu Hà La) yêu cầu vật phẩm "Bản Đồ Vực Sâu Hà La"
  (MAP7_ITEM_KEY) ngoài cấp độ — vật phẩm này được thưởng khi câu được 1
  trong 3 cá boss của Map 6 (xem cấp code trong fishing_cog.py).
- Map 8 (Hậu Viện Nam Cương) và Map 9 (Sông Băng Cực): CHƯA có ảnh gốc
  xác nhận khối lượng/đơn giá — 4 con cá ở 2 map này (Đại Côn x2, Côn Hộ
  Pháp Khổng Lồ, Côn Băng Hà) dùng số liệu ƯỚC LƯỢNG tạm thời, cần chỉnh
  lại khi có ảnh/số liệu gốc.
- "SL" trong ảnh gốc là số lượng cá người chơi đang có, không phải thuộc
  tính loài cá nên không đưa vào đây.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import NamedTuple


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "ca"


def parse_weight_to_can(weight_label: str) -> float | None:
    """Quy đổi weight_label hiển thị (vd "500.000 cân", "1 vạn cân",
    "1,2 triệu cân") về 1 số thực đơn vị "cân" duy nhất, dùng để CỘNG DỒN
    tổng khối lượng cá đã câu của người chơi (bảng xếp hạng cân nặng).
    Trả về None nếu weight_label không xác định (vd "—") — cá đó không
    cộng vào tổng cân nặng (KHÔNG tự bịa số để tránh sai lệch xếp hạng).
    """
    s = weight_label.strip().lower()
    if not s or s in ("—", "-"):
        return None
    s = s.replace("cân", "").strip()

    multiplier = 1.0
    if "triệu" in s:
        multiplier = 1_000_000.0
        s = s.replace("triệu", "").strip()
    elif "vạn" in s:
        multiplier = 10_000.0
        s = s.replace("vạn", "").strip()

    if not s:
        return None
    # Quy ước Việt Nam: dấu phẩy = thập phân (vd "1,2"), dấu chấm = phân
    # cách hàng nghìn (vd "1.500.000") -> chuẩn hóa về float Python.
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(".", "")

    try:
        value = float(s)
    except ValueError:
        return None
    return value * multiplier


@dataclass(frozen=True)
class FishSpecies:
    key: str
    name: str
    weight_label: str    # hiển thị, vd "500.000 Cân" — cố định theo loài, không random
    price: int            # đơn giá bán, Vàng / con
    tier_key: str
    map_key: str | None = None   # khu vực câu, độc lập với tier giá
    weight_can: float | None = None  # weight_label quy đổi ra số "cân" (xem parse_weight_to_can)
    is_boss: bool = False  # boss của khu vực câu (map_key) — đánh dấu tường minh
    hp_override: int | None = None  # máu (target) CỐ ĐỊNH cho riêng con này —
        # None = tính theo công thức rod.pull * clicks_needed * hp_buff_multiplier
        # ở fishing_cog.compute_challenge như bình thường; đặt số ở đây để CHỐT
        # cứng 1 mức máu base cụ thể bất kể cần câu nào đang dùng (GLOBAL_HP_
        # MULTIPLIER trong fishing_cog.py vẫn nhân thêm vào số base này).


@dataclass(frozen=True)
class FishingMap:
    key: str
    label: str
    emoji: str
    unlock_level: int = 0   # 0 = mở sẵn, >0 = cần đạt cấp độ này mới câu được
    requires_item: str | None = None  # key vật phẩm cần có thêm để mở (ngoài unlock_level)


@dataclass(frozen=True)
class FishTier:
    key: str
    label: str             # tên hiển thị giống menu bên trái trong game
    required_pull: int      # lực kéo tối thiểu của cần câu để ra cá tier này


# ---------------------------------------------------------------------------
# Vật phẩm mở khóa Map 7 — thưởng khi câu được 1 trong các cá boss của Map 6
# (xem CATCH_ITEM_DROPS bên dưới + xử lý cộng vào data["map_items"] trong
# fishing_cog.py).
# ---------------------------------------------------------------------------
MAP7_ITEM_KEY = "ban_do_vuc_sau_ha_la"
MAP7_ITEM_LABEL = "Bản Đồ Vực Sâu Hà La"

# ---------------------------------------------------------------------------
# Khu vực câu cá — 9 map theo đúng yêu cầu (thay toàn bộ bộ map cũ).
# unlock_level: cấp độ NGƯỜI CHƠI (data["level"]) cần đạt để chọn được khu
# vực này trong /chọn_map — xem MapSelectView trong fishing_cog.py.
# ---------------------------------------------------------------------------
MAP1_KEY = "ho_bo_hoang"
MAP2_KEY = "ho_thuy_dien"
MAP3_KEY = "ho_cao_nguyen"
MAP4_KEY = "dap_nuoc"
MAP5_KEY = "khu_nuoc_thai_hat_nhan"
MAP6_KEY = "ho_den"
MAP7_KEY = "vuc_sau_ha_la"
MAP8_KEY = "hau_vien_nam_cuong"
MAP9_KEY = "song_bang_cuc"

MAPS: list[FishingMap] = [
    FishingMap(MAP1_KEY, "Hồ chứa nước bỏ hoang", "🏞️", unlock_level=1),
    FishingMap(MAP2_KEY, "Hồ thủy điện gần nhà máy điện hạt nhân", "🌊", unlock_level=10),
    FishingMap(MAP3_KEY, "Hồ cao nguyên trên 5.000 m", "🏔️", unlock_level=20),
    FishingMap(MAP4_KEY, "Đập nước", "🏗️", unlock_level=30),
    FishingMap(MAP5_KEY, "Khu vực nước thải hạt nhân", "☢️", unlock_level=45),
    FishingMap(MAP6_KEY, "Hố đen", "🕳️", unlock_level=60),
    # Cần Lv.60 + vật phẩm "Bản Đồ Vực Sâu Hà La" (rơi từ boss Map 6).
    FishingMap(MAP7_KEY, "Vực sâu Hà La", "🌀", unlock_level=60, requires_item=MAP7_ITEM_KEY),
    FishingMap(MAP8_KEY, "Hậu viện Nam Cương", "🏯", unlock_level=80),
    FishingMap(MAP9_KEY, "Sông băng cực", "🧊", unlock_level=80),
]
MAP_BY_KEY: dict[str, FishingMap] = {m.key: m for m in MAPS}


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
    FishTier("ngan_van_can", "Ngàn Vạn Cân", 1200),
    FishTier("son_hai", "Sơn Hải", 2000),
    # Chưa có dữ liệu thật — điền cá vào _RAW_FISH khi có ảnh rõ.
    FishTier("ca_gioi_han", "Cá Giới Hạn", 2500),
    FishTier("ca_dac_biet", "Cá Đặc Biệt", 3000),
]
TIER_BY_KEY: dict[str, FishTier] = {t.key: t for t in TIERS}


class _F(NamedTuple):
    """1 dòng cá thô: (tên, khối_lượng_hiển_thị, đơn_giá_vàng, map_key, is_boss)."""
    name: str
    weight_label: str
    price: int
    map_key: str | None = None
    is_boss: bool = False
    hp_override: int | None = None  # xem FishSpecies.hp_override


# Cấp Mười Cân — Map 1 (Hồ chứa nước bỏ hoang, Lv.1).
_MUOI_CAN = [
    _F("Cá Thanh Hoa", "5 cân", 15_000, MAP1_KEY),
    _F("Cá Vàng", "10 cân", 20_000, MAP1_KEY),
    _F("Cá Chép Nhỏ", "10 cân", 25_000, MAP1_KEY),
    _F("Cá Liên Trắng", "20 cân", 30_000, MAP1_KEY),
    _F("Cá Trê", "30 cân", 40_000, MAP1_KEY),
    _F("Cá Diếc", "40 cân", 50_000, MAP1_KEY),
    # Đổi tên từ "Cá Nheo Biến Dị" theo yêu cầu — boss Map 1.
    _F("Cá Chép Râu Đỏ", "80 cân", 100_000, MAP1_KEY, is_boss=True),
]

# Cấp Trăm Cân — Map 2 (Hồ thủy điện gần nhà máy điện hạt nhân, Lv.10).
_TRAM_CAN = [
    _F("Cá Chép Đỏ Đột Biến", "100 cân", 150_000, MAP2_KEY),
    _F("Cá Chép Xanh Biến Dị", "100 cân", 150_000, MAP2_KEY),
    _F("Cá Liên Dung Biến Dị", "180 cân", 200_000, MAP2_KEY),
    _F("La Phi Khổng Lồ", "300 cân", 500_000, MAP2_KEY),
    _F("Tổ Ngư Hoàng Kim", "400 cân", 800_000, MAP2_KEY),
    _F("Vương Cá Chép", "500 cân", 1_000_000, MAP2_KEY, is_boss=True),
    _F("Đối Thiên Kiều", "500 cân", 1_000_000, MAP2_KEY, is_boss=True),
]

# Cấp Ngàn Cân — dàn trải Map 3/4/5/6 (xem map_key từng dòng).
_NGAN_CAN = [
    _F("Bạch Điêu Ngàn Cân", "1.000 cân", 1_200_000, MAP3_KEY),
    _F("Cá Thanh Râu Vàng", "1.200 cân", 1_500_000, MAP3_KEY),
    _F("Cá Cờ Vây Đen", "1.400 cân", 2_000_000, MAP3_KEY),
    _F("Cá Cờ Vây Đỏ", "1.600 cân", 2_500_000, MAP3_KEY),
    _F("Cá Trắng Vây Vàng", "1.800 cân", 2_800_000, MAP3_KEY),
    _F("Cá Cờ Vây Xanh", "2.500 cân", 3_000_000, MAP3_KEY),
    _F("La Phi Đầu Rồng (Nhỏ)", "2.500 cân", 2_000_000, MAP3_KEY),
    _F("Vua Cá Cờ", "5.000 cân", 4_500_000, MAP3_KEY, is_boss=True),
    _F("La Phi Đầu Rồng (Lớn)", "6.000 cân", 5_000_000, MAP3_KEY, is_boss=True),
    _F("Quy Ngư Đột Biến", "5.000 cân", 4_000_000, MAP5_KEY),
    _F("Thạch Bản Đột Biến", "5.000 cân", 4_200_000, MAP4_KEY),
    _F("Bá Ngư Đột Biến", "5.000 cân", 4_500_000, MAP4_KEY),
    _F("Giao Ngư Đột Biến", "6.000 cân", 4_800_000, MAP5_KEY),
    _F("Xước Ngư Đột Biến", "7.000 cân", 5_000_000, MAP5_KEY),
    _F("Điêu Ngư Đột Biến", "7.000 cân", 5_200_000, MAP5_KEY),
    _F("Xích Nhãn", "8.000 cân", 6_500_000, MAP5_KEY),
    _F("Cá Cờ Côn Luân", "3.000 cân", 8_000_000, MAP6_KEY),
    _F("Thổ Lăng Ngư", "4.000 cân", 8_000_000, MAP6_KEY),
    _F("Cá Biển Dị", "5.000 cân", 8_500_000, MAP6_KEY),
    _F("Cá Mỏ Nhọn Biển Dị", "5.000 cân", 8_500_000, MAP6_KEY),
]

# Vạn Cân — dàn trải Map 3/4/5/6, phần không thuộc map nào ở lại map_key=None.
# 4 con boss giá 8-11 triệu (giá đã nhân PRICE_MULTIPLIER) được CHỐT máu base
# cứng ~870.000 qua hp_override (x GLOBAL_HP_MULTIPLIER ở fishing_cog.py ->
# ra gần đúng 1 triệu máu hiển thị, theo đúng yêu cầu, KHÔNG còn phụ thuộc
# công thức rod.pull * clicks_needed như cá thường).
_VAN_CAN = [
    _F("Giao Ngư Long", "10.000 cân", 8_000_000, MAP3_KEY, is_boss=True, hp_override=870_000),
    _F("Cá Mập Biến Dị", "1 vạn cân", 9_500_000, MAP5_KEY, is_boss=True, hp_override=870_000),
    _F("Cá Biển Đột Biến", "1 vạn cân", 8_500_000),  # chưa gán map theo yêu cầu mới
    _F("Tam Đương Gia Bá Địa Hổ", "10.000 cân", 7_800_000, MAP4_KEY, is_boss=True, hp_override=870_000),
    _F("Nhị Đương Gia Bá Địa Hổ", "10.000 cân", 8_000_000, MAP4_KEY),
    _F("Đại Đương Gia Bá Địa Hổ", "10.000 cân", 8_200_000, MAP4_KEY, is_boss=True, hp_override=870_000),
    _F("Cá Chép Nuốt Trời", "2 vạn cân", 12_000_000, MAP4_KEY, is_boss=True),
    _F("Liên Ưng Lôi Điện", "30.000 cân", 15_000_000, MAP6_KEY),
    _F("Thanh Ngư Sừng Bạc", "50.000 cân", 17_500_000, MAP6_KEY),
    _F("Cá Đầu Chó", "50.000 cân", 18_000_000, MAP6_KEY, is_boss=True),
    _F("Cá Cờ Đầu Bò", "20.000 cân", 17_000_000, MAP6_KEY, is_boss=True),
    _F("Song Thổ Lăng Ngư", "30.000 cân", 18_000_000, MAP6_KEY, is_boss=True),
    _F("Âm·Trúc Thanh Bạch Điêu", "5 vạn cân", 17_000_000),  # chưa gán map theo yêu cầu mới
]

# Mười Vạn Cân — 2 con được gán làm boss Map 4/5, phần còn lại chưa gán map.
_MUOI_VAN_CAN = [
    _F("Cá Piranha", "100.000 cân", 40_000_000),
    _F("Ngư Châu", "—", 200_000_000),
    _F("Vua Cá Mập Biển", "10 vạn cân", 30_000_000, MAP5_KEY, is_boss=True),
    _F("Cá Koi Hình Rồng", "100.000 cân", 30_000_000, MAP4_KEY, is_boss=True),
    _F("Âm·Cá Mào Gà", "10 vạn cân", 30_000_000),
    _F("Âm·Lý Ngư Sừng Đỏ", "15 vạn cân", 35_000_000),
    _F("Âm·Cá Lưng Gai", "20 vạn cân", 40_000_000),
    _F("Cá Rắn Xương Khổng Lồ", "20 vạn cân", 40_000_000),
    _F("Cá Trầm Đen", "400.000 cân", 20_000_000),
    _F("Âm·Cá Ăn Thịt", "30 vạn cân", 40_000_000),
    _F("Cá Liếc Biến Dị", "500.000 cân", 50_000_000),
    _F("Cá Diếc Sừng Khổng Lồ", "500.000 cân", 50_000_000),
    _F("Cư Lân Ngư Biến Dị", "500.000 cân", 50_000_000),
    _F("Âm·Cá Lưng Xanh Mắt Đỏ", "40 vạn cân", 45_000_000),
    _F("Cá Chép Râu Vàng Đỏ", "600.000 cân", 60_000_000),
    _F("Cá Chép Râu Vàng Xanh", "600.000 cân", 60_000_000),
    _F("Bàng Tỵ Biến Dị", "600.000 cân", 60_000_000),
    _F("Bạch Lư Răng Cưa", "600.000 cân", 60_000_000),
    _F("Cá Sấu Hoa", "600.000 cân", 70_000_000),
    _F("Âm·Thanh Ngư Sừng Trâu", "500.000 cân", 50_000_000),
    _F("Thanh Ngư Xích Nhãn", "800.000 cân", 70_000_000),
    _F("Liên Ưng Vây Đao", "800.000 cân", 70_000_000),
    _F("Hắc Lư Mắt Đỏ", "800.000 cân", 70_000_000),
    _F("La Phi Dã Biến Dị", "800.000 cân", 70_000_000),
    _F("Quế Ngư Biến Dị", "800.000 cân", 80_000_000),
    _F("Đuôi Đỏ", "800.000 cân", 70_000_000),
]

# Cấp Triệu Cân — chưa có ảnh khoanh map, KHÔNG đụng tới trong đợt làm lại
# map này -> vẫn dùng fallback boss tự động (cá đắt nhất trong tier).
_TRIEU_CAN = [
    _F("Vua Cá Mập Xanh", "1 triệu cân", 85_000_000),
    _F("Cá Mú Vây Dao", "1 triệu cân", 85_000_000),
    _F("Cá Voi Đột Biến", "1,2 triệu cân", 95_000_000),
    _F("Cá Đèn Biển", "1 triệu cân", 95_000_000),
    _F("Anh Phiêu Tuyết", "—", 150_000_000),
    _F("Răng Lốt Hóa", "1.500.000 cân", 110_000_000),
    _F("Cá Chép Đổi Màu", "1.000.000 cân", 110_000_000),
    _F("Cá Koi Hình Rồng (Triệu Cân)", "1 triệu cân", 110_000_000),
    _F("Cá Lưỡi Xương Khổng Lồ Amazon", "3 triệu cân", 150_000_000),
    _F("Cá Diếp Vân Rồng", "1.000.000 cân", 72_000_000),
    _F("Cá Dao Khổng Lồ", "1.000.000 cân", 72_000_000),
    _F("Cá Ngừ Độc Bích", "1.000.000 cân", 72_000_000),
    _F("Cá Sừng Nâu", "1.000.000 cân", 72_000_000),
    _F("Cá Nóc Quái Thú", "—", 230_000_000),
    _F("Cá Nóc Lam", "—", 250_000_000),
    _F("Thanh Ngư Xoắn", "2 triệu cân", 120_000_000),
    _F("Đèn Lồng Khổng Lồ", "5 triệu cân", 170_000_000),
    _F("Cá Kiếm Biển Dị", "2 triệu cân", 120_000_000),
    _F("Cá Sói Biển Dị", "2 triệu cân", 120_000_000),
    _F("Cá Bơn Biển Dị", "2 triệu cân", 120_000_000),
    _F("Cá Voi Lưng Gù", "—", 270_000_000),
    _F("Cá Koi Hình Rồng Khổng Lồ", "3 triệu cân", 150_000_000),
    _F("Cá Chép Rồng Vàng", "3 triệu cân", 150_000_000),
    _F("Cá Chép Rồng Bạc", "3 triệu cân", 150_000_000),
    _F("Cá Trê Lãnh Thổ", "—", 285_000_000),
    _F("Ngân Giáp Cán Ngư", "3 triệu cân", 150_000_000),
    _F("Cá Koi May Mắn", "3 triệu cân", 150_000_000),
    _F("Xích Giáp Cán Vương", "—", 240_000_000),
    _F("Cá Điêu Râu Bạc", "—", 295_000_000),
    _F("Vua Cá Diếc Vảy Vàng", "—", 200_000_000),
    _F("Lươn Điện Biến Dị", "—", 200_000_000),
    _F("Rùa Cá Sấu Trăm", "—", 200_000_000),
]

# Sơn Hải — Map 7 (Vực sâu Hà La, Lv.60 + vật phẩm bản đồ). Khớp đúng menu
# "Sơn Hải" trong ảnh gốc (12 con: 10 Hà La Ngư Phân + 2 boss).
_SON_HAI = [
    _F("Hà La Ngư Phân 1", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 2", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 3", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 4", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 5", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 6", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 7", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 8", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 9", "200.000 cân", 45_000_000, MAP7_KEY),
    _F("Hà La Ngư Phân 10", "200.000 cân", 45_000_000, MAP7_KEY),
    # 2 boss cuối cùng — theo yêu cầu, cần "đánh bại từ Phân 1 đến Phân 10"
    # trước (thứ tự roll/điều kiện mở khóa cụ thể xử lý ở fishing_cog.py).
    _F("Bản Thể Hà La Ngư", "1 triệu cân", 75_000_000, MAP7_KEY, is_boss=True),
    _F("Hà La Ngư Thoát", "1 triệu cân", 85_000_000, MAP7_KEY, is_boss=True),
]

# Ngàn Vạn Cân — Map 8 (Hậu viện Nam Cương) + Map 9 (Sông băng cực).
# ƯỚC LƯỢNG TẠM — chưa có ảnh gốc xác nhận số liệu, xem ghi chú đầu file.
_NGAN_VAN_CAN = [
    _F("Đại Côn", "200.000 cân", 320_000_000, MAP8_KEY),
    _F("Đại Côn (Boss)", "600.000 cân", 450_000_000, MAP8_KEY, is_boss=True),
    _F("Côn Hộ Pháp Khổng Lồ", "—", 500_000_000, MAP9_KEY),
    _F("Côn Băng Hà", "—", 650_000_000, MAP9_KEY, is_boss=True),
]

_RAW_FISH: dict[str, list[_F]] = {
    "muoi_can": _MUOI_CAN,
    "tram_can": _TRAM_CAN,
    "ngan_can": _NGAN_CAN,
    "van_can": _VAN_CAN,
    "muoi_van_can": _MUOI_VAN_CAN,
    "trieu_can": _TRIEU_CAN,
    "ngan_van_can": _NGAN_VAN_CAN,
    "son_hai": _SON_HAI,
    # Chưa có ảnh mở khóa — để trống.
    "ca_gioi_han": [],
    "ca_dac_biet": [],
}


# Hệ số tăng giá bán cá toàn cục — tăng 10% so với giá gốc trong _RAW_FISH.
PRICE_MULTIPLIER = 1.10


def _make_unique_key(base_key: str, used_keys: set[str]) -> str:
    key, n = base_key, 2
    while key in used_keys:
        key = f"{base_key}_{n}"
        n += 1
    used_keys.add(key)
    return key


def _build_fish() -> tuple[
    list[FishSpecies],
    dict[str, FishSpecies],
    dict[str, list[FishSpecies]],
    dict[str, list[FishSpecies]],
    set[str],
]:
    all_fish: list[FishSpecies] = []
    used_keys: set[str] = set()
    by_tier: dict[str, list[FishSpecies]] = {t.key: [] for t in TIERS}
    by_map: dict[str, list[FishSpecies]] = {m.key: [] for m in MAPS}
    boss_keys: set[str] = set()
    tier_has_explicit_boss: set[str] = set()

    for tier_key, rows in _RAW_FISH.items():
        best_in_tier: FishSpecies | None = None
        for row in rows:
            key = _make_unique_key(f"{tier_key}_{_slugify(row.name)}", used_keys)
            priced = max(1, round(row.price * PRICE_MULTIPLIER))
            fish = FishSpecies(key=key, name=row.name, weight_label=row.weight_label,
                                price=priced, tier_key=tier_key, map_key=row.map_key,
                                weight_can=parse_weight_to_can(row.weight_label),
                                is_boss=row.is_boss, hp_override=row.hp_override)
            all_fish.append(fish)
            by_tier[tier_key].append(fish)
            if row.map_key is not None:
                by_map[row.map_key].append(fish)
            if row.is_boss:
                boss_keys.add(fish.key)
                tier_has_explicit_boss.add(tier_key)
            if best_in_tier is None or fish.price > best_in_tier.price:
                best_in_tier = fish
        # Fallback: tier nào KHÔNG có boss tường minh nào (chưa đụng tới
        # trong đợt làm lại map) thì giữ hành vi cũ — cá đắt nhất làm boss.
        if best_in_tier is not None and tier_key not in tier_has_explicit_boss:
            boss_keys.add(best_in_tier.key)

    return all_fish, {f.key: f for f in all_fish}, by_tier, by_map, boss_keys


ALL_FISH, FISH_BY_KEY, FISH_BY_TIER, FISH_BY_MAP, BOSS_FISH_KEYS = _build_fish()


# ---------------------------------------------------------------------------
# Rác — kết quả câu "hụt" (xem fishing_cog.roll_catch): không thuộc TIERS/
# _RAW_FISH ở trên (không được chọn qua roll_fish bình thường / không hiện
# trong /chọn_map hay ảnh hưởng tỉ lệ boss), CHỈ được chọn qua nhánh random
# tỉ lệ rác riêng. Vẫn tái dùng dataclass FishSpecies để toàn bộ pipeline có
# sẵn (kho đồ, bán, minigame kéo, EXP...) hoạt động được luôn không cần sửa
# thêm — phân biệt rác/cá thật qua JUNK_KEYS (is_junk_fish()).
# tier_key="rac" được đăng ký thêm vào FISH_BY_TIER bên dưới để
# compute_challenge() (fishing_cog.py, tra FISH_BY_TIER[fish.tier_key] để
# tính độ dai) không bị KeyError khi câu phải rác.
# ---------------------------------------------------------------------------
_RAC: list[_F] = [
    _F("Ủng Cao Su Cũ", "—", 500),
    _F("Lon Nước Ngọt Rỉ Sét", "—", 300),
    _F("Túi Ni-lông Rách", "—", 150),
    _F("Chai Nhựa Vỡ", "—", 200),
    _F("Rong Rêu Ướt Sũng", "—", 100),
    _F("Dép Tổ Ong Một Chiếc", "—", 350),
    _F("Lưới Đánh Cá Mục Nát", "—", 250),
    _F("Vỏ Lon Bia Gỉ Sét", "—", 300),
]


def _build_junk() -> tuple[list[FishSpecies], dict[str, FishSpecies], set[str]]:
    junk: list[FishSpecies] = []
    used_keys: set[str] = set()
    for row in _RAC:
        key = _make_unique_key(f"rac_{_slugify(row.name)}", used_keys)
        item = FishSpecies(
            key=key, name=row.name, weight_label=row.weight_label,
            price=row.price, tier_key="rac", map_key=None, weight_can=None,
        )
        junk.append(item)
    return junk, {j.key: j for j in junk}, {j.key for j in junk}


JUNK_ITEMS, JUNK_BY_KEY, JUNK_KEYS = _build_junk()
FISH_BY_TIER["rac"] = JUNK_ITEMS


def is_junk_fish(fish_key: str) -> bool:
    return fish_key in JUNK_KEYS


def roll_junk() -> FishSpecies:
    """Random đều 1 món rác (rác không phân cấp hiếm/thường như cá)."""
    return random.choice(JUNK_ITEMS)


def is_boss_fish(fish_key: str) -> bool:
    return fish_key in BOSS_FISH_KEYS


def fish_in_map(map_key: str) -> list[FishSpecies]:
    """Cá đã gán vào khu vực `map_key` (cá chưa xác định map trả về rỗng)."""
    return FISH_BY_MAP.get(map_key, [])


def map_is_unlocked(map_key: str, level: int, map_items: set[str] | list[str] | None = None) -> bool:
    """1 map mở được khi đủ cấp độ VÀ (nếu map yêu cầu vật phẩm) đã có vật
    phẩm đó trong data["map_items"]. Dùng ở MapSelectView (fishing_cog.py)."""
    m = MAP_BY_KEY.get(map_key)
    if m is None:
        return False
    if level < m.unlock_level:
        return False
    if m.requires_item and m.requires_item not in (map_items or ()):
        return False
    return True


def tiers_unlocked_for_pull(pull: int) -> list[FishTier]:
    """Các tier mà 1 cần câu với lực kéo `pull` có thể câu được (chỉ tính
    tier đã có dữ liệu cá thật, bỏ qua tier còn rỗng)."""
    return [t for t in TIERS if pull >= t.required_pull and FISH_BY_TIER[t.key]]
