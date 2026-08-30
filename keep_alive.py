"""
keep_alive.py
==============
Web server tối thiểu để Render (Web Service) nhận diện có port đang mở.
KHÔNG cần nếu bạn deploy dạng "Background Worker" trên Render — chỉ Web
Service mới bắt buộc phải bind port.

CÁCH DÙNG
---------
Trong file main chạy bot (vd main.py / bot.py), thêm ở trên cùng, TRƯỚC
dòng bot.run(...):

    from keep_alive import keep_alive
    keep_alive()
    bot.run(TOKEN)

Render tự cấp port qua biến môi trường PORT — không cần set tay.
"""

import os
import threading

from flask import Flask, send_from_directory

app = Flask(__name__)

# Thư mục chứa index.html / terms.html / privacy.html (trang giới thiệu +
# Điều khoản/Chính sách dùng để xác minh app trên Discord Developer Portal).
_SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")


@app.route("/")
@app.route("/index.html")
def home():
    if os.path.isfile(os.path.join(_SITE_DIR, "index.html")):
        return send_from_directory(_SITE_DIR, "index.html")
    return "Bot đang chạy!"


@app.route("/terms")
@app.route("/terms.html")
def terms():
    return send_from_directory(_SITE_DIR, "terms.html")


@app.route("/privacy")
@app.route("/privacy.html")
def privacy():
    return send_from_directory(_SITE_DIR, "privacy.html")


def _run() -> None:
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive() -> None:
    """Chạy web server trên 1 thread riêng, không chặn bot.run()."""
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
