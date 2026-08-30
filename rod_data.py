"""
rod_data.py
===========
Danh sách cần câu, lấy từ tab "Cần Thường Trực" trong shop cần câu bạn gửi
ảnh (5 ảnh, hiển thị lần lượt theo độ mạnh tăng dần). Sắp xếp lại theo thứ
tự sức mạnh tăng dần (dựa trên "Sát thương/giây" + "Lực kéo").

GHI CHÚ
-------
- Tab thứ hai "Cần Câu Giới Hạn" (limited-time rods, xem LIMITED_ROD_LIST)
  lấy từ 3 ảnh chụp shop cần câu — toàn bộ đều KHÔNG bán trực tiếp bằng
  Vàng (price_vang=None), chỉ nhận qua sự kiện/lễ/thẻ như "Cách Nhận" ghi
  trong ảnh, nên chỉ hiển thị xem thông tin trong shop, không có nút mua.
  1 cây (Thép Gân Châu) bị ảnh cắt mất chỉ số/hiệu ứng nên CHƯA thêm —
  điền sau khi có ảnh đầy đủ.
- 4 cây đầu (Cần câu người yêu cũ tặng, Thép Gân, Thép Gân Điêu Tàng,
  Thép Gân Tam Hợp, Cần Máy Ngang) trong ảnh gốc không hiện giá Vàng cụ
  thể (nút chỉ hiện "Trang Bị" / "Đã trang bị" — tức đã sở hữu sẵn / cần
  thường mở đầu game). Đã đặt mức giá Vàng THẤP hợp lý để có thể mua lại
  trong shop (đổi price_vang nếu bạn có số chính xác từ game).
- Các cây "Cách Nhận" không phải "Mua trực tiếp bằng Vàng" (quest/sự kiện/
  chế tạo) được để price_vang=None => không bán trong shop bằng Vàng, chỉ
  mở khóa qua lệnh riêng (vd lệnh admin/nhiệm vụ) bằng hàm grant_rod.
- GIÁ TRIỆU: toàn bộ price_vang của các cần bán trực tiếp đã được quy về
  bội số tròn của 1.000.000 (1 triệu) Vàng, khớp với mặt bằng giá cá (cá
  cấp cao bán được hàng chục/hàng trăm triệu Vàng/con) và hiển thị bằng
  fishing_cog.fmt_gia_trieu() dạng "X triệu" thay vì số lẻ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Rod:
    key: str
    name: str
    emoji: str
    dps: int                    # Sát thương/giây
    pull: int                    # Lực kéo
    line_len: int                 # Độ dài dây câu (giới hạn trước khi đứt)
    effect: str                    # Hiệu ứng đặc biệt
    obtain: str                     # Cách nhận
    price_vang: Optional[int] = None   # None = không bán trực tiếp bằng Vàng


ROD_LIST: list[Rod] = [
    Rod("nguoi_yeu_cu", "Cần Câu Người Yêu Cũ Tặng", "🎏", 150, 25, 3,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=1_000_000),
    Rod("thep_gan", "Thép Gân", "<:caimoc:1543465444545921116>", 350, 50, 4,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=3_000_000),
    Rod("thep_gan_dieu_tang", "Thép Gân Điêu Tàng", "<:caimoc:1543465444545921116>", 800, 75, 5,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=8_000_000),
    Rod("thep_gan_tam_hop", "Thép Gân Tam Hợp", "<:caimoc:1543465444545921116>", 1_500, 100, 7,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=20_000_000),
    Rod("can_may_ngang", "Cần Máy Ngang", "🎣", 2_500, 150, 9,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=50_000_000),
    Rod("thep_gan_hop_kim", "Thép Gân Hợp Kim", "🎣", 5_000, 200, 12,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=120_000_000),
    Rod("thep_gan_hoang_kim", "Thép Gân Hoàng Kim", "🎣", 8_000, 300, 15,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=250_000_000),
    Rod("tre", "Cần Tre", "🎋", 12_000, 500, 20,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=400_000_000),
    Rod("pho_cot_chi_thu", "Phó Cốt Chi Thứ", "🦴", 15_000, 400, 15,
        "Mỗi đòn +500 sát thương", "Luyện từ Cá Mập Biến Dị 10 vạn cân"),
    Rod("am_thep_gan", "Âm · Thép Gân", "⛓️", 20_000, 600, 40,
        "Không", "Nhận khi hồi sinh Hạ Điếu Đế"),
    Rod("thep_gan_vibranium", "Thép Gân Vibranium", "🩶", 30_000, 700, 40,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=600_000_000),
    Rod("nuot_troi", "Cần Nuốt Trời", "🐉", 25_000, 500, 35,
        "Nhân 20% Sát Thương Câu, mỗi 200 thể lực tiêu hao +5% sát thương",
        "Nhận từ phó bản Cá Chép Kình Biến"),
    Rod("vuong_gia_dai_vat", "Vương Giả Đại Vật", "<:vuongmien:1543461013045645323>", 45_000, 1_000, 65,
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
DEFAULT_ROD_KEY = "nguoi_yeu_cu"


# ---------------------------------------------------------------------------
# Cần Câu Giới Hạn (tab riêng trong shop) — toàn bộ nhận qua sự kiện/lễ/thẻ,
# KHÔNG bán trực tiếp bằng Vàng (price_vang=None với mọi cây trong danh
# sách này). "Cách Nhận" giữ đúng chữ hiển thị trong ảnh gốc.
# ---------------------------------------------------------------------------
LIMITED_ROD_LIST: list[Rod] = [
    Rod("gh_can_phao_hoa", "Cần Pháo Hoa", "🎆", 50_000, 800, 60,
        "Cháy: Nhận 66% cộng thêm Sát Thương Câu, chỉ kéo dài 20 giây",
        "Nhận từ Sự Kiện Tết Dương Lịch"),
    Rod("gh_can_ca_kiem", "Cần Cá Kiếm", "⚔️", 50_000, 900, 70,
        "Thần Tốc: Giảm thời gian hồi chiêu điệu 30%",
        "Nhận từ Lễ 5 Triệu"),
    Rod("gh_thep_gan_huyet_sac", "Thép Gân Huyết Sắc", "🩸", 65_000, 1_200, 40,
        "Tăng 80% Sát Thương Câu một đoạn",
        "Nhận từ Lễ 6 Triệu"),
    Rod("gh_tu_dien_than_can", "Tử Điện Thần Cần", "🟣", 50_000, 1_000, 80,
        "Nhận 50% cộng sát thương câu, giảm 20% thời gian hồi chiêu điệu, "
        "giảm 30% tiêu hao thể lực câu",
        "Cần Thẻ Cá Đợt 1"),
    Rod("gh_lai_tai_can", "Lai Tài Cần", "🧧", 70_000, 1_200, 100,
        "Nhận 30% cộng sát thương câu, giảm 30% thời gian hồi chiêu điệu, "
        "20% tỷ lệ nhận cá gấp đôi",
        "Nhận từ Lễ 7 Triệu"),
    Rod("gh_thep_gan_lap_lanh", "Thép Gân Lấp Lánh", "<:sao:1543465405484503160>", 3_000, 60, 3,
        "Nhận cộng dây câu, Khống Cá và sát thương tăng theo cấp cường hóa "
        "(cơ bản +7.200 sát thương/giây, +144 lực kéo, +7,2 độ dài dây câu)",
        "Nhận từ Lễ 20 Vạn"),
    Rod("gh_can_xuong_vang", "Cần Xương Vàng", "🦴", 40_000, 600, 50,
        "Mỗi đòn +8.000 sát thương, 1% nhận 50 vạn Vàng",
        "Nhận từ Triệu Lễ"),
    Rod("gh_can_an_long", "Cần Ẩn Long", "🐲", 35_000, 600, 60,
        "Nhận 25% cộng thêm Sát Thương Câu, 50% tỷ lệ miễn nhiễm tấn công của cá",
        "Nhận từ Lễ 2 Triệu"),
    Rod("gh_can_keo_giang_sinh", "Cần Kẹo Giáng Sinh", "🎄", 45_000, 1_200, 70,
        "Nhận 20% cộng thêm Sát Thương Câu, trong thời gian Thu Dây có 5% tỷ lệ "
        "buộc kéo cá một đoạn",
        "Nhận từ Sự Kiện Giáng Sinh"),
    Rod("gh_can_tuong_van", "Cần Tường Vận", "🍀", 80_000, 1_000, 80,
        "Nhận 50% Cộng Điệu Câu, Điệu Câu có 20% tỷ lệ bạo kích, 20% tỷ lệ "
        "đặt lại hồi chiêu",
        "Nhận từ Sự Kiện Tết"),
    Rod("gh_can_ma_thuong_huu_ngu", "Cần Mã Thượng Hữu Ngư", "🐎", 88_888, 888, 88,
        "Nhận 88% Cộng câu, Quăng cần là câu được cá lớn ngay!",
        "Nhận từ Sự Kiện Tết"),
    Rod("gh_truc_van_nien", "Trúc Vạn Niên", "🐼", 88_888, 888, 88,
        "Nhận (20 + số phúc lợi đã nhận) x 3 cộng sát thương (hiện tại: 23%)",
        "Kỷ Niệm Gấu Trúc Độc Quyền"),
]

LIMITED_RODS: dict[str, Rod] = {r.key: r for r in LIMITED_ROD_LIST}

# RODS gộp cả 2 tab để tra cứu theo key (equip/lookup không cần biết cần
# đang ở tab nào) — dùng ở fishing_cog.py khi đọc data["rod"].
RODS.update(LIMITED_RODS)
