# Telegram Lunch Bot — Hướng dẫn cho Claude

## Tech stack
- Python 3.8, python-telegram-bot 21.x, FastAPI, aiosqlite, APScheduler
- SQLite (WAL mode), Timezone: Asia/Ho_Chi_Minh

## Chạy local
```bash
# Bot Telegram
python bot.py

# Web dashboard
python -m uvicorn web.app:app --port 8080
```

## Kill & restart bot
Dùng skill `/kill-bot` — kill toàn bộ bot.py processes qua WMI rồi restart sạch.

Hoặc thủ công:
```bash
wmic process where "commandline like '%bot.py%'" delete
python bot.py
```

**Lưu ý quan trọng**:
- `taskkill` không hoạt động từ bash tool trên Windows. Phải dùng `wmic`.
- Khi bị lỗi `Conflict: terminated by other getUpdates request`, kiểm tra cả `main.py` lẫn `bot.py` đang chạy — cần kill cả hai: `wmic process where "name='python.exe'" delete`
- Khi cần kill uvicorn: `wmic process where "commandline like '%uvicorn%'" delete`

## Lịch tự động (scheduler)
| Giờ | Ngày | Hành động |
|---|---|---|
| 19:00 | T2–T5 | Tạo vote cho ngày hôm sau (T3–T6), wording "ngày mai" |
| 08:30 | T2–T6 | Đã có vote → nhắc số người vote; chưa có → tạo vote (lưới an toàn) |
| 10:30 | T2–T6 | Đóng vote + chốt sổ + phân công lấy cơm/trả hộp |
| 14:00 | Cuối tháng | Gửi tổng kết tiền cơm cả tháng |

Vote T3→T6 tạo từ 19:00 tối hôm trước; vote T2 tạo sáng 08:30. Job 08:30 vừa
là lưới an toàn (tạo bù nếu job tối lỡ) vừa gửi tin nhắc nếu vote đã có.

Cấu hình trong `.env`: `VOTE_OPEN_TIME` (08:30), `EVENING_OPEN_TIME` (19:00), `ANNOUNCE_TIME` (10:30)

## Cấu trúc file quan trọng
- `bot.py` — entry point bot, đăng ký handlers + `set_my_commands`
- `config.py` — đọc `.env`
- `database.py` — toàn bộ SQL queries
- `scheduler.py` — 4 jobs: open_vote_evening (19:00), morning (08:30), announce_roles (10:30), monthly_summary (14:00)
- `handlers/vote.py` — open/close vote, poll answer, inline keyboard fallback
- `handlers/admin.py` — quản lý thành viên, cài đặt, /reset_vote
- `handlers/payment.py` — /dong_tien + admin confirm callback
- `handlers/help.py` — /help command (user vs admin khác nhau)
- `web/app.py` — FastAPI routes
- `web/templates/index.html` — dashboard UI

## Database schema
```sql
users            -- id, username, full_name, rotation_index, return_index, active
daily_votes      -- date PK, status (open/closed/none), picker_user_id, returner_user_id,
                 --   dish1-4, poll_id, poll_message_id, price, ship_fee, menu_image
vote_entries     -- date+user_id PK, dish
settings         -- key/value (price, ship_fee, open_time, close_time)
monthly_payments -- year_month+user_id PK
```

Migration thêm cột: vòng lặp `try/except ALTER TABLE` trong `init_db()`.

## Tính năng đã implement

### Vote poll
- Nếu admin nhập món ăn trong web → bot gửi native Telegram poll với tối đa 4 món
- Nếu không có món → fallback inline keyboard ✅/❌
- `PollAnswerHandler` xử lý vote từ native poll → ghi vào `vote_entries.dish`

### Round-robin phân công
- **Lấy cơm**: `rotation_index` + `last_picked_at`
- **Trả hộp**: `return_index` + `last_returned_at` (queue độc lập)
- Thành viên mới join vào cuối cả 2 queue
- Chỉ chọn từ những người đã vote hôm đó

### /dong_tien
- Bất kỳ ai trong nhóm đều gõ được (không cần active member)
- Bot gửi vào nhóm kèm nút [✅ Xác nhận] cho admin
- Admin xác nhận → ghi `monthly_payments`, thông báo công khai
- Web dashboard hiện trạng thái đã/chưa đóng tiền

### /help
- User thường: thấy 3 lệnh cơ bản (summary, dong_tien, help)
- Admin: thấy đầy đủ 11 lệnh (+ open_vote, close_vote, add_member, remove_member, set_price, set_time, rotation, reset_vote, skip_today)
- `set_my_commands` scope: default (3 lệnh) + `BotCommandScopeChat(admin_id)` (11 lệnh trong private chat)
- Admin KHÔNG thấy lệnh quản trị trong nhóm (bỏ `BotCommandScopeChatMember` để tránh lộ)

### /skip_today
- Admin dùng khi hôm nay không đặt cơm — không gửi poll, không thông báo
- Set status = 'closed' trong daily_votes, bỏ qua round-robin

### Tính tiền
- Công thức: `price + round(ship_fee / voter_count)` cho mỗi ngày
- Mặc định: 45,000đ + 20,000đ ship chia đều số người vote
- Cả `/summary` bot và web dashboard dùng cùng công thức (`get_monthly_summary` và `get_monthly_detail`)

### Security (web login)
- Timing-safe: `hmac.compare_digest`
- Rate limiting: 5 lần/5 phút per IP (in-memory `_login_attempts`)
- Open redirect prevention: `_safe_redirect()` chỉ cho phép path bắt đầu bằng `/` không phải `//`

### Web dashboard
- Tab "Tuần này": xem ai đặt, nhập 4 món cho từng ngày (admin)
- Tab "Tháng": bảng chi tiết tiền từng người, nút toggle paid
- Tab "Lịch sử": các ngày đã đóng vote
- Ngày đã qua mà status vẫn `open` → hiện là `closed` (fix trong `get_week_data`)

## Conventions
- Web và bot dùng chung SQLite — không conflict nhờ WAL mode
- Admin check: `user_id in config.ADMIN_IDS`
- `close_daily_vote()`: đóng + chọn picker/returner (dùng lúc 10:30)
- `set_vote_closed()`: chỉ đóng, chưa chọn người (dùng trong announce_roles lúc 10:30)
- Web cần restart uvicorn sau khi sửa code Python

## Lưu ý khi deploy
- Fly.io: `fly.toml` đã có; `fly` CLI cần cài riêng (chưa có trên máy này)
- Biến môi trường bắt buộc: `BOT_TOKEN`, `CHAT_ID`, `ADMIN_IDS`
- Biến tuỳ chọn: `ANTHROPIC_API_KEY` (Claude Vision đọc menu từ ảnh)
- **Không commit `.env`** — chứa token thật
- Giá mặc định: `PRICE_PER_MEAL=45000`, `SHIP_FEE=20000`
