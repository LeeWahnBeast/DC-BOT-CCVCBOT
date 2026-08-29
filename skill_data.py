"""
skill_data.py
=============
Kỹ năng câu cá — dùng trong ván kéo cá (xem ReelView trong fishing_cog.py).
Lấy cảm hứng từ hệ thống skill của game gốc "Câu Cá Vạn Cân": skill tiêu
hao thể lực (Stamina) và tác dụng chính là hỗ trợ dây câu KHÔNG bị đứt,
không gây thêm sát thương trực tiếp lên máu cá.

TRANG BỊ
--------
Mỗi người chơi có SKILL_SLOTS = 3 ô trang bị (data["equipped_skills"]),
mỗi ô chứa 1 skill_key hoặc None. Skill phải được mua/mở khóa
(data["unlocked_skills"]) trước khi trang bị được vào ô.

DÙNG TRONG VÁN CÂU
-------------------
Mỗi skill chỉ dùng được ĐÚNG 1 LẦN mỗi ván kéo cá (xem ReelView.skills_used),
tốn `energy_cost` thể lực ngay khi dùng, có 2 loại hiệu ứng:

- "reduce_tension": trừ NGAY một phần trăm (`value`) độ căng dây câu hiện
  tại — dùng khi dây sắp đứt để "câu giờ".
- "slow_tension": trong `duration_s` giây kế tiếp, độ căng dây tăng chậm
  hơn hẳn theo hệ số (`value`) — áp dụng cho cả lúc bấm "Kéo!" lẫn lúc
  đứng yên (idle tick) — dùng để câu an toàn với cá dai/cá boss.
"""

from __future__ import annotations

from dataclasses import dataclass

SKILL_SLOTS = 3   # số ô trang bị skill mỗi người chơi


@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    emoji: str
    effect: str            # "reduce_tension" | "slow_tension"
    value: float             # reduce_tension: % trừ ngay; slow_tension: % giảm tốc độ tăng
    energy_cost: int          # thể lực tiêu hao mỗi lần dùng (1 lần/ván câu)
    price_vang: int            # giá mở khóa, quy về giá triệu (bội số 1.000.000)
    duration_s: int = 0          # chỉ áp dụng cho slow_tension
    description: str = ""


SKILL_SHOP: list[Skill] = [
    Skill(
        "giat_day", "Giật Dây", "🌀", "reduce_tension", 0.25, 15, 5_000_000,
        description="Giật nhẹ dây câu đúng lúc, trừ ngay một phần độ căng dây hiện tại.",
    ),
    Skill(
        "giu_chan_ca", "Giữ Chân Cá", "⚓", "slow_tension", 0.5, 25, 15_000_000,
        duration_s=8,
        description="Ghì chặt cần câu, khiến dây câu căng chậm lại hẳn trong ít giây.",
    ),
    Skill(
        "tha_long_day", "Thả Lỏng Dây", "💨", "reduce_tension", 0.45, 30, 20_000_000,
        description="Nới dây câu đúng nhịp, trừ ngay gần một nửa độ căng dây hiện tại.",
    ),
    Skill(
        "dinh_tam_cau", "Định Tâm", "🧘", "slow_tension", 0.7, 45, 50_000_000,
        duration_s=12,
        description="Giữ nhịp thở thật đều, độ căng dây gần như ngừng tăng trong một lúc.",
    ),
    Skill(
        "pha_bang_day", "Phá Băng", "❄️", "reduce_tension", 0.6, 50, 80_000_000,
        description="Làm dây câu cứng cáp tạm thời, trừ ngay phần lớn độ căng dây hiện tại.",
    ),
    Skill(
        "an_nhien_cau", "An Nhiên", "🍃", "slow_tension", 1.0, 60, 150_000_000,
        duration_s=10,
        description="Tâm bất động trước sóng gió, độ căng dây HOÀN TOÀN không tăng trong ít giây.",
    ),
]

SKILLS: dict[str, Skill] = {s.key: s for s in SKILL_SHOP}


def equipped_skill_objects(data: dict) -> list[Skill | None]:
    """Trả về list SKILL_SLOTS phần tử: Skill đã trang bị & còn mở khóa,
    hoặc None cho ô trống / skill không còn hợp lệ (an toàn dữ liệu)."""
    unlocked = set(data.get("unlocked_skills", []))
    equipped = data.get("equipped_skills", [None] * SKILL_SLOTS)
    equipped = (list(equipped) + [None] * SKILL_SLOTS)[:SKILL_SLOTS]
    return [SKILLS.get(key) if key in unlocked else None for key in equipped]
