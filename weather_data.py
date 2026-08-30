"""
weather_data.py
================
Hệ thống thời tiết toàn server cho tính năng câu cá. Mỗi giờ bot tự random
1 thời tiết mới (xem WEATHER_LOOP trong fishing_cog.py), lưu vào Firebase
(fishing/weather/current) và thông báo trong kênh thời tiết cố định.

Thời tiết ảnh hưởng tới ván câu đang diễn ra (áp dụng tại thời điểm bấm
/câu_cá, giữ nguyên cho tới khi ván đó kết thúc dù thời tiết đổi giữa chừng):
- luck_delta: cộng thẳng vào luck_bonus (giống mồi câu) — ảnh hưởng sát
  thương kéo + tốc độ tăng độ căng dây.
- tension_mult: nhân thêm vào tốc độ tăng độ căng dây (idle lẫn mỗi lần
  kéo), độc lập với luck_bonus.
- boss_weight_mult: nhân vào trọng số random của các con cá "boss" (cá đắt
  nhất mỗi cấp, xem fish_data.BOSS_FISH_KEYS) khi roll cá — >1 nghĩa là dễ
  gặp cá boss/hiếm hơn.
- junk_chance_delta: cộng thẳng vào tỉ lệ câu ra rác cơ bản (xem
  fishing_cog.BASE_JUNK_CHANCE) — dương nghĩa là thời tiết đó làm dễ câu
  ra rác hơn (nước cạn, giông bão cuốn rác lên...), âm nghĩa là cá cắn
  câu tốt hơn nên ít gặp rác hơn. Kết quả cuối cùng luôn được kẹp về
  [0, junk_chance_cap] trước khi roll (xem fishing_cog.roll_catch).
- junk_chance_cap: trần riêng cho junk_chance_delta của thời tiết này —
  None nghĩa là dùng trần chung fishing_cog.JUNK_CHANCE_CAP (0.35). Chỉ
  cần set khi 1 thời tiết cụ thể (vd Lạnh) được thiết kế để đẩy tỉ lệ ra
  rác cao hơn hẳn mức trần chung.
- tension_break_note: không phải field số liệu — "dây câu dễ đứt hơn"
  được thể hiện qua tension_mult > 1.0 ở trên (tăng tốc độ tăng độ căng
  dây => dễ chạm ngưỡng đứt dây hơn), KHÔNG có field riêng.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Weather:
    key: str
    name: str
    emoji: str
    description: str
    luck_delta: float
    tension_mult: float
    boss_weight_mult: float = 1.0
    junk_chance_delta: float = 0.0
    junk_chance_cap: float | None = None  # None = dùng trần chung JUNK_CHANCE_CAP


WEATHERS: list[Weather] = [
    Weather(
        "mua", "Mưa", "<:mua:1543495250893348874>",
        "Trời đổ mưa, mặt nước xao động khiến cá cắn câu nhạy hơn hẳn.",
        luck_delta=0.10, tension_mult=0.90, junk_chance_delta=-0.05,
    ),
    Weather(
        "giong", "Giông", "<:giong:1543495327749767248>",
        "Giông tố nổi lên, cá phản kháng dữ dội hơn — dây câu dễ căng hơn "
        "nhưng bù lại vận may câu cũng tăng theo. Sóng lớn cũng cuốn theo "
        "kha khá rác trôi nổi.",
        luck_delta=0.20, tension_mult=1.25, junk_chance_delta=0.05,
    ),
    Weather(
        "dem", "Đêm", "<:dem:1543495413170966628>",
        "Màn đêm buông xuống, những con cá lớn thường ẩn mình ban ngày bắt "
        "đầu xuất hiện nhiều hơn.",
        luck_delta=0.05, tension_mult=1.0, boss_weight_mult=1.6, junk_chance_delta=-0.02,
    ),
    Weather(
        "han_han", "Hạn Hán", "<:hanhan:1543495503180992552>",
        "Hạn hán kéo dài, mực nước cạn khiến cá cắn câu kém hẳn đi và lộ ra "
        "toàn rác đáy hồ.",
        luck_delta=-0.15, tension_mult=1.15, junk_chance_delta=0.15,
    ),
    Weather(
        "cau_vong", "Bảy Sắc Cầu Vồng", "<:cauvong:1543495604217581618>",
        "Hiện tượng cực hiếm! Cầu vồng bảy sắc xuất hiện, vận may câu cá "
        "tăng vọt và cá quý hiếm dễ xuất hiện hơn rất nhiều.",
        luck_delta=0.50, tension_mult=0.60, boss_weight_mult=3.0, junk_chance_delta=-0.15,
    ),
    Weather(
        "lanh", "Lạnh", "<:cold:1543495687923306497>",
        "Trời trở lạnh, cá lờ đờ chẳng buồn cắn câu — kéo lên toàn rác là "
        "rác. Tay tê cóng cầm cần không chắc, dây câu cũng dễ đứt hơn hẳn.",
        luck_delta=-0.10, tension_mult=1.20, junk_chance_delta=0.72, junk_chance_cap=0.80,
    ),
    Weather(
        "suong_mu", "Sương Mù", "<:suongmu:1543495786392850572>",
        "Sương mù giăng kín mặt nước, tầm nhìn hạn chế khiến những con cá "
        "to (kể cả boss) lén lút cắn câu mà không ai hay — nhưng cũng vì "
        "không thấy đường mà dây câu dễ đứt hơn.",
        luck_delta=0.0, tension_mult=1.15, boss_weight_mult=2.2, junk_chance_delta=0.0,
    ),
]
WEATHER_BY_KEY: dict[str, Weather] = {w.key: w for w in WEATHERS}

# Trọng số random mỗi giờ — Bảy Sắc Cầu Vồng hiếm nhất.
WEATHER_WEIGHTS: dict[str, float] = {
    "mua": 25.0,
    "giong": 18.0,
    "dem": 20.0,
    "han_han": 15.0,
    "cau_vong": 5.0,
    "lanh": 12.0,
    "suong_mu": 12.0,
}


def roll_weather() -> Weather:
    """Random 1 thời tiết mới theo trọng số ở trên."""
    keys = list(WEATHER_WEIGHTS.keys())
    weights = [WEATHER_WEIGHTS[k] for k in keys]
    key = random.choices(keys, weights=weights)[0]
    return WEATHER_BY_KEY[key]
