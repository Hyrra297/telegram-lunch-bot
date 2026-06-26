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
  - **KHÔNG tính tiền lúc 10h30** cho thứ 6 (bọc khối `set_cost_per_person` trong `if not _is_friday(today)`). Giá bún đậu thực tế chốt sau, để job 15h tính.
- Các ngày khác giữ công thức tính tiền `price + round(ship_fee / voter_count)` tại 10h30 như cũ.

### 4b. Chốt tiền thứ 6 lúc 15h — update vào bảng
- **Job mới `friday_settle`** lúc 15:00, `day_of_week="fri"` (chỉ thứ 6).
- Hành động (im lặng, KHÔNG gửi thông báo):
  - Lấy `daily = get_daily_vote(today)`, `voters = get_voters(today)`. Không có vote hợp lệ hoặc không ai vote → bỏ qua.
  - **Áp giá override admin nhập vào giá thực**: `price = price_override nếu có, else daily["price"]`; tương tự `ship`. Ghi `daily_votes.price`/`ship_fee` = giá đã chốt (hàm mới `set_day_actual_price`). ⇒ Bảng tổng kết (đọc live từ `daily_votes.price`) hiển thị đúng giá bún đậu admin chốt buổi chiều.
  - Tính `cost_per_person = price + round(ship / len(voters))`, lưu `set_cost_per_person` (cho bản ghi/log).
- Lý do 15h: admin mua bún đậu xong mới biết giá thật → nhập/chỉnh giá qua web trước 15h; 15h bot mới "chốt" để update bảng. `cost_per_person` hiện không hiển thị trực tiếp (bảng tính live), nên việc cập nhật `daily_votes.price`/`ship_fee` mới là phần làm bảng đúng.
- Lưu ý ngoài phạm vi: lệnh admin thủ công `/close_vote` (handlers/admin.py) vẫn tính tiền ngay khi đóng — không đổi (admin tự chủ động).

### 5. Thông báo riêng admin — GIỮ NGUYÊN (real-time bật cho T6)
- Thứ 6 admin **vẫn nhận notify real-time** mỗi khi có người đặt/đổi/huỷ bún đậu trong khoảng 8h30–10h30, để biết số lượng mà đi đặt.
- **Không cần sửa code**: `_past_evening_digest("<thứ 6>")` đã trả `True` trong khoảng 8h30–10h30 (vì đã qua mốc 20h tối T5), nên cơ chế notify real-time sẵn có tự động hoạt động cho T6. Voter đầu tiên trong ngày cũng được báo (`was_voter=False → notify_new_voter`).
- Lưu ý: T6 không có "danh sách chốt" 20h tối hôm trước (baseline digest), nhưng các tin real-time đều kèm số người hiện tại nên vẫn đủ thông tin.

## File sẽ sửa
- `scheduler.py` — bỏ `thu` ở `open_vote_evening` + `admin_digest`; thêm `_is_friday`; wording bún đậu trong `_open_vote_wording`; nhánh T6 trong `_scheduled_announce_roles` (1 picker + bỏ tính tiền 10h30); tôn trọng giá admin trong `_scheduled_open_vote`; **job mới `friday_settle` 15h + hàm `_scheduled_friday_settle`**.
- `database.py` — không ghi đè giá admin; thêm `set_day_price`; **thêm `set_day_actual_price`** (ghi giá thực vào `daily_votes.price`/`ship_fee`); `get_week_data` trả thêm `price_override`/`ship_fee_override`.
- `web/app.py` — endpoint lưu giá/ship theo ngày.
- `web/templates/index.html` — ô nhập giá/ship mỗi ngày.
- `handlers/vote.py` — **không sửa**; notify real-time admin cho T6 đã đúng tự nhiên.

## Kiểm thử
- T6 không có vote tối T5 (kiểm tra job evening/digest bỏ qua thứ 5).
- T6 8h30: có ảnh menu → tạo vote bún đậu (wording đúng); thiếu ảnh → nhắn admin, không tạo.
- T6 10h30: chỉ 1 picker, không returner; tin nhắn "đi lấy bún đậu"; **`cost_per_person` chưa được tính (vẫn None)**.
- T6 15h: áp giá override vào `daily_votes.price`/`ship_fee`, tính lại `cost_per_person`; không ai vote → bỏ qua; không gửi tin.
- Giá admin nhập qua web cho T6 không bị ghi đè khi tạo vote 8h30; ship=0 → mỗi người = giá bún đậu.
- T6 VẪN bắn notify real-time admin giữa 8h30–10h30 (đặt/đổi/huỷ bún đậu), gồm cả voter đầu tiên.
- Ngày T2–T5: hành vi không đổi (vẫn tạo tối hôm trước, có returner, wording cơm).

## Ngoài phạm vi (YAGNI)
- Không đổi món cố định/giá cố định cho bún đậu (admin nhập tay).
- Không thêm digest riêng cho thứ 6.
- Không đổi luồng các ngày khác (10h30 các ngày khác vẫn tính tiền như cũ).
- Không gửi thông báo lúc 15h (chốt tiền im lặng).
- Không đổi lệnh admin thủ công `/close_vote` (vẫn tính tiền khi đóng).
