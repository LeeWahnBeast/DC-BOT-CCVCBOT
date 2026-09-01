"""
skill_data.py
=============
Kỹ năng câu cá — dùng trong ván kéo cá (xem ReelView trong fishing_cog.py).
Skill giờ được chia thành 4 NHÓM ĐIẾU PHÁP (SKILL_GROUPS) để hiện trong
"/đồ_câu_lão_bát" theo dạng "chọn nhóm -> xem skill trong nhóm" thay vì liệt
kê hết 1 danh sách dài (xem SkillGroupPickerView/SkillShopView trong
fishing_cog.py):

    1. Giáng Ngư Thập Bát Điếu — 17 chiêu chính, giá 500 nghìn -> 350 triệu.
    2. Thái Cực Điếu Pháp      — 2 chiêu đặc biệt.
    3. Thất Thương Điếu Pháp   — 4 chiêu (Tâm/Cản/Tưởng/Tử Thương).
    4. Thục Đạo Sơn Điếu Pháp  — 4 chiêu (Can Môn Đương/Quan/Khai/Đoạn).

TRANG BỊ
--------
Mỗi người chơi mặc định có SKILL_SLOTS_BASE = 3 ô trang bị
(data["equipped_skills"]), mỗi ô chứa 1 skill_key hoặc None. Skill phải
được mua/mở khóa (data["unlocked_skills"]) trước khi trang bị được vào ô.
Có thể trang bị skill từ BẤT KỲ nhóm nào vào cùng lúc — nhóm chỉ để phân
loại hiển thị trong shop, KHÔNG giới hạn ô trang bị theo nhóm.

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
Mỗi skill dùng lại được VÔ HẠN LẦN trong 1 ván kéo cá, chỉ cần hồi xong
cooldown (`cooldown_s`) và đủ năng lượng — xem ReelView.skill_cooldown_until
trong fishing_cog.py. Dùng tốn `energy_cost` thể lực ngay khi dùng.

CÁC LOẠI HIỆU ỨNG (`effect`)
----------------------------
- "reduce_tension": trừ NGAY `value` % độ căng dây hiện tại.
- "slow_tension": trong `duration_s` giây kế tiếp, độ căng dây tăng chậm
  hơn theo hệ số `value` (áp dụng cả lúc bấm "Kéo!" lẫn lúc đứng yên).
- "reduce_then_slow": vừa trừ ngay `value` % độ căng dây, vừa làm chậm
  `slow_value` % tốc độ tăng độ căng dây trong `duration_s` giây kế tiếp.
- "boost_pull": nhân lực kéo của cần đang dùng lên `value` lần trong
  `duration_s` giây kế tiếp (áp dụng cho mỗi lần bấm "Kéo!" trong lúc đó).
- "boost_pull_and_slow": boost_pull + slow_tension cùng lúc, cùng
  `duration_s` (value = hệ số nhân lực kéo, slow_value = % làm chậm).
- "boost_pull_and_reduce": boost_pull trong `duration_s` giây (value = hệ
  số nhân lực kéo) VÀ đồng thời trừ ngay `reduce_value` % độ căng dây.
- "damage_value": gây sát thương ngay bằng `value` LẦN lực kéo của cần
  đang dùng (rod.pull * value, KHÔNG theo % máu cá) — có tỉ lệ TRƯỢT
  (xem fishing_cog.INSTANT_FINISH_MISS_CHANCE), trượt thì coi như hụt
  (không mất cá).
- "damage_value_sure": giống "damage_value" nhưng CHẮC CHẮN TRÚNG, không
  có tỉ lệ trượt (dùng cho Đả Ngư Bổng Pháp).
- "slow_then_damage_value": làm chậm `value` % tốc độ tăng độ căng dây
  trong `duration_s` giây, sau đó (hết hiệu lực) gây sát thương ngay bằng
  `bonus_damage_value` lần lực kéo của cần — có tỉ lệ TRƯỢT như trên.
- "reduce_slow_then_damage_value": trừ ngay `reduce_value` % độ căng dây,
  đồng thời làm chậm `value` % tốc độ tăng độ căng dây trong `duration_s`
  giây, sau đó gây sát thương ngay bằng `bonus_damage_value` lần lực kéo
  của cần — có tỉ lệ TRƯỢT như trên.
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

# -- 4 nhóm điếu pháp, đúng thứ tự hiện trong màn "Chọn Nhóm" của shop -----
GROUP_GIANG_NGU = "Giáng Ngư Thập Bát Điếu"
GROUP_THAI_CUC = "Thái Cực Điếu Pháp"
GROUP_THAT_THUONG = "Thất Thương Điếu Pháp"
GROUP_THUC_DAO_SON = "Thục Đạo Sơn Điếu Pháp"

SKILL_GROUPS: list[str] = [
    GROUP_GIANG_NGU, GROUP_THAI_CUC, GROUP_THAT_THUONG, GROUP_THUC_DAO_SON,
]
GROUP_EMOJIS: dict[str, str] = {
    GROUP_GIANG_NGU: "🎣",
    GROUP_THAI_CUC: "☯️",
    GROUP_THAT_THUONG: "💔",
    GROUP_THUC_DAO_SON: "🚪",
}


@dataclass(frozen=True)
class Skill:
    key: str
    name: str
    emoji: str
    group: str
    effect: str
    value: float = 0.0        # ý nghĩa tùy `effect` — xem docstring đầu file
    energy_cost: int = 0        # thể lực tiêu hao MỖI LẦN dùng
    price_vang: int = 0          # giá mở khóa
    duration_s: int = 0            # slow_tension/boost_pull/... và các effect kết hợp
    description: str = ""
    slow_value: float = 0.0          # % làm chậm phụ (reduce_then_slow, boost_pull_and_slow)
    reduce_value: float = 0.0          # % trừ ngay phụ (boost_pull_and_reduce, reduce_slow_then_damage_value)
    bonus_damage_value: float = 0.0      # hệ số lực kéo gây thêm khi hết hiệu lực (slow_then_damage_value/reduce_slow_then_damage_value)
    cooldown_s: float = 0.0                # thời gian hồi chiêu (giây) TRƯỚC KHI dùng lại được
        # skill này trong CÙNG 1 ván câu — không giới hạn số lần dùng/ván,
        # skill nào cũng dùng lại VÔ HẠN LẦN, chỉ cần hồi xong cooldown (và
        # đủ năng lượng) — xem ReelView._on_skill/skill_cooldown_until
        # trong fishing_cog.py.


SKILL_SHOP: list[Skill] = [
    # =======================================================================
    # 1) GIÁNG NGƯ THẬP BÁT ĐIẾU — 17 chiêu chính, giá 500 nghìn -> 350 triệu.
    # =======================================================================
    Skill(
        key="vung_nhu_cho_gia", name="Vững Như Chó Già", emoji="🐕", group=GROUP_GIANG_NGU,
        effect="slow_tension", value=0.10, duration_s=5,
        energy_cost=20, cooldown_s=5, price_vang=500_000,
        description="Ghì chặt cần câu như chó già bám đất, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        key="ma_dat_dieu_phap", name="Mã Đạt Điếu Pháp", emoji="🪢", group=GROUP_GIANG_NGU,
        effect="boost_pull", value=2.0, duration_s=5,
        energy_cost=50, cooldown_s=9, price_vang=3_000_000,
        description="Vung cần theo thế ngựa phi, nhân đôi lực kéo của cần đang dùng trong ít giây.",
    ),
    Skill(
        key="dai_ma_bai_thoai", name="Đại Ma Bại Thoái", emoji="🌀", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.20,
        energy_cost=30, cooldown_s=7, price_vang=5_000_000,
        description="Giật lùi dây câu, ép con mồi lùi bước, trừ ngay một phần độ căng dây.",
    ),
    Skill(
        key="soai_ca_ha_son", name="Soái Ca Hạ Sơn", emoji="🏔️", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.40,
        energy_cost=40, cooldown_s=8, price_vang=6_000_000,
        description="Giật mạnh dây câu như hạ sơn thị uy, trừ ngay khá nhiều độ căng dây hiện tại.",
    ),
    Skill(
        key="hoi_thu_thao", name="Hồi Thủ Thao", emoji="🤲", group=GROUP_GIANG_NGU,
        effect="slow_tension", value=0.25, duration_s=3,
        energy_cost=25, cooldown_s=8, price_vang=8_000_000,
        description="Thu tay đúng nhịp, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        key="lao_han_dap_xe", name="Lão Hán Đạp Xe", emoji="🚲", group=GROUP_GIANG_NGU,
        effect="slow_tension", value=0.30, duration_s=3,
        energy_cost=28, cooldown_s=9, price_vang=10_000_000,
        description="Đạp đều như lão hán đạp xe, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        key="phi_thien_vo_cuc_dieu", name="Phi Thiên Vô Cực Điếu", emoji="🕊️", group=GROUP_GIANG_NGU,
        effect="slow_tension", value=0.40, duration_s=4,
        energy_cost=40, cooldown_s=12, price_vang=14_000_000,
        description="Kéo dây câu bay bổng vô cực, giữ dây câu căng chậm lại hẳn trong ít giây.",
    ),
    Skill(
        key="lao_nai_nai_toan_bi_oa", name="Lão Nãi Nãi Toàn Bị Oa", emoji="👵", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.50,
        energy_cost=50, cooldown_s=15, price_vang=22_000_000,
        description="Kéo mạnh dây câu bằng công phu lão luyện, trừ ngay phần lớn độ căng dây.",
    ),
    Skill(
        key="te_thien_dai_dieu", name="Tề Thiên Đại Điếu", emoji="🐵", group=GROUP_GIANG_NGU,
        effect="slow_tension", value=0.50, duration_s=3,
        energy_cost=60, cooldown_s=15, price_vang=30_000_000,
        description="Đại náo như Tề Thiên, giữ dây câu căng chậm lại rất nhiều trong ít giây.",
    ),
    Skill(
        key="cong_ke_ha_dan", name="Công Kê Hạ Đản", emoji="🐓", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.55,
        energy_cost=55, cooldown_s=14, price_vang=26_000_000,
        description="Giật mạnh dây câu dứt khoát, trừ ngay khá nhiều độ căng dây hiện tại.",
    ),
    Skill(
        key="dieu_long_ban_ho", name="Điếu Long Bàn Hổ", emoji="🐉", group=GROUP_GIANG_NGU,
        effect="boost_pull_and_slow", value=2.5, slow_value=0.30, duration_s=5,
        energy_cost=70, cooldown_s=18, price_vang=50_000_000,
        description="Thế rồng cuộn hổ chầu, vừa tăng mạnh lực kéo vừa giữ dây câu căng chậm lại.",
    ),
    Skill(
        key="hoanh_tao_thien_quan", name="Hoành Tảo Thiên Quân", emoji="⚔️", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.70,
        energy_cost=80, cooldown_s=18, price_vang=60_000_000,
        description="Giật mạnh dây câu quét ngang vạn quân, trừ ngay rất nhiều độ căng dây.",
    ),
    Skill(
        key="xuyen_thien_hau_chi_dieu", name="Xuyên Thiên Hầu Chi Điếu", emoji="🐒", group=GROUP_GIANG_NGU,
        effect="boost_pull_and_reduce", value=3.0, reduce_value=0.60, duration_s=3,
        energy_cost=90, cooldown_s=20, price_vang=80_000_000,
        description="Kéo dây câu siêu mạnh xuyên thấu trời cao, vừa tăng lực kéo vừa trừ ngay độ căng dây.",
    ),
    Skill(
        key="da_ngu_bong_phap", name="Đả Ngư Bổng Pháp", emoji="💥", group=GROUP_GIANG_NGU,
        effect="damage_value_sure", value=2.5,
        energy_cost=140, cooldown_s=22, price_vang=120_000_000,
        description="Giáng bổng pháp thẳng vào con mồi, chắc chắn gây sát thương bằng lực kéo của cần.",
    ),
    Skill(
        key="hoi_anh_chi_thu", name="Hồi Ảnh Chi Thủ", emoji="🔄", group=GROUP_GIANG_NGU,
        effect="reduce_tension", value=0.80,
        energy_cost=150, cooldown_s=25, price_vang=180_000_000,
        description="Kéo dây câu cực mạnh bằng thủ pháp xoay ảnh, trừ ngay phần lớn độ căng dây.",
    ),
    Skill(
        key="khai_thien_mon", name="Khai Thiên Môn", emoji="🌌", group=GROUP_GIANG_NGU,
        effect="damage_value", value=5.0,
        energy_cost=250, cooldown_s=30, price_vang=250_000_000,
        description="Dồn hết nội lực, \"một cần mở toang cổng trời\", đập thẳng cá vào bờ.",
    ),
    Skill(
        key="pha_phu_tram_chu", name="Phá Phủ Trầm Chu", emoji="⚓", group=GROUP_GIANG_NGU,
        effect="damage_value", value=6.0,
        energy_cost=350, cooldown_s=30, price_vang=350_000_000,
        description="Đập vỡ thuyền chìm xuồng, dồn toàn lực kết liễu con mồi.",
    ),

    # =======================================================================
    # 2) THÁI CỰC ĐIẾU PHÁP
    # =======================================================================
    Skill(
        key="thai_cuc_dieu_phap", name="Thái Cực Điếu Pháp", emoji="☯️", group=GROUP_THAI_CUC,
        effect="slow_then_damage_value", value=0.40, duration_s=6, bonus_damage_value=8.0,
        energy_cost=500, cooldown_s=30, price_vang=500_000_000,
        description=(
            "Vận chuyển âm dương: giữ dây câu căng chậm lại hẳn, tích lực cho một đòn "
            "phản kích cực mạnh ngay khi hiệu lực kết thúc."
        ),
    ),
    Skill(
        key="can_khon_dai_na_ngu", name="Càn Khôn Đại Na Ngư", emoji="🌪️", group=GROUP_THAI_CUC,
        effect="reduce_tension", value=0.85,
        energy_cost=175, cooldown_s=30, price_vang=200_000_000,
        description="Xoay chuyển càn khôn dịch chuyển cả con mồi, trừ ngay gần hết độ căng dây.",
    ),

    # =======================================================================
    # 3) THẤT THƯƠNG ĐIẾU PHÁP (Tâm/Cản/Tưởng/Tử Thương)
    # =======================================================================
    Skill(
        key="tam_thuong", name="Tâm Thương", emoji="💔", group=GROUP_THAT_THUONG,
        effect="damage_value", value=3.5,
        energy_cost=180, cooldown_s=20, price_vang=160_000_000,
        description="Đòn đầu tiên của Thất Thương Quyền, tổn thương tận tâm can con mồi.",
    ),
    Skill(
        key="can_thuong", name="Cản Thương", emoji="🛡️", group=GROUP_THAT_THUONG,
        effect="reduce_tension", value=0.45,
        energy_cost=55, cooldown_s=12, price_vang=10_000_000,
        description="Giật dây câu ngăn cản đà tiến của cá, trừ ngay một phần độ căng dây.",
    ),
    Skill(
        key="tuong_thuong", name="Tưởng Thương", emoji="🧠", group=GROUP_THAT_THUONG,
        effect="slow_tension", value=0.35, duration_s=3,
        energy_cost=30, cooldown_s=10, price_vang=12_000_000,
        description="Đánh vào tâm trí con mồi, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        key="tu_thuong", name="Tử Thương", emoji="☠️", group=GROUP_THAT_THUONG,
        effect="reduce_tension", value=0.70,
        energy_cost=90, cooldown_s=20, price_vang=70_000_000,
        description="Đòn chí mạng cuối cùng của Thất Thương Quyền, trừ ngay rất nhiều độ căng dây.",
    ),

    # =======================================================================
    # 4) THỤC ĐẠO SƠN ĐIẾU PHÁP (Can Môn Đương/Quan/Khai/Đoạn)
    # =======================================================================
    Skill(
        key="can_mon_duong", name="Can Môn Đương", emoji="🚪", group=GROUP_THUC_DAO_SON,
        effect="slow_tension", value=0.30, duration_s=4,
        energy_cost=40, cooldown_s=12, price_vang=14_000_000,
        description="Trấn giữ cửa ải Can Môn, giữ dây câu căng chậm lại trong ít giây.",
    ),
    Skill(
        key="can_mon_quan", name="Can Môn Quan", emoji="🗝️", group=GROUP_THUC_DAO_SON,
        effect="reduce_then_slow", value=0.30, slow_value=0.40, duration_s=6,
        energy_cost=60, cooldown_s=18, price_vang=60_000_000,
        description="Vừa giật vừa kéo phá cửa ải Can Môn, trừ ngay độ căng dây và làm chậm tốc độ tăng tiếp theo.",
    ),
    Skill(
        key="can_mon_khai", name="Can Môn Khai", emoji="🔨", group=GROUP_THUC_DAO_SON,
        effect="damage_value", value=5.5,
        energy_cost=300, cooldown_s=25, price_vang=280_000_000,
        description="Phá tan cửa ải Can Môn, dồn toàn lực đập cá.",
    ),
    Skill(
        key="can_mon_doan", name="Can Môn Đoạn", emoji="🌋", group=GROUP_THUC_DAO_SON,
        effect="reduce_slow_then_damage_value", reduce_value=0.30, value=0.50, duration_s=3,
        bonus_damage_value=10.0,
        energy_cost=750, cooldown_s=30, price_vang=750_000_000,
        description=(
            "Chiêu cuối cùng của Thục Đạo Sơn: dứt luôn cửa ải Can Môn — trừ ngay độ căng dây, "
            "giữ dây căng chậm lại, rồi dồn toàn lực giáng đòn kết liễu."
        ),
    ),
]

SKILLS: dict[str, Skill] = {s.key: s for s in SKILL_SHOP}


def skills_in_group(group: str) -> list[Skill]:
    """Danh sách skill thuộc 1 nhóm điếu pháp, giữ nguyên thứ tự trong
    SKILL_SHOP — dùng cho màn xem skill theo nhóm trong shop."""
    return [s for s in SKILL_SHOP if s.group == group]


def describe_effect(skill: Skill, miss_chance: float = 0.30) -> str:
    """Trả về 1 dòng mô tả hiệu ứng của `skill` bằng tiếng Việt, dùng chung
    cho mọi nơi hiển thị skill (shop, tooltip...). `miss_chance` = tỉ lệ
    TRƯỢT của các effect damage_value/... có ăn may (khớp
    fishing_cog.INSTANT_FINISH_MISS_CHANCE, mặc định 30%)."""
    hit_pct = f"{1 - miss_chance:.0%}"
    if skill.effect == "reduce_tension":
        return f"Trừ ngay `{skill.value:.0%}` độ căng dây khi dùng."
    if skill.effect == "slow_tension":
        return f"Giảm `{skill.value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s`."
    if skill.effect == "reduce_then_slow":
        return (
            f"Trừ ngay `{skill.value:.0%}` độ căng dây, đồng thời giảm "
            f"`{skill.slow_value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s` kế tiếp."
        )
    if skill.effect == "boost_pull":
        return f"Nhân lực kéo của cần đang dùng lên `{skill.value:.1f}x` trong `{skill.duration_s}s`."
    if skill.effect == "boost_pull_and_slow":
        return (
            f"Nhân lực kéo của cần đang dùng lên `{skill.value:.1f}x`, đồng thời giảm "
            f"`{skill.slow_value:.0%}` tốc độ tăng độ căng dây, cả hai trong `{skill.duration_s}s`."
        )
    if skill.effect == "boost_pull_and_reduce":
        return (
            f"Nhân lực kéo của cần đang dùng lên `{skill.value:.1f}x` trong `{skill.duration_s}s`, "
            f"đồng thời trừ ngay `{skill.reduce_value:.0%}` độ căng dây khi dùng."
        )
    if skill.effect == "damage_value":
        return (
            f"Gây sát thương ngay bằng `{skill.value:.1f}x` lực kéo của cần đang dùng — có "
            f"`{hit_pct}` cơ hội trúng đòn, nếu trượt thì coi như hụt (không mất cá)."
        )
    if skill.effect == "damage_value_sure":
        return (
            f"Gây sát thương ngay bằng `{skill.value:.1f}x` lực kéo của cần đang dùng — "
            f"chắc chắn trúng, không có tỉ lệ trượt."
        )
    if skill.effect == "slow_then_damage_value":
        return (
            f"Giảm `{skill.value:.0%}` tốc độ tăng độ căng dây trong `{skill.duration_s}s`. Sau khi "
            f"hiệu lực kết thúc, gây sát thương ngay bằng `{skill.bonus_damage_value:.1f}x` lực kéo "
            f"của cần đang dùng — có `{hit_pct}` cơ hội trúng đòn, nếu trượt thì coi như hụt."
        )
    if skill.effect == "reduce_slow_then_damage_value":
        return (
            f"Trừ ngay `{skill.reduce_value:.0%}` độ căng dây, đồng thời giảm `{skill.value:.0%}` "
            f"tốc độ tăng độ căng dây trong `{skill.duration_s}s` kế tiếp, sau đó gây sát thương ngay "
            f"bằng `{skill.bonus_damage_value:.1f}x` lực kéo của cần — có `{hit_pct}` cơ hội trúng đòn, "
            f"nếu trượt thì coi như hụt."
        )
    return skill.description


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
