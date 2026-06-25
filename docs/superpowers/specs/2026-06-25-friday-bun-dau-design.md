# Thiết kế: Ngày thứ 6 = ngày bún đậu

**Ngày:** 2026-06-25
**Phạm vi:** Chỉ áp dụng cho thứ 6 (`weekday() == 4`). Mọi ngày T2–T5 và cuối tuần giữ nguyên hành vi hiện tại.

## Mục tiêu

Biến thứ 6 thành "ngày bún đậu" với luồng riêng:
1. Vote thứ 6 chỉ được tạo **một lần duy nhất lúc 8h30 sáng thứ 6** — không tạo từ tối thứ 5, không digest tối thứ 5, không nhắc lại.
2. Wording theo chủ đề bún đậu khi tạo vote thứ 6.
3. Giá/ship ngày bún đậu do **admin nhập tay mỗi tuần** qua web (không hardcode).
4. Phân công chỉ cần **1 người đi lấy** (picker, round-robin như cũ), **bỏ vai trò trả hộp** (returner).

## Bối cảnh hiện tại (để đối chiếu)

Luồng thứ 6 hiện nay:
- **T5 19:00** `open_vote_evening` tạo vote cho T6 (cần ảnh thực đơn).
- **T5 20:00** `admin_digest` digest riêng admin cho vote T6.
- **T6 08:30** `morning` thấy đã có vote → gửi tin nhắc số người.
- **T6 10:30** `announce_roles` đóng vote, chọn picker + returner.

Cấu hình lịch trong `scheduler.py::build_scheduler`:
- `open_vote_evening`: `day_of_week="sun,mon,tue,wed,thu"`, `args=[app, 1]` (offset=1, tạo cho ngày mai).
- `admin_digest`: `day_of_week="sun,mon,tue,wed,thu"`.
- `morning`: `day_of_week="mon-fri"` — nếu chưa có vote thì gọi `_scheduled_open_vote(day_offset=0)`.
- `announce_roles`: `day_of_week="mon-fri"`.

Giá/ship theo ngày: `daily_votes` có cột `price`, `ship_fee`. `set_menu_image`/`save_menu_items` tạo placeholder row (`status='none'`, `price=35000`). Nhưng `create_daily_vote` lúc tạo vote dùng `ON CONFLICT(date) DO UPDATE SET price=excluded.price, ship_fee=excluded.ship_fee` ⇒ **ghi đè** giá bằng giá toàn cục. Chưa có UI web để nhập giá theo ngày.

## Quyết định thiết kế

### Helper chung
Thêm `_is_friday(date_str) -> bool` (dùng `datetime.fromisoformat(date_str).weekday() == 4`) trong `scheduler.py`, và logic tương đương ở `handlers/vote.py` nếu cần.

### 1. Tạo vote — chỉ 8h30 sáng thứ 6
- `open_vote_evening`: `day_of_week` đổi `"sun,mon,tue,wed,thu"` → `"sun,mon,tue,wed"`. ⇒ Tối T5 không tạo vote cho T6 nữa.
- `admin_digest`: `day_of_week` đổi `"sun,mon,tue,wed,thu"` → `"sun,mon,tue,wed"`. ⇒ Không digest cho T6.
- `morning` (đã chạy `mon-fri`): T6 không có vote → nhánh `else` gọi `_scheduled_open_vote(day_offset=0)` tạo vote. Đây là tin duy nhất cho T6.
  - Lưu ý: placeholder row có `status='none'` rơi vào nhánh `else` của `_scheduled_morning` (chỉ chặn `open`/`closed`), nên vẫn tạo đúng.
- Vẫn **bắt buộc có ảnh thực đơn**; thiếu ảnh → `notify_admins`, không tạo vote (hành vi `_scheduled_open_vote` hiện tại, giữ nguyên).

### 2. Wording bún đậu (chỉ thứ 6)
Sửa `_open_vote_wording(day_offset, date_str)` (hoặc thêm nhánh) để khi `_is_friday(date_str)` trả về:
- `caption`: `🍜 Thực đơn bún đậu hôm nay`
- `poll_question`: `🥢 Hôm nay ăn bún đậu gì?`
- `day_label`: `hôm nay`

Các ngày khác giữ nguyên wording hiện tại.

