# Thiết kế: Menu bún đậu mặc định cho mọi thứ 6

**Ngày:** 2026-06-26
**Bối cảnh:** Thứ 6 = ngày bún đậu (per-dish pricing đã ship). Hiện mỗi thứ 6 admin phải tự nhập lại 4 món + giá + upload ảnh. Yêu cầu: **mọi thứ 6 tự động dùng menu bún đậu cố định như tuần này**, admin không phải làm gì.

## Mục tiêu

1. Lưu 1 **template thứ 6 cố định** (4 món + giá + ship + ảnh), set sẵn = menu tuần này.
2. Mỗi thứ 6 lúc 8h30, bot **tự áp template** rồi tạo vote bún đậu — **admin không cần thao tác** (không cần upload ảnh, dùng sẵn `fri.jpg`).
3. **Override vẫn được**: nếu admin tự nhập món khác cho thứ 6 đó → template không áp; `/skip_today` vẫn skip được.

## Quyết định (từ brainstorm)

- Template **cố định**, sửa qua DB khi cần (không làm web editor) — "ít đổi, báo tôi".
- Ảnh: **dùng lại `fri.jpg`** mỗi tuần.
- **Tự động hoàn toàn**: 8h30 thứ 6 tự tạo vote, admin không cần làm gì.

## Mô hình

### Lưu template ở `settings`
1 setting `friday_template` = chuỗi JSON:

```json
{
  "dishes": ["Bún đậu(35k)", "Bún đậu(40k)", "Bún đậu đầy đủ (45k) - mắm tôm", "Bún đậu đầy đủ (45k) - nước mắm"],
  "prices": [35000, 40000, 45000, 45000],
  "ship_fee": 20000,
  "menu_image": "fri.jpg"
}
```

Set sẵn trên prod = menu tuần này. Đổi sau → cập nhật setting (không cần deploy).

### Áp template
Hàm `apply_friday_template(date: str) -> bool` (database.py):
- Đọc `get_setting("friday_template")`. Thiếu/rỗng/JSON lỗi → return `False` (không phá luồng tạo vote).
- Nếu ngày đó **đã có món** (`get_menu_items(date)` không rỗng) → return `False` (admin override thắng).
- Ngược lại áp: `save_menu_items(date, dishes)` + `set_day_dish_prices(date, prices)` + `set_day_ship(date, ship_fee)` + `set_menu_image(date, menu_image)`. Return `True`.

### Móc vào tạo vote thứ 6
Trong `scheduler.py::_scheduled_open_vote`, **ngay sau** đoạn early-return (vote đã open/closed), trước khi check ảnh:
- Nếu `_is_friday(target_str)` → `await db.apply_friday_template(target_str)`.
- **Re-fetch** `existing = await db.get_daily_vote(target_str)` sau khi áp (vì `existing["menu_image"]` đọc ở dưới phải thấy ảnh template vừa set).
- Phần còn lại giữ nguyên: check ảnh (giờ có `fri.jpg`) → gửi ảnh → `get_menu_items` (giờ có 4 món) → tạo poll bún đậu.

⇒ Thứ 6 fresh (admin không làm gì): morning 8h30 → không có vote → `_scheduled_open_vote(0)` → áp template → poll bún đậu tự tạo.

## Edge cases

- Admin đã nhập món cho thứ 6 đó (qua web) → `apply_friday_template` thấy có món → không áp → dùng món admin.
- `/skip_today` (status='closed', no poll) → `_scheduled_open_vote` early-return (status closed) → không áp template, không tạo. Skip được.
- Thiếu `fri.jpg` trên server → check ảnh fail → `notify_admins` (như cũ), không tạo vote. (fri.jpg đã có trên /data/menus.)
- JSON template lỗi/thiếu → `apply_friday_template` return False → luồng cũ (cần admin upload ảnh) → an toàn, không vỡ.
- Ngày T2–T5: không phải thứ 6 → không áp template, hành vi không đổi.

## File sửa

- `database.py`: thêm `apply_friday_template(date) -> bool` (đọc setting JSON, áp nếu chưa có món). Có thể thêm `set_friday_template(...)` tiện set (tuỳ chọn).
- `scheduler.py`: trong `_scheduled_open_vote`, nhánh thứ 6 áp template + re-fetch existing.
- Prod: set `settings.friday_template` = menu tuần này (qua DB, không cần code).

## Kiểm thử

- `apply_friday_template`: áp khi chưa có món (món/giá/ship/ảnh đúng); skip khi đã có món; return False khi không có setting / JSON lỗi.
- `_scheduled_open_vote` thứ 6 (monkeypatch `_target_date` về 1 thứ 6 cố định): set `friday_template`, không có món → tạo poll với 4 món template + ảnh fri.jpg; price/ship đúng.
- Thứ 6 đã có món tay → poll dùng món tay (template không áp).
- Ngày thường (không phải thứ 6) → không áp template (không đổi hành vi).

## Ngoài phạm vi (YAGNI)

- Không web editor cho template (sửa qua DB).
- Không template cho ngày khác (chỉ thứ 6).
- Không đổi luồng vote/picker/chốt 15h.
