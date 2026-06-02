"""Render bảng tổng kết tiền cơm thành ảnh PNG (dùng cho /summary và job cuối tháng).

Hàm thuần — không đụng DB, không đụng Telegram. Trả về bytes PNG.
"""
from __future__ import annotations
import logging
import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Cấu hình hiển thị ─────────────────────────────────────────────────────────
SCALE = 2  # render 2x cho nét

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
_FONT_REGULAR = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_FONT_BOLD = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")

# Màu
COL_BG = (255, 255, 255)
COL_TITLE = (31, 78, 121)
COL_HEADER_BG = (31, 78, 121)
COL_HEADER_TEXT = (255, 255, 255)
COL_ROW_ALT = (245, 245, 245)
COL_TEXT = (34, 34, 34)
COL_LINE = (210, 210, 210)
COL_PAID = (27, 94, 32)       # ✓ xanh
COL_UNPAID = (183, 28, 28)    # ✗ đỏ
COL_TOTAL_BG = (227, 242, 253)
TOP1_MARK = "★ "              # dấu nhấn trước tên top 1 (in đậm)

# Kích thước (px ở scale 1, nhân SCALE khi vẽ)
PAD = 24
ROW_H = 40
TITLE_H = 56
COL_GAP = 22
FS_TITLE = 30
FS_HEADER = 21
FS_ROW = 20


def _font(path: str, size: int):
    """Load font TTF; nếu thiếu file → fallback font mặc định (không crash)."""
    px = size * SCALE
    try:
        return ImageFont.truetype(path, px)
    except OSError:
        logger.warning("Không load được font %s — dùng font mặc định.", path)
        try:
            return ImageFont.load_default(px)  # Pillow >= 10.1: scalable, có tiếng Việt
        except TypeError:
            return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def render_summary_image(rows, paid_ids, year_month: str) -> bytes:
    """Vẽ bảng tổng kết thành PNG.

    rows: list dict đã sort theo total giảm dần, mỗi dict có
          full_name, meal_count, total, user_id.
    paid_ids: set user_id đã đóng tiền.
    year_month: "YYYY-MM".
    """
    paid_ids = set(paid_ids or [])
    year, month = year_month.split("-")
    title = f"Tổng kết tháng {int(month)}/{year}"

    f_title = _font(_FONT_BOLD, FS_TITLE)
    f_header = _font(_FONT_BOLD, FS_HEADER)
    f_row = _font(_FONT_REGULAR, FS_ROW)
    f_row_b = _font(_FONT_BOLD, FS_ROW)

    # Dòng dữ liệu -> cell text
    data = []
    for i, r in enumerate(rows, 1):
        data.append({
            "rank": str(i),
            "name": str(r.get("full_name", "")),
            "count": str(r.get("meal_count", 0)),
            "total": f"{r.get('total', 0):,}đ",
            "paid": r.get("user_id") in paid_ids,
        })

    total_count = sum(r.get("meal_count", 0) for r in rows)
    total_money = sum(r.get("total", 0) for r in rows)
    total_row = {
        "rank": "",
        "name": "Tổng cộng",
        "count": str(total_count),
        "total": f"{total_money:,}đ",
    }

    # Định nghĩa cột: (key, header, align, font_đo)
    columns = [
        ("rank", "#", "center"),
        ("name", "Tên", "center"),
        ("count", "Suất", "center"),
        ("total", "Tiền", "center"),
        ("tt", "TT", "center"),
    ]

    # Đo bề rộng từng cột bằng một draw tạm
    tmp = Image.new("RGB", (10, 10))
    td = ImageDraw.Draw(tmp)

    def _name_disp(i, name):
        return (TOP1_MARK + name) if i == 0 else name

    col_w = {}
    for key, header, _ in columns:
        w = _text_w(td, header, f_header)
        if key == "tt":
            w = max(w, _text_w(td, "✓", f_row_b))
        elif key == "name":
            for i, d in enumerate(data):
                f = f_row_b if i == 0 else f_row
                w = max(w, _text_w(td, _name_disp(i, d["name"]), f))
            w = max(w, _text_w(td, total_row["name"], f_row_b))
        else:
            for i, d in enumerate(data):
                f = f_row_b if i == 0 else f_row
                w = max(w, _text_w(td, d[key], f))
            if key in ("count", "total"):
                w = max(w, _text_w(td, total_row[key], f_row_b))
        col_w[key] = w

    pad = PAD * SCALE
    col_gap = COL_GAP * SCALE
    row_h = ROW_H * SCALE
    title_h = TITLE_H * SCALE

    table_w = sum(col_w.values()) + col_gap * (len(columns) - 1)
    width = table_w + pad * 2
    # title + header + N data rows + total row
    height = title_h + row_h * (len(data) + 2) + pad

    img = Image.new("RGB", (width, height), COL_BG)
    draw = ImageDraw.Draw(img)

    # Vị trí x trái của từng cột
    col_x = {}
    x = pad
    for key, _, _ in columns:
        col_x[key] = x
        x += col_w[key] + col_gap

    def draw_cell(text, key, top, font, color, align):
        cw = col_w[key]
        cx = col_x[key]
        tw = _text_w(draw, text, font)
        if align == "right":
            tx = cx + cw - tw
        elif align == "center":
            tx = cx + (cw - tw) // 2
        else:
            tx = cx
        ty = top + (row_h - (FS_ROW * SCALE)) // 2 - 2 * SCALE
        draw.text((tx, ty), text, font=font, fill=color)

    # Tiêu đề (canh giữa)
    tw = _text_w(draw, title, f_title)
    draw.text(((width - tw) // 2, pad // 2), title, font=f_title, fill=COL_TITLE)

    # Header row
    y = title_h
    draw.rectangle([0, y, width, y + row_h], fill=COL_HEADER_BG)
    for key, header, align in columns:
        draw_cell(header, key, y, f_header, COL_HEADER_TEXT, align)

    # Data rows (zebra; hàng top 1 in đậm + ★)
    y += row_h
    for idx, d in enumerate(data):
        is_top = idx == 0
        if idx % 2 == 1:
            draw.rectangle([0, y, width, y + row_h], fill=COL_ROW_ALT)
        row_font = f_row_b if is_top else f_row
        for key, _, align in columns:
            if key == "tt":
                mark = "✓" if d["paid"] else "✗"
                color = COL_PAID if d["paid"] else COL_UNPAID
                draw_cell(mark, key, y, f_row_b, color, align)
            elif key == "name":
                txt = (TOP1_MARK + d["name"]) if is_top else d["name"]
                draw_cell(txt, key, y, row_font, COL_TEXT, align)
            else:
                draw_cell(d[key], key, y, row_font, COL_TEXT, align)
        y += row_h

    # Total row
    draw.rectangle([0, y, width, y + row_h], fill=COL_TOTAL_BG)
    draw.line([0, y, width, y], fill=COL_LINE, width=SCALE)
    for key, _, align in columns:
        if key == "tt":
            continue
        draw_cell(total_row.get(key, ""), key, y, f_row_b, COL_TITLE, align)

    # Gạch dọc phân cách giữa các cột (vẽ sau cùng, nằm trong khoảng trống giữa cột)
    grid_top = title_h
    grid_bottom = y + row_h
    for i in range(len(columns) - 1):
        next_key = columns[i + 1][0]
        bx = col_x[next_key] - col_gap // 2
        draw.line([(bx, grid_top), (bx, grid_bottom)], fill=COL_LINE, width=SCALE)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
