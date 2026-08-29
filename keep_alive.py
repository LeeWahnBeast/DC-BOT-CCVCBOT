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

from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot đang chạy!"


def _run() -> None:
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive() -> None:
    """Chạy web server trên 1 thread riêng, không chặn bot.run()."""
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
