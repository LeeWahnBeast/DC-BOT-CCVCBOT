"""
skill_data.py
=============
Kỹ năng câu cá — dùng trong ván kéo cá (xem ReelView trong fishing_cog.py).
Bộ skill "GIÁNG NGƯ THẬP BÁT ĐIẾU" (17 chiêu chính) + các chiêu đặc biệt
(Thái Cực Điếu Pháp, Càn Khôn Đại Na Ngư, Toàn Chân Điếu Pháp, Bắc Minh
Điếu Pháp, bộ Thục Đạo Sơn Điếu Pháp: Can Môn Đương/Quan/Khai, bộ Thất
Thương Điếu Pháp: Tâm/Cản/Tưởng/Tử Thương) — lấy theo đúng game gốc "Câu
Cá Vạn Cân", KHÔNG còn skill tự chế như bộ cũ.

TRANG BỊ
--------
Mỗi người chơi mặc định có SKILL_SLOTS_BASE = 3 ô trang bị
(data["equipped_skills"]), mỗi ô chứa 1 skill_key hoặc None. Skill phải
được mua/mở khóa (data["unlocked_skills"]) trước khi trang bị được vào ô.

MUA THÊM Ô (data["extra_skill_slots"])
---------------------------------------
Người chơi có thể MUA THÊM ô trang bị (ngoài 3 ô mặc định) bằng Vàng.
Số ô đã mua thêm lưu ở data["extra_skill_slots"] (int, mặc định 0).
Giá ô thứ (n+1) TĂNG DẦN 50 triệu mỗi ô đã mua:
    ô thêm thứ 1: 50.000.000
    ô thêm thứ 2: 100.000.000
    ô thêm thứ 3: 150.000.000
    ...
Dùng slot_count(data) để lấy tổng số ô hiện có, next_slot_price(data) để
lấy giá mua ô kế tiếp — xem 2 hàm bên dưới.

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
from typing import Optional

SKILL_SLOTS = 3   # (GIỮ TÊN CŨ để tương thích ngược) số ô mặc định mỗi người chơi
SKILL_SLOTS_BASE = SKILL_SLOTS

# Giá mua ô trang bị THÊM (ngoài SKILL_SLOTS_BASE), tăng dần mỗi ô đã mua.
EXTRA_SLOT_BASE_PRICE = 50_000_000
# Không giới hạn cứng số ô có thể mua thêm — để None nếu không muốn chặn.
MAX_EXTRA_SLOTS: int | None = None


@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    emoji: str
    # "reduce_tension" | "slow_tension" | "instant_finish" | "damage_fish_hp"
    # | "damage_value" (gây sát thương ngay bằng `value` LẦN lực kéo của
    #   cần đang dùng — rod.pull * value — KHÔNG theo % máu tối đa của cá
    #   như damage_fish_hp/instant_finish, để cá boss máu buff cao không
    #   còn bị 1 chiêu kết liễu ngay. Có tỉ lệ TRƯỢT INSTANT_FINISH_MISS_CHANCE
    #   giống instant_finish. Dùng cho bộ "Đập cá" cấp cao: Khai Thiên Môn,
    #   Phá Phủ Trầm Chu, Càn Môn Khai, Bắc Minh Điếu Pháp, Tâm Thương)
    # | "slow_then_damage" (kết hợp: giảm tốc tăng dây trong duration_s giây,
    #   HẾT hiệu lực thì gây thêm sát thương bonus_damage_pct lên máu cá)
    # | "reduce_then_slow" (kết hợp "Giật + Kéo": trừ ngay `value`% độ căng
    #   dây VÀ đồng thời làm chậm tốc độ tăng dây `slow_value`% trong
    #   duration_s giây kế tiếp — không gây thêm sát thương cá)
    effect: str
    value: float             # reduce_tension/slow_tension: %; damage_fish_hp: % máu cá tối đa; damage_value: số lần lực kéo (rod.pull); reduce_then_slow: % trừ ngay
    energy_cost: int          # thể lực tiêu hao MỖI LẦN dùng
    price_vang: int            # giá mở khóa, quy về giá triệu (bội số 1.000.000)
    duration_s: int = 0          # áp dụng cho slow_tension / slow_then_damage / reduce_then_slow
    description: str = ""
    uses_per_session: int = 1     # số lần dùng được tối đa trong 1 ván câu
    bonus_damage_pct: float = 0.0   # chỉ dùng cho "slow_then_damage": % máu cá gây thêm khi hiệu lực slow kết thúc
    slow_value: float = 0.0          # chỉ dùng cho "reduce_then_slow": % làm chậm tốc độ tăng dây
    cooldown_s: float = 0.0           # thời gian hồi chiêu (giây) TRƯỚC KHI dùng lại được
        # skill này trong CÙNG 1 ván câu — 0 nghĩa là không có hồi chiêu
        # riêng (chỉ bị chặn bởi uses_per_session như cũ). Skill nào có
        # cooldown_s > 0 nên đặt uses_per_session > 1 (vd 5) để hồi chiêu
        # thực sự là ĐIỀU KIỆN CHÍNH giới hạn việc dùng lại, không phải
        # uses_per_session nữa — xem ReelView._on_skill/skill_cooldown_until.


SKILL_SHOP: list[Skill] = [
    # =======================================================================
    # GIÁNG NGƯ THẬP BÁT ĐIẾU — bộ 17 chiêu chính (theo game gốc), giá tăng
    # dần 2 triệu -> 300 triệu theo đúng thứ tự & độ mạnh Vàng/thể lực đưa
    # ra. Quy ước hiệu ứng:
    #   "Giữ"          -> slow_tension (làm chậm tốc độ tăng căng dây)
    #   "Giật"/"Kéo"   -> reduce_tension (trừ ngay % căng dây), mức % tăng
    #                     dần theo thứ tự nhẹ/mạnh/cực mạnh/siêu mạnh
    #   "Đập cá"       -> instant_finish (xem INSTANT_FINISH_MISS_CHANCE ở
    #                     fishing_cog.py — có tỉ lệ TRƯỢT, không còn ăn
    #                     chắc 100% như trước)
    # =======================================================================
    Skill(
        "vung_nhu_cho_gia", "Vững Như Chó Già", "🐕", "slow_tension", 0.25, 15, 2_000_000,
        cooldown_s=6, uses_per_session=5,
        duration_s=5,
        description="Ghì chặt cần câu như chó già bám đất, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        "ma_dat_dieu_phap", "Mã Đạt Điếu Pháp", "🪢", "reduce_tension", 0.20, 15, 6_000_000,
        cooldown_s=6, uses_per_session=5,
        description="Giật nhẹ dây câu đúng lúc, trừ ngay một phần nhỏ độ căng dây hiện tại.",
    ),
    Skill(
        "dai_ma_bai_thoai", "Đại Ma Bại Thoái", "🌀", "reduce_tension", 0.22, 18, 10_000_000,
        cooldown_s=7, uses_per_session=5,
        description="Giật lùi dây câu, ép con mồi lùi bước, trừ ngay một phần độ căng dây.",
    ),
    Skill(
        "soai_ca_ha_son", "Soái Ca Hạ Sơn", "🏔️", "reduce_tension", 0.40, 25, 16_000_000,
        cooldown_s=10, uses_per_session=5,
        description="Giật mạnh dây câu như hạ sơn thị uy, trừ ngay khá nhiều độ căng dây hiện tại.",
    ),
    Skill(
        "hoi_thu_thao", "Hồi Thủ Thao", "🤲", "reduce_tension", 0.30, 22, 22_000_000,
        cooldown_s=9, uses_per_session=5,
        description="Kéo dây câu về đúng nhịp, trừ ngay một phần độ căng dây hiện tại.",
    ),
    Skill(
        "lao_han_dap_xe", "Lão Hán Đạp Xe", "🚲", "reduce_tension", 0.32, 24, 28_000_000,
        cooldown_s=10, uses_per_session=5,
        description="Kéo dây câu đều đặn như đạp xe của lão hán, trừ ngay một phần độ căng dây.",
    ),
    Skill(
        "phi_thien_vo_cuc_dieu", "Phi Thiên Vô Cực Điếu", "🕊️", "reduce_tension", 0.35, 26, 35_000_000,
        cooldown_s=10, uses_per_session=5,
        description="Kéo dây câu bay bổng vô cực, trừ ngay một phần kha khá độ căng dây.",
    ),
    Skill(
        "lao_nai_nai_toan_bi_oa", "Lão Nãi Nãi Toàn Bị Oa", "👵", "reduce_tension", 0.50, 35, 45_000_000,
        cooldown_s=14, uses_per_session=5,
        description="Kéo mạnh dây câu bằng công phu lão luyện, trừ ngay phần lớn độ căng dây.",
    ),
    Skill(
        "te_thien_dai_dieu", "Tề Thiên Đại Điếu", "🐒", "reduce_tension", 0.52, 36, 55_000_000,
        cooldown_s=14, uses_per_session=5,
        description="Kéo mạnh dây câu như Tề Thiên đại náo, trừ ngay phần lớn độ căng dây.",
    ),
    Skill(
        "cong_ke_ha_dan", "Công Kê Hạ Đản", "🐓", "reduce_tension", 0.42, 28, 65_000_000,
        cooldown_s=11, uses_per_session=5,
        description="Giật mạnh dây câu dứt khoát, trừ ngay khá nhiều độ căng dây hiện tại.",
    ),
    Skill(
        "dieu_long_ban_ho", "Điếu Long Bàn Hổ", "🐉", "reduce_tension", 0.45, 30, 80_000_000,
        cooldown_s=12, uses_per_session=5,
        description="Giật mạnh dây câu thế rồng cuộn hổ chầu, trừ ngay khá nhiều độ căng dây.",
    ),
    Skill(
        "hoanh_tao_thien_quan", "Hoành Tảo Thiên Quân", "⚔️", "reduce_tension", 0.48, 32, 95_000_000,
        cooldown_s=13, uses_per_session=5,
        description="Giật mạnh dây câu quét ngang vạn quân, trừ ngay khá nhiều độ căng dây.",
    ),
    Skill(
        "xuyen_thien_hau_chi_dieu", "Xuyên Thiên Hầu Chi Điếu", "🐒", "reduce_tension", 0.65, 45, 115_000_000,
        cooldown_s=18, uses_per_session=5,
        description="Kéo dây câu siêu mạnh xuyên thấu trời cao, trừ ngay rất nhiều độ căng dây.",
    ),
    Skill(
        "da_ngu_bong_phap", "Đả Ngư Bổng Pháp", "💥", "reduce_tension", 0.55, 38, 135_000_000,
        cooldown_s=15, uses_per_session=5,
        description="Giật mạnh dây câu bằng bổng pháp, trừ ngay phần lớn độ căng dây hiện tại.",
    ),
    Skill(
        "hoi_anh_chi_thu", "Hồi Ảnh Chi Thủ", "🔄", "reduce_tension", 0.60, 42, 160_000_000,
        cooldown_s=17, uses_per_session=5,
        description="Kéo dây câu cực mạnh bằng thủ pháp xoay ảnh, trừ ngay phần lớn độ căng dây.",
    ),
    Skill(
        "khai_thien_mon", "Khai Thiên Môn", "🌌", "damage_value", 4.0, 100, 220_000_000,
        description=(
            "Dồn hết nội lực, \"một cần mở toang cổng trời\", đập thẳng cá vào bờ — "
            "gây sát thương ngay bằng `4.0x` lực kéo của cần."
        ),
    ),
    Skill(
        "pha_phu_tram_chu", "Phá Phủ Trầm Chu", "⚓", "damage_value", 5.5, 110, 300_000_000,
        description=(
            "Đập vỡ thuyền chìm xuồng, dồn toàn lực kết liễu con mồi — "
            "gây sát thương ngay bằng `5.5x` lực kéo của cần."
        ),
    ),

    # =======================================================================
    # CÁC CHIÊU ĐẶC BIỆT — mạnh hơn hẳn Thập Bát Điếu, giá 150tr -> 500tr.
    # =======================================================================
    Skill(
        "thai_cuc_dieu_phap", "Thái Cực Điếu Pháp", "☯️", "slow_then_damage", 0.55, 300, 350_000_000,
        duration_s=6, bonus_damage_pct=0.25,
        description=(
            "Vận chuyển âm dương: vừa kéo dây câu mạnh làm chậm hẳn tốc độ tăng căng "
            "dây, vừa tích lực cho một đòn \"đập cá\" phản kích ngay khi hiệu lực kết thúc."
        ),
    ),
    Skill(
        "can_khon_dai_na_ngu", "Càn Khôn Đại Na Ngư", "🌪️", "reduce_tension", 0.70, 48, 250_000_000,
        cooldown_s=19, uses_per_session=5,
        description="Kéo dây câu cực mạnh, xoay chuyển càn khôn dịch chuyển cả con mồi, trừ ngay rất nhiều độ căng dây.",
    ),
    Skill(
        "toan_chan_dieu_phap", "Toàn Chân Điếu Pháp", "🧘", "reduce_tension", 0.58, 40, 180_000_000,
        cooldown_s=16, uses_per_session=5,
        description="Kéo dây câu mạnh theo tâm pháp Toàn Chân, trừ ngay phần lớn độ căng dây hiện tại.",
    ),
    Skill(
        "bac_minh_dieu_phap", "Bắc Minh Điếu Pháp", "🐋", "damage_value", 7.0, 120, 400_000_000,
        description=(
            "Hấp thụ nội lực biển Bắc Minh, dồn toàn lực đập cá — "
            "gây sát thương ngay bằng `7.0x` lực kéo của cần."
        ),
    ),

    # -- Thục Đạo Sơn Điếu Pháp (bộ 3 chiêu: Đương/Quan/Khai) --------------
    Skill(
        "can_mon_duong", "Can Môn Đương", "🚪", "slow_tension", 0.55, 30, 150_000_000,
        cooldown_s=12, uses_per_session=5,
        duration_s=8,
        description="Trấn giữ cửa ải Can Môn, giữ dây câu căng chậm lại hẳn trong ít giây.",
    ),
    Skill(
        "can_mon_quan", "Can Môn Quan", "🗝️", "reduce_then_slow", 0.35, 40, 210_000_000,
        cooldown_s=16, uses_per_session=5,
        duration_s=6, slow_value=0.40,
        description="Vừa giật vừa kéo phá cửa ải Can Môn, trừ ngay một phần độ căng dây và làm chậm tốc độ tăng tiếp theo.",
    ),
    Skill(
        "can_mon_khai", "Can Môn Khai", "💥", "damage_value", 6.0, 115, 320_000_000,
        description=(
            "Phá tan cửa ải Can Môn, dồn toàn lực đập cá — "
            "gây sát thương ngay bằng `6.0x` lực kéo của cần."
        ),
    ),

    # -- Thất Thương Điếu Pháp (bộ 4 chiêu: Tâm/Cản/Tưởng/Tử Thương) -------
    Skill(
        "tam_thuong", "Tâm Thương", "💔", "damage_value", 8.0, 130, 450_000_000,
        description=(
            "Đòn đầu tiên của Thất Thương Quyền, tổn thương tận tâm can, dồn toàn lực "
            "đập cá — gây sát thương ngay bằng `8.0x` lực kéo của cần."
        ),
    ),
    Skill(
        "can_thuong", "Cản Thương", "🛡️", "reduce_tension", 0.38, 26, 120_000_000,
        cooldown_s=10, uses_per_session=5,
        description="Giật dây câu ngăn cản đà tiến của cá, trừ ngay một phần độ căng dây hiện tại.",
    ),
    Skill(
        "tuong_thuong", "Tưởng Thương", "🧠", "reduce_tension", 0.44, 30, 145_000_000,
        cooldown_s=12, uses_per_session=5,
        description="Kéo dây câu đánh vào tâm trí con mồi, trừ ngay khá nhiều độ căng dây hiện tại.",
    ),
    Skill(
        "tu_thuong", "Tử Thương", "☠️", "reduce_tension", 0.68, 46, 500_000_000,
        cooldown_s=18, uses_per_session=5,
        description="Giật mạnh dây câu đòn chí mạng cuối cùng của Thất Thương Quyền, trừ ngay gần hết độ căng dây.",
    ),
]

SKILLS: dict[str, Skill] = {s.key: s for s in SKILL_SHOP}


def slot_count(data: dict) -> int:
    """Tổng số ô trang bị hiện có của người chơi = mặc định + số ô đã mua
    thêm (data["extra_skill_slots"], mặc định 0 nếu chưa từng mua)."""
    extra = int(data.get("extra_skill_slots", 0) or 0)
    return SKILL_SLOTS_BASE + max(0, extra)


def next_slot_price(data: dict) -> Optional[int]:
    """Giá (Vàng) để mua ô trang bị KẾ TIẾP. Trả None nếu đã đạt
    MAX_EXTRA_SLOTS (không mua thêm được nữa)."""
    extra = int(data.get("extra_skill_slots", 0) or 0)
    if MAX_EXTRA_SLOTS is not None and extra >= MAX_EXTRA_SLOTS:
        return None
    return EXTRA_SLOT_BASE_PRICE * (extra + 1)


def equipped_skill_objects(data: dict) -> list[Skill | None]:
    """Trả về list slot_count(data) phần tử: Skill đã trang bị & còn mở
    khóa, hoặc None cho ô trống / skill không còn hợp lệ (an toàn dữ liệu)."""
    n = slot_count(data)
    unlocked = set(data.get("unlocked_skills", []))
    equipped = data.get("equipped_skills", [None] * n)
    equipped = (list(equipped) + [None] * n)[:n]
    return [SKILLS.get(key) if key in unlocked else None for key in equipped]
