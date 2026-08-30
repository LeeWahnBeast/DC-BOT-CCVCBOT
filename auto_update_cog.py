"""
auto_update_cog.py
===================
THAY THẾ HOÀN TOÀN update_log_cog.py (đã xóa lệnh /update_log thủ công).

Cơ chế MỚI — TỰ ĐỘNG HOÀN TOÀN, KHÔNG CẦN OWNER GÕ LỆNH:

Mỗi lần bot khởi động lại (tức là mỗi lần deploy code mới lên Render):
1. Quét toàn bộ file .py trong thư mục bot, tính hash nội dung từng file.
2. So với snapshot hash đã lưu ở Firebase (lần khởi động trước) để biết
   CHÍNH XÁC những file nào mới bị thêm/sửa/xóa.
3. Nếu KHÔNG có file nào đổi (vd bot chỉ restart do lỗi mạng, không phải
   deploy code mới) -> BỎ QUA, không tính là 1 bản cập nhật.
4. Nếu có thay đổi -> gửi phần code đã đổi (diff-lite: nội dung file mới,
   cắt bớt nếu quá dài) cho Groq AI, yêu cầu AI tự:
     a. Viết lại thành các gạch đầu dòng mô tả thay đổi (tiếng Việt).
     b. Tự quyết định bản cập nhật này là "lớn" / "vừa" / "nhỏ" dựa trên
        mức độ + số lượng file thay đổi, và tự đề xuất mức tăng version
        tương ứng — bot không áp rule cứng, để AI tự phân tích.
5. Cộng mức tăng AI đề xuất vào version đang lưu ở Firebase, lưu version
   mới + snapshot hash mới xuống Firebase.
6. Đăng bản tin cập nhật vào LOG_CHANNEL_ID bằng Discord Components V2
   Container (không dùng embed), theo đúng mẫu cũ:

    # CẬP NHẬT 5.12
    <t:1787891898:f>
    **<:sao:1543465405484503160> Tính năng mới:**
    • ...
    -# 4 file thay đổi · v5.02 → v5.12

YÊU CẦU
-------
- Biến môi trường GROQ_API_KEY.
- Gói `groq` (đã có sẵn trong requirements.txt).
- Firebase phải init xong TRƯỚC khi cog này load (main.py đã gọi
  init_firebase() trước asyncio.run(main())).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from firebase_admin import db

# Kênh đăng update log do AI soạn (giữ nguyên kênh cũ của update_log_cog).
LOG_CHANNEL_ID = 1539484617663324230

# Nhánh Firebase lưu version hiện tại + snapshot hash các file .py — TÁCH
# khỏi DB_ROOT của fishing_cog (không liên quan dữ liệu người chơi).
AUTO_UPDATE_ROOT = "bot_meta/auto_update"

# Thư mục gốc chứa code bot — quét toàn bộ file .py trực tiếp trong đây
# (không đệ quy vào __pycache__/site/assets vì không phải code logic).
BOT_DIR = Path(__file__).resolve().parent
_IGNORED_DIRS = {"__pycache__", "site", "assets", ".git"}

# Cho phép đổi model qua biến môi trường mà không cần sửa code.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Giới hạn ký tự nội dung file gửi cho AI (tránh vượt context/token limit
# nếu 1 file quá dài) — mỗi file đổi chỉ gửi tối đa chừng này ký tự.
_MAX_CHARS_PER_FILE = 4000

_SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích thay đổi code (changelog) cho một Discord bot "
    "viết bằng Python, trả lời bằng tiếng Việt.\n"
    "Bạn sẽ nhận được: phiên bản hiện tại, danh sách tên file đã "
    "thêm/sửa/xóa, và nội dung (có thể bị cắt bớt) của các file đó.\n"
    "Nhiệm vụ của bạn — trả lời DUY NHẤT bằng 1 khối JSON hợp lệ, KHÔNG có "
    "lời dẫn, KHÔNG có markdown code fence, đúng cấu trúc:\n"
    '{"bump": <số thực dương>, "bullets": ["...", "..."]}\n\n'
    "Trong đó:\n"
    "- \"bump\": mức bạn đề xuất CỘNG THÊM vào version hiện tại, dựa trên "
    "mức độ quan trọng + số lượng file thay đổi mà bạn tự đánh giá "
    "(thay đổi nhỏ/vá lỗi -> bump nhỏ như 0.1; thêm tính năng vừa -> "
    "khoảng 0.3-0.5; đại tu/thêm nhiều tính năng lớn -> 1.0 trở lên). "
    "Tự quyết định hoàn toàn, không có công thức cố định.\n"
    "- \"bullets\": danh sách các gạch đầu dòng NGẮN GỌN, RÕ RÀNG mô tả "
    "thay đổi, viết theo góc nhìn người chơi cuối (KHÔNG lộ chi tiết code/"
    "biến/tên hàm nội bộ nếu không cần thiết)."
)


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_py_files() -> dict[str, str]:
    """Quét toàn bộ file .py trong BOT_DIR (không đệ quy vào thư mục bị
    bỏ qua), trả về {đường_dẫn_tương_đối: hash_sha256}."""
    result: dict[str, str] = {}
    for path in BOT_DIR.rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.relative_to(BOT_DIR).parts):
            continue
        rel = str(path.relative_to(BOT_DIR))
        result[rel] = _hash_file(path)
    return result


def _diff_files(old_hashes: dict[str, str], new_hashes: dict[str, str]) -> dict[str, list[str]]:
    old_keys, new_keys = set(old_hashes), set(new_hashes)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified = sorted(k for k in (old_keys & new_keys) if old_hashes[k] != new_hashes[k])
    return {"added": added, "removed": removed, "modified": modified}


def _read_snippet(rel_path: str) -> str:
    try:
        text = (BOT_DIR / rel_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "(không đọc được nội dung file)"
    if len(text) > _MAX_CHARS_PER_FILE:
        return text[:_MAX_CHARS_PER_FILE] + "\n... (đã cắt bớt) ..."
    return text


def _get_groq_client():
    from groq import Groq  # import trễ để không bắt buộc cài nếu không dùng

    api_key = os.environ["GROQ_API_KEY"]
    return Groq(api_key=api_key)


def _call_groq_sync(current_version: str, diff: dict[str, list[str]]) -> dict:
    client = _get_groq_client()

    parts = [f"Phiên bản hiện tại: {current_version}\n"]
    for label, key in (("THÊM MỚI", "added"), ("ĐÃ SỬA", "modified"), ("ĐÃ XÓA", "removed")):
        files = diff[key]
        if not files:
            continue
        parts.append(f"\n== File {label} ({len(files)}) ==")
        for rel in files:
            parts.append(f"\n--- {rel} ---")
            if key != "removed":
                parts.append(_read_snippet(rel))

    user_content = "\n".join(parts)

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content.strip()
    parsed = json.loads(raw)

    bump = float(parsed.get("bump", 0.1))
    if bump <= 0:
        bump = 0.1
    bullets = parsed.get("bullets") or []
    bullets = [str(b).strip() for b in bullets if str(b).strip()]
    if not bullets:
        bullets = ["(AI không trả về nội dung mô tả)"]
    return {"bump": bump, "bullets": bullets}


async def _analyze_with_ai(current_version: str, diff: dict[str, list[str]]) -> dict:
    return await asyncio.to_thread(_call_groq_sync, current_version, diff)


def _fmt_version(v: float) -> str:
    """1.0 -> '1.0' ; 2.5 -> '2.5' ; 2.35 -> '2.35' (bỏ số 0 thừa nhưng
    luôn giữ ít nhất 1 số thập phân)."""
    s = f"{v:.2f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def build_update_container(
    *, tu_ban: str, den_ban: str, so_file: int, bullets: list[str],
) -> discord.ui.LayoutView:
    ts = int(time.time())
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour.blurple())
    container.add_item(discord.ui.TextDisplay(
        f"# CẬP NHẬT {den_ban}\n"
        f"<t:{ts}:f>"
    ))
    bullet_text = "\n".join(f"• {b}" for b in bullets)
    container.add_item(discord.ui.TextDisplay(
        f"**<:sao:1543465405484503160> Tính năng mới:**\n{bullet_text}"
    ))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(
        f"-# {so_file} file thay đổi · v{tu_ban} → v{den_ban}"
    ))
    view.add_item(container)
    return view


class AutoUpdateCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._checked = False  # chỉ chạy đúng 1 lần mỗi lần process khởi động

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready có thể bắn lại nhiều lần (reconnect) — chỉ xử lý auto
        # update ở lần đầu tiên của process này.
        if self._checked:
            return
        self._checked = True
        await self._run_auto_update()

    async def _run_auto_update(self) -> None:
        try:
            meta_ref = db.reference(AUTO_UPDATE_ROOT)
            meta = await asyncio.to_thread(meta_ref.get) or {}

            old_hashes: dict[str, str] = meta.get("file_hashes") or {}
            current_version: str = meta.get("version") or "1.0"

            new_hashes = await asyncio.to_thread(_scan_py_files)

            # Lần đầu tiên bot chạy (chưa từng có snapshot) -> chỉ lưu
            # snapshot gốc, KHÔNG tính là 1 bản cập nhật (không có gì để
            # so sánh) và không đăng log.
            if not old_hashes:
                await asyncio.to_thread(
                    meta_ref.set,
                    {"version": current_version, "file_hashes": new_hashes,
                     "updated_at": time.time()},
                )
                print(f"[auto_update] Khởi tạo snapshot lần đầu — version {current_version}")
                return

            diff = _diff_files(old_hashes, new_hashes)
            so_file = len(diff["added"]) + len(diff["modified"]) + len(diff["removed"])

            if so_file == 0:
                # Bot restart nhưng code không đổi (vd lỗi mạng, crash) ->
                # bỏ qua, không phải 1 bản deploy mới.
                return

            try:
                analysis = await _analyze_with_ai(current_version, diff)
            except Exception as exc:  # noqa: BLE001
                print(f"[auto_update] Groq AI lỗi, bỏ qua lần cập nhật này: {exc}")
                # Vẫn lưu lại snapshot mới để lần sau không tính lại đúng
                # diff này (tránh báo trùng khi Groq lỗi tạm thời).
                await asyncio.to_thread(
                    meta_ref.update,
                    {"file_hashes": new_hashes, "updated_at": time.time()},
                )
                return

            tu_ban = current_version
            den_ban = _fmt_version(float(current_version) + analysis["bump"])

            await asyncio.to_thread(
                meta_ref.set,
                {"version": den_ban, "file_hashes": new_hashes, "updated_at": time.time()},
            )

            channel = self.bot.get_channel(LOG_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
                except discord.HTTPException as exc:
                    print(f"[auto_update] Không tìm thấy kênh log: {exc}")
                    return

            view = build_update_container(
                tu_ban=tu_ban, den_ban=den_ban, so_file=so_file, bullets=analysis["bullets"],
            )
            await channel.send(view=view)
            print(f"[auto_update] Đã đăng update v{tu_ban} → v{den_ban} ({so_file} file)")

        except Exception as exc:  # noqa: BLE001 — không để lỗi auto-update crash cả bot
            print(f"[auto_update] Lỗi không xác định, bỏ qua lần này: {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoUpdateCog(bot))
