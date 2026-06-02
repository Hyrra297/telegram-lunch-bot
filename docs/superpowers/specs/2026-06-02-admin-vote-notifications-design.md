# Thiết kế: Thông báo vote riêng cho admin (qua @lunch17_bot)

Ngày: 2026-06-02

## Vấn đề
Nhiều người vote nhưng admin không xem nhóm liên tục được → sợ sót. Giải pháp:
bot **chủ động đẩy thông báo vào chat riêng với bot** (KHÔNG gửi vào nhóm).

## Hành vi (đã chốt với user)
1. **Digest buổi tối — 20:00**: 1 giờ sau khi vote được tạo (19:00 cho ngày mai),
   bot nhắn riêng từng admin: danh sách ai đã đặt + tổng số người (cho vote ngày mai).
   Chạy các tối T2–T5 (khớp job tạo vote tối). Không có ai thì báo "chưa có ai đặt".
2. **Real-time sáng hôm sau**: mỗi khi có **người mới** đặt (số người tăng), bot nhắn
   riêng admin ngay: "✅ {tên} vừa đặt cơm — tổng {N} người."
   - Chỉ bật vào **đúng ngày ăn** (`vote.date == hôm nay`) → buổi tối hôm trước không
     real-time (chỉ digest 20:00); sáng hôm sau mới real-time.
   - Chỉ báo **người mới** (không báo đổi món, không báo bỏ vote).
   - Tự dừng sau 10:30 (vote đóng → handler bỏ qua).
   - Không tự báo cho chính admin về vote của họ (`exclude_user_id`).

Gửi tới: tất cả id trong `config.ADMIN_IDS`, mỗi người 1 tin riêng (chat với bot).

## Kiến trúc

### Module mới: `admin_notify.py`
- `format_new_voter(name, count) -> str` — tin real-time (thuần, test được).
- `format_digest(date, voters) -> str` — tin digest (thuần, test được).
- `async notify_admins(bot, text, exclude_user_id=None)` — gửi riêng từng admin,
  try/except + log từng người (1 admin lỗi không chặn người khác).
- `async notify_new_voter(bot, name, count, exclude_user_id=None)` — compose + gửi.
- `async send_vote_digest(bot, date)` — đọc `get_voters(date)`, format, gửi.

### `database.py`
- Thêm `async is_voter(date, user_id) -> bool` — kiểm tra đã có row trong
  `vote_entries` chưa (để phát hiện "người mới" trên đường poll).

### `handlers/vote.py`
- `handle_poll_answer` (native poll): trước khi `vote_for_dish`, lấy
  `was = await db.is_voter(date, user_id)`. Sau khi ghi, nếu là lựa chọn (không phải
  retract) và `date == _today()` và `not was` → `notify_new_voter(...)`.
- `handle_vote_callback` (inline VOTE_IN): `toggle_vote` trả `voted_in`; nếu
  `voted_in and date == _today()` → `notify_new_voter(...)` (dùng `len(voters)` sẵn có).

### `scheduler.py` + `config.py`
- `config.ADMIN_DIGEST_TIME` mặc định "20:00".
- `_scheduled_admin_digest(app)`: `tomorrow = _target_date(1)`; nếu vote tồn tại và
  `status == open` → `send_vote_digest(app.bot, tomorrow)`.
- Job mới id `admin_digest`, CronTrigger giờ digest, `day_of_week="mon-thu"` (khớp job
  tạo vote tối), misfire_grace_time=300.

## Test
- `format_new_voter`, `format_digest` (có voters / rỗng / format ngày DD/MM).
- `notify_admins`: gửi tới tất cả admin; bỏ qua `exclude_user_id`; 1 bot lỗi không chặn.
- `notify_new_voter`: compose đúng text + gửi.
- `is_voter`: True sau khi vote, False khi chưa (test DB).

## Ngoài phạm vi
- Không gửi gì vào nhóm (chỉ chat riêng admin).
- Không đụng công thức tính tiền / round-robin (10:30 vẫn đọc DB tươi như cũ).
- Không thêm /who hay live-message lần này (đã bàn nhưng user chọn hướng push).
