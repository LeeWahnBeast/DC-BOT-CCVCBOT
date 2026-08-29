"""
rod_data.py
===========
Danh sách cần câu, lấy từ tab "Cần Thường Trực" trong shop cần câu bạn gửi
ảnh (5 ảnh, hiển thị lần lượt theo độ mạnh tăng dần). Sắp xếp lại theo thứ
tự sức mạnh tăng dần (dựa trên "Sát thương/giây" + "Lực kéo").

GHI CHÚ
-------
- Tab thứ hai "Cần Câu Giới Hạn" (limited-time rods) chưa có ảnh nên chưa
  đưa vào — thêm sau khi có dữ liệu.
- 4 cây đầu (Cần câu người yêu cũ tặng, Thép Gân, Thép Gân Điêu Tàng,
  Thép Gân Tam Hợp, Cần Máy Ngang) trong ảnh gốc không hiện giá Vàng cụ
  thể (nút chỉ hiện "Trang Bị" / "Đã trang bị" — tức đã sở hữu sẵn / cần
  thường mở đầu game). Đã đặt mức giá Vàng THẤP hợp lý để có thể mua lại
  trong shop (đổi price_vang nếu bạn có số chính xác từ game).
- Các cây "Cách Nhận" không phải "Mua trực tiếp bằng Vàng" (quest/sự kiện/
  chế tạo) được để price_vang=None => không bán trong shop bằng Vàng, chỉ
  mở khóa qua lệnh riêng (vd lệnh admin/nhiệm vụ) bằng hàm grant_rod.
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
        "Không", "Mua trực tiếp bằng Vàng", price_vang=5_000),
    Rod("thep_gan", "Thép Gân", "🪝", 350, 50, 4,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=20_000),
    Rod("thep_gan_dieu_tang", "Thép Gân Điêu Tàng", "🪝", 800, 75, 5,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=80_000),
    Rod("thep_gan_tam_hop", "Thép Gân Tam Hợp", "🪝", 1_500, 100, 7,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=250_000),
    Rod("can_may_ngang", "Cần Máy Ngang", "🎣", 2_500, 150, 9,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=800_000),
    Rod("thep_gan_hop_kim", "Thép Gân Hợp Kim", "🎣", 5_000, 200, 12,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=2_500_000),
    Rod("thep_gan_hoang_kim", "Thép Gân Hoàng Kim", "🎣", 8_000, 300, 15,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=80_000_000),
    Rod("tre", "Cần Tre", "🎋", 12_000, 500, 20,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=150_000_000),
    Rod("pho_cot_chi_thu", "Phó Cốt Chi Thứ", "🦴", 15_000, 400, 15,
        "Mỗi đòn +500 sát thương", "Luyện từ Cá Mập Biến Dị 10 vạn cân"),
    Rod("am_thep_gan", "Âm · Thép Gân", "⛓️", 20_000, 600, 40,
        "Không", "Nhận khi hồi sinh Hạ Điếu Đế"),
    Rod("thep_gan_vibranium", "Thép Gân Vibranium", "🩶", 30_000, 700, 40,
        "Không", "Mua trực tiếp bằng Vàng", price_vang=300_000_000),
    Rod("nuot_troi", "Cần Nuốt Trời", "🐉", 25_000, 500, 35,
        "Nhân 20% Sát Thương Câu, mỗi 200 thể lực tiêu hao +5% sát thương",
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
DEFAULT_ROD_KEY = "nguoi_yeu_cu"
