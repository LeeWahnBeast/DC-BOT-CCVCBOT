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
          vang: int             # Vàng — tiền chính, bán cá / mua cần / mua mồi
          kim_cuong: int         # Kim Cương — tiền premium
          cash: int               # Cash — tiền premium thứ hai (nạp thật)
          rod: str                 # key cần đang trang bị
          unlocked_rods: [str]      # danh sách key cần đã mở khóa
          inventory: {fish_key: qty}  # kho cá đang giữ, chưa bán
          score: int
          bait: {name, luck, expires_at} | None
          last_cast: float           # epoch giây của lần câu gần nhất

Đổi DB_ROOT nếu bot đã có sẵn nhánh khác.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, db

DB_ROOT = "fishing/users"

DEFAULT_ROD_KEY = "nguoi_yeu_cu"

# Điền ID Discord của owner/admin được bypass giá (Vàng vô hạn) + cooldown.
OWNER_IDS: set[int] = set()


def init_firebase(cred_path: Optional[str] = None, database_url: Optional[str] = None) -> None:
    """Khởi tạo app Firebase nếu chưa có app nào được init trong tiến trình.
    An toàn để gọi nhiều lần / gọi ở nhiều module — chỉ init thật sự 1 lần."""
    if firebase_admin._apps:
        return
    cred_path = cred_path or os.environ["FIREBASE_CRED_PATH"]
    database_url = database_url or os.environ["FIREBASE_DB_URL"]
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {"databaseURL": database_url})


def _default_data() -> dict:
    return {
        "vang": 0,
        "kim_cuong": 0,
        "cash": 0,
        "rod": DEFAULT_ROD_KEY,
        "unlocked_rods": [DEFAULT_ROD_KEY],
        "inventory": {},
        "score": 0,
        "bait": None,
        "last_cast": 0.0,
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
