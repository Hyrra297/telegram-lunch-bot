# Thiết kế: Render bảng tổng kết (/summary) thành ảnh

Ngày: 2026-06-02

## Mục tiêu
Hiển thị bảng tổng kết tiền cơm dạng **ảnh** thay vì bảng text trong code block, cho
dễ theo dõi. Áp dụng cho `/summary` (admin gõ tay) và job tổng kết cuối tháng (14:00).
`/tien` giữ nguyên text.

## Quyết định
- Chỉ gửi **ảnh** (không kèm text). Trường hợp không có dữ liệu vẫn trả text như cũ.
- Render bằng **Pillow** + font **DejaVuSans** đóng kèm trong repo (hỗ trợ tiếng Việt,
  chạy được cả Windows lẫn Fly.io).
- Có dòng **"Tổng cộng"** (tổng suất + tổng tiền) ở cuối bảng.

## Kiến trúc

### Module mới: `image_summary.py`
Hàm thuần, tách khỏi bot/scheduler để test độc lập:

```
render_summary_image(rows, paid_ids, year_month) -> bytes  # PNG (BytesIO.getvalue())
```

- `rows`: list dict đã sort theo `total` giảm dần (caller lo sort). Mỗi dict có
  `full_name`, `meal_count`, `total`, `user_id`.
- `paid_ids`: set user_id đã đóng tiền.
- `year_month`: "YYYY-MM".
- Trả về bytes PNG. Không đụng DB, không đụng Telegram.

### Bố cục ảnh
- Tiêu đề: "Tổng kết tháng M/YYYY".
- Cột: `#` | `Tên` | `Suất` | `Tiền` | `TT`.
- Header có nền màu; các dòng dữ liệu zebra (nền xám nhạt xen kẽ).
- Trạng thái: `✓` xanh (đã đóng) / `✗` đỏ (chưa) — dùng glyph trong DejaVuSans
  (emoji màu không render được).
- Dòng cuối "Tổng cộng": tổng `meal_count` + tổng `total`.
- Render ở scale 2x cho nét; chiều cao co theo số dòng; chiều rộng co theo tên dài nhất.

### Font
- Đóng kèm `assets/fonts/DejaVuSans.ttf` + `DejaVuSans-Bold.ttf` (license tự do).
- Load từ đường dẫn tương đối module để chạy mọi nơi.

## Tích hợp
- `handlers/summary.py::summary()` — thay `reply_text(table)` bằng render ảnh +
  `reply_photo(BytesIO, caption="📊 Tổng kết tháng M/YYYY")`. Nhánh "không có dữ liệu"
  giữ `reply_text` như cũ. Bỏ auto-delete (đã bỏ ở thay đổi trước).
- `scheduler.py::_scheduled_monthly_summary()` — thay `send_message` bằng `send_photo`.
- `requirements.txt` — thêm `pillow`.

## Test
- `render_summary_image` trả về bytes bắt đầu bằng magic PNG `\x89PNG`.
- Không crash với: 1 dòng, nhiều dòng, tên dài, tên tiếng Việt có dấu.
- Tổng suất/tiền trong ảnh đúng (kiểm gián tiếp qua việc render không lỗi + ảnh có
  kích thước > 0; nội dung số liệu test ở tầng dữ liệu đã có sẵn).

## Ngoài phạm vi
- Không đổi `/tien`.
- Không đổi web dashboard.
- Không đổi công thức tính tiền.
