"""
firebase_db.py
===============
Lớp lưu trữ Firebase Realtime Database dùng riêng cho tính năng câu cá vạn cân.

CÁCH DÙNG
---------
- Nếu bot chính (delta-mick-bot) ĐÃ gọi firebase_admin.initialize_app() ở
  entrypoint rồi thì KHÔNG cần gọi init_firebase() ở đây nữa — chỉ cần
  import module này, nó sẽ tự dùng chung app Firebase đã có sẵn.
- Nếu file này được chạy độc lập / cog được load trước khi app init, gọi
  init_firebase() một lần lúc bot khởi động (vd trong setup_hook / on_ready).
- Cấu trúc dữ liệu trên Realtime Database:

      fishing/
        users/
          <user_id>/
            mick: int
            rod: str                # key cần đang trang bị
            unlocked_rods: [str]     # danh sách key cần đã mở khóa
            score: int
            bait: {name, luck, expires_at} | None
            last_cast: float         # epoch giây của lần câu gần nhất

- Đổi DB_ROOT nếu bot đã có sẵn nhánh khác (vd bot dùng "users/<id>/fishing"
  thay vì nhánh riêng "fishing/users/<id>").
"""

from __future__ import annotations

import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, db

DB_ROOT = "fishing/users"

DEFAULT_ROD_KEY = "thep_ren"

# Điền ID Discord của owner/admin được bypass giá cần câu (MICK vô hạn).
# Đây là cùng cơ chế sentinel float("inf") mà bot đang dùng cho owner bypass
# ở các hệ thống kinh tế khác.
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
        "mick": 0,
        "rod": DEFAULT_ROD_KEY,
        "unlocked_rods": [DEFAULT_ROD_KEY],
        "score": 0,
        "bait": None,
        "last_cast": 0.0,
    }


def get_user_data(user_id: int) -> dict:
    """Đọc dữ liệu câu cá của user; tạo bản ghi mặc định nếu chưa có.
    Owner trong OWNER_IDS luôn thấy mick = float("inf") (không ghi inf
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

    if user_id in OWNER_IDS:
        data["mick"] = float("inf")
    return data


def save_user_data(user_id: int, data: dict) -> None:
    """Ghi dữ liệu câu cá xuống Firebase. Không bao giờ ghi giá trị
    float("inf") xuống DB vì JSON không hỗ trợ Infinity."""
    to_save = dict(data)
    if to_save.get("mick") in (float("inf"), float("-inf")):
        to_save.pop("mick", None)  # giữ nguyên số MICK thật đang lưu trên DB
        db.reference(f"{DB_ROOT}/{user_id}").update(to_save)
        return
    db.reference(f"{DB_ROOT}/{user_id}").set(to_save)