### 3. Tiền — admin nhập tay mỗi tuần (web per-day)
- **Web**: thêm ô nhập **giá** + **ship** cho từng ngày ở tab "Tuần này" (cạnh 4 món). Để trống = dùng mặc định toàn cục.
  - `web/templates/index.html`: thêm 2 input (price, ship) mỗi ngày.
  - `web/app.py`: endpoint lưu giá/ship theo ngày (có thể gộp vào `/save-menu-items` hoặc thêm endpoint riêng `/save-day-price`).
  - `database.py`: hàm `set_day_price(date, price, ship_fee)` cập nhật `daily_votes` (tạo placeholder row nếu chưa có), và `get_week_data` trả thêm `price`, `ship_fee` để hiển thị.
- **Không ghi đè giá admin** — dùng `NULL` làm dấu hiệu "admin chưa nhập":
  - **Placeholder rows** (`set_menu_image`, `save_menu_items`) **không** set `price`/`ship_fee` nữa — để `NULL` thay vì hardcode `35000`. (Sửa luôn việc hardcode 35000 không khớp config.)
  - **Web `set_day_price(date, price, ship_fee)`** ghi giá admin vào `daily_votes.price`/`ship_fee`. Ô để trống → ghi `NULL`.
  - **`_scheduled_open_vote`** (8h30): đọc `existing`; `price = existing["price"] if existing và existing["price"] is not None else global_price`, tương tự `ship_fee`. Truyền giá đã chọn vào `create_daily_vote`.
  - **`create_daily_vote`** vẫn `ON CONFLICT DO UPDATE` `price`/`ship_fee` bằng giá truyền vào — nhưng giá truyền vào giờ đã là "giá admin nếu có, else global", nên không còn ghi đè nhầm.

### 4. Phân công — 1 người lấy, không trả hộp (chỉ thứ 6)
- Trong `_scheduled_announce_roles`, khi `_is_friday(today)`:
  - Chỉ gọi `pick_next_fetcher` (round-robin như cũ, ưu tiên người lâu chưa làm).
  - **Không** gọi `pick_next_returner`; `close_daily_vote(today, picker_id, None)`.
  - Tin nhắn: `🛵 @X đi lấy bún đậu` (thay "đi lấy cơm").
  - Không cập nhật hàng đợi trả hộp (returner) trong ngày T6.
- Tính tiền giữ công thức `price + round(ship_fee / voter_count)`; nếu admin để ship=0 thì mỗi người = giá bún đậu.

### 5. Thông báo riêng admin
- Thứ 6 không có digest tối hôm trước ⇒ **không** bắn notify real-time cho admin trong ngày T6.
- `handlers/vote.py::_past_evening_digest(date)` trả `False` khi `_is_friday(date)` (giữ nguyên tắc "chỉ báo real-time sau digest"). Admin vẫn nhận tin chốt sổ 10h30 như mọi ngày.

## File sẽ sửa
- `scheduler.py` — bỏ `thu` ở `open_vote_evening` + `admin_digest`; thêm `_is_friday`; wording bún đậu trong `_open_vote_wording`; nhánh T6 trong `_scheduled_announce_roles`; tôn trọng giá admin trong `_scheduled_open_vote`.
- `database.py` — `create_daily_vote`/logic không ghi đè giá admin; thêm `set_day_price`; `get_week_data` trả thêm `price`/`ship_fee`.
- `web/app.py` — endpoint lưu giá/ship theo ngày.
- `web/templates/index.html` — ô nhập giá/ship mỗi ngày.
- `handlers/vote.py` — `_past_evening_digest` trả `False` cho thứ 6.

## Kiểm thử
- T6 không có vote tối T5 (kiểm tra job evening/digest bỏ qua thứ 5).
- T6 8h30: có ảnh menu → tạo vote bún đậu (wording đúng); thiếu ảnh → nhắn admin, không tạo.
- T6 10h30: chỉ 1 picker, không returner; tin nhắn "đi lấy bún đậu".
- Giá admin nhập qua web cho T6 không bị ghi đè khi tạo vote 8h30; ship=0 → mỗi người = giá bún đậu.
- T6 không bắn notify real-time admin giữa 8h30–10h30.
- Ngày T2–T5: hành vi không đổi (vẫn tạo tối hôm trước, có returner, wording cơm).

## Ngoài phạm vi (YAGNI)
- Không đổi món cố định/giá cố định cho bún đậu (admin nhập tay).
- Không thêm digest riêng cho thứ 6.
- Không đổi luồng các ngày khác.
