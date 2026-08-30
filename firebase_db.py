"""
firebase_db.py
===============
Lớp lưu trữ Firebase Realtime Database dùng riêng cho tính năng câu cá.

CÁCH DÙNG
---------
- Nếu bot chính ĐÃ gọi firebase_admin.initialize_app() ở entrypoint rồi thì
  KHÔNG cần gọi init_firebase() ở đây nữa — chỉ cần import module này, nó
  sẽ tự dùng chung app Firebase đã có sẵn.
- Nếu file này chạy độc lập / cog được load trước khi app init, gọi
  init_firebase() một lần lúc bot khởi động (vd setup_hook / on_ready).

CẤU TRÚC DỮ LIỆU (Realtime Database)
------------------------------------
    fishing/
      users/
        <user_id>/
          vang: int             # Vàng — tiền duy nhất, bán cá / mua cần / mua mồi / mua kỹ năng
          rod: str                 # key cần đang trang bị
          unlocked_rods: [str]      # danh sách key cần đã mở khóa
          inventory: {fish_key: qty}  # kho cá đang giữ, chưa bán
          score: int
          bait: {name, luck, expires_at} | None
          last_cast: float           # epoch giây của lần câu gần nhất
          level: int                  # cấp độ người chơi, bắt đầu từ 1
          exp: int                     # EXP hiện có (đã trừ phần dùng để lên cấp)
          energy: int                  # thể lực hiện có (thanh năng lượng riêng, hao theo lần bấm "Kéo!")
          energy_updated_at: float     # epoch giây lần cuối tính hồi thể lực (dùng để hồi lazy theo thời gian)
          current_map: str | None      # key khu vực câu đang chọn (fish_data.MAPS) — None = câu tất cả khu vực
          unlocked_skills: [str]        # danh sách key skill câu cá đã mở khóa (skill_data.SKILL_SHOP)
          equipped_skills: [str|None]     # 3 ô trang bị skill, mỗi ô None hoặc key skill (skill_data.SKILL_SLOTS)
      codes/
        <code>/
          reward: {vang?, rod?, skill?, bait?}   # xem create_code/redeem_code bên dưới
          max_uses: int | None
          used_by: [str]
          created_by: int
          created_at: float

Đổi DB_ROOT nếu bot đã có sẵn nhánh khác.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import firebase_admin
from firebase_admin import credentials, db

DB_ROOT = "fishing/users"

DEFAULT_ROD_KEY = "nguoi_yeu_cu"

# Điền ID Discord của owner/admin được bypass giá (Vàng vô hạn) + cooldown.
OWNER_IDS: set[int] = {1210771747889090571}


def init_firebase(cred_path: Optional[str] = None, database_url: Optional[str] = None) -> None:
    """Khởi tạo app Firebase nếu chưa có app nào được init trong tiến trình.
    An toàn để gọi nhiều lần / gọi ở nhiều module — chỉ init thật sự 1 lần.

    FIREBASE_CRED_PATH có thể là:
    - đường dẫn tới 1 file JSON credential, HOẶC
    - nội dung JSON credential dán thẳng vào biến môi trường (phổ biến trên
      Render/Railway vì không upload được file kèm code) — hàm tự nhận diện
      bằng cách thử json.loads() trước, thất bại mới coi là đường dẫn file.
    """
    if firebase_admin._apps:
        return
    cred_raw = cred_path or os.environ["FIREBASE_CRED_PATH"]
    database_url = database_url or os.environ["FIREBASE_DB_URL"]

    try:
        cred_dict = json.loads(cred_raw)
        cred = credentials.Certificate(cred_dict)
    except json.JSONDecodeError:
        # Không phải JSON -> coi như đường dẫn file như cũ
        cred = credentials.Certificate(cred_raw)

    firebase_admin.initialize_app(cred, {"databaseURL": database_url})


def _default_data() -> dict:
    return {
        "vang": 0,
        "rod": DEFAULT_ROD_KEY,
        "unlocked_rods": [DEFAULT_ROD_KEY],
        "inventory": {},
        "score": 0,
        "bait": None,
        "last_cast": 0.0,
        "level": 1,
        "exp": 0,
        # 500 phải khớp với ENERGY_BASE (thể lực tối đa ở level 1) trong
        # fishing_cog.py — energy_updated_at=0.0 nên lần đầu apply_energy_regen()
        # sẽ thấy energy đã đầy (>= max) và chỉ cập nhật lại mốc thời gian, an toàn.
        "energy": 500,
        "energy_updated_at": 0.0,
        "current_map": None,
        "unlocked_skills": [],
        "equipped_skills": [None, None, None],
        # Tổng khối lượng (đơn vị "cân") cá đã câu được CỘNG DỒN cả đời —
        # dùng riêng cho bảng xếp hạng cân nặng (/bảng_xếp_hạng), KHÔNG
        # phải khối lượng đang tồn trong kho (không trừ khi bán cá).
        "total_weight_can": 0.0,
    }


def get_user_data(user_id: int) -> dict:
    """Đọc dữ liệu câu cá của user; tạo bản ghi mặc định nếu chưa có.
    Owner trong OWNER_IDS luôn thấy vang = float("inf") (không ghi inf
    xuống DB, chỉ áp khi đọc ra)."""
    ref = db.reference(f"{DB_ROOT}/{user_id}")
    raw = ref.get()

    if not raw:
        data = _default_data()
        ref.set(data)
    else:
        # Merge để tránh lỗi thiếu field khi schema có thêm cột mới sau này
        data = _default_data()
        data.update(raw)
        if not isinstance(data.get("inventory"), dict):
            data["inventory"] = {}
        # Dọn field tiền tệ cũ (kim_cuong/cash) đã bỏ khỏi game — nếu user
        # có dữ liệu từ trước khi bỏ, xóa luôn để lần save tới không ghi
        # lại xuống DB nữa.
        data.pop("kim_cuong", None)
        data.pop("cash", None)

    if user_id in OWNER_IDS:
        data["vang"] = float("inf")
    return data


def save_user_data(user_id: int, data: dict) -> None:
    """Ghi dữ liệu câu cá xuống Firebase. Không bao giờ ghi giá trị
    float("inf") xuống DB vì JSON không hỗ trợ Infinity."""
    to_save = dict(data)
    if to_save.get("vang") in (float("inf"), float("-inf")):
        to_save.pop("vang", None)  # giữ nguyên số Vàng thật đang lưu trên DB
        db.reference(f"{DB_ROOT}/{user_id}").update(to_save)
        return
    db.reference(f"{DB_ROOT}/{user_id}").set(to_save)


# ---------------------------------------------------------------------------
# Bản async — CHẠY CÁI NÀY TRONG COG, không gọi get_user_data/save_user_data
# (bản sync) trực tiếp trong 1 command async, vì firebase_admin là thư viện
# BLOCKING: gọi thẳng sẽ đứng nguyên event loop của bot trong lúc chờ mạng,
# khiến TẤT CẢ lệnh khác (và cả Discord) không phản hồi được cho tới khi
# request đó xong. Dùng to_thread để đẩy phần blocking ra thread khác.
# ---------------------------------------------------------------------------
async def aget_user_data(user_id: int) -> dict:
    return await asyncio.to_thread(get_user_data, user_id)


async def asave_user_data(user_id: int, data: dict) -> None:
    await asyncio.to_thread(save_user_data, user_id, data)


def get_all_users() -> dict:
    """Đọc TOÀN BỘ nhánh fishing/users 1 lần — dùng cho bảng xếp hạng
    (/bảng_xếp_hạng). Trả về {user_id_str: user_data_dict}. KHÔNG áp dụng
    Vàng vô hạn cho OWNER_IDS ở đây (khác get_user_data) vì owner chưa
    từng bị ghi float('inf') xuống DB thật — giá trị đọc ra luôn là số
    Vàng thật đang lưu, hợp lệ để xếp hạng."""
    raw = db.reference(DB_ROOT).get()
    return raw or {}


async def aget_all_users() -> dict:
    return await asyncio.to_thread(get_all_users)


# ---------------------------------------------------------------------------
# Thời tiết toàn server (1 giá trị dùng chung cho mọi user, KHÔNG theo
# user_id) — xem weather_data.py cho danh sách loại thời tiết + hiệu ứng.
# Lưu ở nhánh riêng "fishing/weather/current" (tách khỏi DB_ROOT của user).
# ---------------------------------------------------------------------------
WEATHER_ROOT = "fishing/weather/current"


def get_current_weather() -> Optional[dict]:
    """Trả về dict {key, name, emoji, started_at, expires_at} hoặc None nếu
    chưa từng random lần nào (vd bot mới deploy lần đầu)."""
    return db.reference(WEATHER_ROOT).get()


def set_current_weather(weather: dict) -> None:
    db.reference(WEATHER_ROOT).set(weather)


async def aget_current_weather() -> Optional[dict]:
    return await asyncio.to_thread(get_current_weather)


async def aset_current_weather(weather: dict) -> None:
    await asyncio.to_thread(set_current_weather, weather)


# ---------------------------------------------------------------------------
# Code đổi thưởng (Admin tạo bằng /tạo-code, người chơi đổi bằng nút
# "🎁 Nhập Code" trong /đồ_câu_lão_bát — xem RedeemCodeModal trong
# fishing_cog.py). Lưu ở nhánh riêng "fishing/codes/<code>", KHÔNG theo
# user_id vì 1 code có thể dùng chung cho nhiều người (tùy max_uses).
#
#   fishing/codes/<CODE>/
#     reward: {vang?, rod?, skill?, bait?}   # key nào có thì cấp thưởng đó
#     max_uses: int | None                    # None = không giới hạn lượt
#     used_by: [user_id_str]                   # đã đổi rồi thì không đổi lại được
#     created_by: int
#     created_at: float
#     expires_at: float                        # epoch giây — BẮT BUỘC, mỗi code
#                                               # đều có hạn dùng (xem create_code)
# ---------------------------------------------------------------------------
CODES_ROOT = "fishing/codes"

# Mỗi code PHẢI có hạn dùng — nếu người tạo (/tạo-code) không tự chỉ định số
# ngày, hệ thống random đều trong khoảng này (đơn vị: ngày).
DEFAULT_CODE_EXPIRY_MIN_DAYS = 1.0
DEFAULT_CODE_EXPIRY_MAX_DAYS = 2.0


def get_code(code: str) -> Optional[dict]:
    return db.reference(f"{CODES_ROOT}/{code}").get()


def create_code(
    code: str, reward: dict, max_uses: Optional[int], created_by: int,
    expires_at: float,
) -> None:
    """Tạo 1 code mới. `expires_at` là mốc epoch giây BẮT BUỘC — bên gọi
    (fishing_cog.py) tự random 1-2 ngày nếu admin không chỉ định số ngày cụ
    thể, đảm bảo KHÔNG có code nào tồn tại vĩnh viễn."""
    db.reference(f"{CODES_ROOT}/{code}").set({
        "reward": reward,
        "max_uses": max_uses,
        "used_by": [],
        "created_by": created_by,
        "created_at": time.time(),
        "expires_at": expires_at,
    })


def redeem_code(code: str, user_id: int) -> dict:
    """Thử đổi 1 code cho user_id, DÙNG TRANSACTION để an toàn khi nhiều
    người đổi cùng lúc (tránh vượt quá max_uses / đổi trùng).
    Kiểm tra hết hạn TRƯỚC TIÊN (kể cả với code cũ từ trước khi có
    expires_at — coi như không có hạn = không bao giờ hết hạn, tránh khóa
    nhầm code đang tồn tại) — code hết hạn thì không được đổi dù còn lượt.
    Trả về {"status": "ok"|"not_found"|"already_used"|"exhausted"|"expired",
    "reward": dict|None}."""
    ref = db.reference(f"{CODES_ROOT}/{code}")
    outcome = {"status": "not_found", "reward": None}

    def _txn(current):
        if current is None:
            outcome["status"] = "not_found"
            return current
        expires_at = current.get("expires_at")
        if expires_at is not None and time.time() >= expires_at:
            outcome["status"] = "expired"
            return current
        used_by = list(current.get("used_by") or [])
        uid = str(user_id)
        if uid in used_by:
            outcome["status"] = "already_used"
            return current
        max_uses = current.get("max_uses")
        if max_uses is not None and len(used_by) >= max_uses:
            outcome["status"] = "exhausted"
            return current
        used_by.append(uid)
        current["used_by"] = used_by
        outcome["status"] = "ok"
        outcome["reward"] = current.get("reward") or {}
        return current

    ref.transaction(_txn)
    return outcome


async def aget_code(code: str) -> Optional[dict]:
    return await asyncio.to_thread(get_code, code)


async def acreate_code(
    code: str, reward: dict, max_uses: Optional[int], created_by: int,
    expires_at: float,
) -> None:
    await asyncio.to_thread(create_code, code, reward, max_uses, created_by, expires_at)


async def aredeem_code(code: str, user_id: int) -> dict:
    return await asyncio.to_thread(redeem_code, code, user_id)
