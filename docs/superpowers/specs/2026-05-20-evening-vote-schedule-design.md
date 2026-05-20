# Tạo vote từ tối hôm trước — Thiết kế

Ngày: 2026-05-20

## Mục tiêu

Cho phép tạo vote cơm trưa của một ngày từ **19:00 tối hôm trước**, để mọi
người có thể chốt suất ăn từ buổi tối thay vì chờ tới sáng.

## Bối cảnh hiện tại

Scheduler ([scheduler.py](../../../scheduler.py)) hiện có 4 job:

| Giờ | Ngày | Job | Hành động |
|---|---|---|---|
| 08:30 | T2–T6 | `open_vote` | tạo vote cho hôm nay |
| 09:30 | T2–T6 | `vote_reminder` | nhắc số người đã vote |
| 10:30 | T2–T6 | `announce_roles` | đóng vote + chốt sổ |
| 14:00 | hằng ngày | `monthly_summary` | tổng kết tháng (cuối tháng) |

Hàm `_scheduled_open_vote` tự tính ngày là "hôm nay" từ `datetime.now()`.
Wording cố định "hôm nay" ở 3 chỗ.

## Quyết định thiết kế (đã chốt với người dùng)

1. **Vote thứ Hai**: vẫn tạo sáng thứ Hai 08:30 (không tạo tối Chủ Nhật,
   tránh làm phiền nhóm cuối tuần). Vote T3→T6 tạo tối hôm trước.
2. **Thực đơn**: giữ logic linh hoạt hiện tại — có món cho ngày đích thì gửi
   poll món ăn, chưa có thì fallback nút ✅/❌.
3. **Lưới an toàn**: job 08:30 kiểm tra — nếu chưa có vote cho hôm nay (job
   19:00 bị lỡ) thì tạo bù.
4. **Gộp reminder vào job sáng**: bỏ job `vote_reminder` 09:30. Job 08:30
   làm: đã có vote → nhắc số người vote; chưa có vote → tạo vote.
5. **Wording theo ngữ cảnh**: vote tạo từ tối hôm trước dùng chữ "ngày mai";
   vote tạo cùng ngày giữ "hôm nay".

## Lịch mới

| Giờ | Ngày | Job | Hành động |
|---|---|---|---|
| 19:00 | T2–T5 | `open_vote_evening` *(mới)* | tạo vote cho ngày mai (T3→T6), wording "ngày mai" |
| 08:30 | T2–T6 | `morning` *(gộp)* | đã có vote → nhắc số người; chưa có → tạo vote, wording "hôm nay" |
| 10:30 | T2–T6 | `announce_roles` | đóng vote + chốt sổ (không đổi) |
| 14:00 | hằng ngày | `monthly_summary` | tổng kết tháng (không đổi) |

Job `vote_reminder` 09:30: **xoá**.

## Hành vi job 08:30 (`morning`)

Đọc vote của hôm nay:

- `status == "open"` → gửi tin nhắc số người vote (tái dùng logic
  `_scheduled_vote_reminder` hiện có).
- `status == "closed"` → không làm gì (ngày đã `/skip_today` hoặc đã xử lý).
- chưa có vote → tạo vote cho hôm nay (`day_offset=0`, wording "hôm nay").

Hệ quả theo ngày:

- **T2**: chưa có vote (không có job tối Chủ Nhật) → tạo vote.
- **T3–T6 bình thường**: đã có vote từ 19:00 hôm trước → gửi tin nhắc.
- **T3–T6 khi job 19:00 lỗi**: chưa có vote → tạo bù (lưới an toàn).

## Wording theo `day_offset`

| Chỗ | `day_offset=0` (cùng ngày) | `day_offset=1` (tối hôm trước) |
|---|---|---|
| Caption ảnh menu | 🍽️ Thực đơn hôm nay | 🍽️ Thực đơn ngày mai |
| Câu hỏi poll | 🍱 Hôm nay ăn gì? | 🍱 Ngày mai ăn gì? |
| Text vote ✅❌ (`_build_vote_text`) | 🍱 *Đặt cơm hôm nay* | 🍱 *Đặt cơm ngày mai* |

## Thay đổi mã

### `scheduler.py`

- `_scheduled_open_vote(app, day_offset=0)`: ngày đích = `now + day_offset`;
  chọn caption / câu hỏi poll / `day_label` theo `day_offset`.
- Thêm hàm job sáng `_scheduled_morning(app)`: đọc vote hôm nay → nhắc hoặc
  tạo (xem mục "Hành vi job 08:30").
- `build_scheduler`:
  - Job `open_vote_evening`: `CronTrigger(hour=19, minute=0, day_of_week="mon-thu")`,
    `args=[app, 1]` → gọi `_scheduled_open_vote`.
  - Job `open_vote` 08:30 đổi thành job `morning` (`_scheduled_morning`),
    cron T2–T6 giữ nguyên.
  - Gỡ đăng ký job `vote_reminder`.
- Tách phần lõi gửi tin nhắc số người vote thành helper riêng (ví dụ
  `_send_vote_reminder(app, date)`), để job sáng gọi lại. Hàm
  `_scheduled_vote_reminder` cũ bị xoá cùng job 09:30.

### `handlers/vote.py`

- `_build_vote_text(voters, menu_description="", day_label="hôm nay")`: thêm
  tham số `day_label`, header thành `f"🍱 *Đặt cơm {day_label}*"`.
- Lệnh `/open_vote` thủ công: **không đổi** — luôn là "hôm nay" (admin gõ tay
  chỉ dùng cho hôm nay). Mặc định `day_label="hôm nay"` đảm bảo điều này.

### `config.py` + `.env`

- Thêm `EVENING_OPEN_TIME` (mặc định `"19:00"`).
- Gỡ `VOTE_CLOSE_TIME` (không còn job nào dùng sau khi xoá `vote_reminder`).

### Tài liệu

- Cập nhật bảng "Lịch tự động (scheduler)" trong [CLAUDE.md](../../../CLAUDE.md).

## Trade-off / hạn chế đã biết

Vote tạo buổi tối thường chưa có thực đơn → rơi vào dạng ✅/❌. Nếu sáng hôm
sau admin mới nhập món hoặc upload ảnh menu, **poll/ảnh menu sẽ không được gửi
lại** vì vote đã tồn tại (job sáng chỉ nhắc, không tạo lại). Đây là hệ quả của
quyết định "giữ logic thực đơn linh hoạt" — đã được người dùng chấp nhận.

## Ngoài phạm vi

- Không gửi lại poll/ảnh menu khi admin nhập thực đơn sau khi vote tối đã tạo.
- Không thay đổi job `announce_roles` (10:30) và `monthly_summary` (14:00).
- Không đổi logic round-robin phân công.
