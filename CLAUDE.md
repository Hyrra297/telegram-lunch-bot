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
| 18:30 | CN–T4 | Tạo vote cho ngày hôm sau (T2–T5), wording "ngày mai". **Thiếu ảnh thực đơn → KHÔNG tạo vote, nhắn riêng admin**. T5 không tạo vote cho T6 — T6 do job 08:30 đảm nhận |
| 20:00 | CN–T4 | Digest riêng admin: danh sách + số người đã đặt cho vote ngày mai. Không chạy T5 (không digest trước thứ 6) |
| 08:30 | T2–T6 | Đã có vote → nhắc số người vote; chưa có → tạo vote (lưới an toàn, vẫn cần ảnh). **T6: đây là job DUY NHẤT tạo vote bún đậu** (caption `🍜 Thực đơn bún đậu hôm nay`, poll `🥢 Hôm nay ăn bún đậu gì?`) |
| 10:30 | T2–T5 | Đóng vote + chốt sổ + phân công lấy cơm/trả hộp + tính tiền |
| 10:30 | T6 | Đóng vote + **chỉ phân công 1 picker** đi lấy bún đậu (`🛵 @X đi lấy bún đậu`). **KHÔNG phân công trả hộp, KHÔNG tính tiền** |
| 14:00 | Cuối tháng | Gửi tổng kết tiền cơm cả tháng (dạng ảnh) |
| 15:00 | T6 | **`friday_settle`**: gọi `snapshot_day_costs(date)` — tính và khoá tiền từng người vào `vote_entries.cost` (mỗi người = giá món + ship/số người). Im lặng (không gửi tin) |

Mọi ngày T2–T5 đều tạo vote từ 18:30 tối hôm trước (CN tạo vote cho T2). Riêng **thứ 6 là ngày bún đậu** — vote tạo lúc 08:30 sáng T6 (không tạo tối T5, không digest tối T5). Job 08:30
là lưới an toàn cho T2–T5 (tạo bù nếu job tối lỡ — vẫn yêu cầu có ảnh) và là job chính cho T6.
Ngoài ra: **sau digest gửi admin lúc 20:00 tối hôm trước**, mọi thay đổi vote cho ngày
đó (đặt mới, đổi món, huỷ) đều được nhắn riêng admin real-time (không vào nhóm) cho tới
khi đóng vote 10:30 — kể cả thay đổi trong buổi tối/đêm hôm trước. T6: real-time notify hoạt động từ 08:30–10:30 (sau khi vote được tạo). Trước mốc digest không
báo real-time. Cổng thời gian: `_past_evening_digest(date)` trong `handlers/vote.py`
(so giờ với `ADMIN_DIGEST_TIME` của tối hôm trước); mẫu tin trong `admin_notify.py`.

**Giá bún đậu T6 (giá theo món)**: admin nhập **giá từng món** (`dish1_price`..`dish4_price`) và **ship** trực tiếp trong web tab "Tuần này" (không còn ô "Giá/s" đơn giá). Job `friday_settle` lúc 15:00 gọi `snapshot_day_costs(date)` → khoá cost từng người vào `vote_entries.cost`. Trước 15h: tổng kết tính live (preview); sau 15h: đọc snapshot đã khoá. Công thức: `cost = giá_món_người_đó (hoặc daily_votes.price nếu không có giá món) + round(ship_fee / voter_count)`. Cột `price_override`/`ship_fee_override` còn trong DB nhưng không còn dùng.

**Template bún đậu mặc định**: Mỗi thứ 6 lúc 08:30, job morning gọi `db.apply_friday_template(date)` để tự áp menu bún đậu cố định — không cần admin làm gì. Template lưu ở `settings.friday_template` (JSON: `{"dishes": [...], "prices": [...], "ship_fee": int, "menu_image": "fri.jpg"}`). Hàm chỉ áp nếu ngày đó **chưa có món** — nếu admin đã set món khác qua web (override) hoặc dùng `/skip_today`, template không ghi đè. Để đổi menu bún đậu mặc định: cập nhật giá trị setting `friday_template` trong DB (không cần deploy lại). Ảnh dùng lại `fri.jpg` (upload một lần, tái sử dụng mỗi tuần). Từ 2026-07-02: nguồn menu thứ 6 ưu tiên **copy nguyên thứ 6 gần nhất có món** (`get_friday_source(date)` — lùi tối đa 8 tuần), `friday_template` chỉ còn là **fallback** khi chưa từng có thứ 6 nào có món. Web tab "Tuần này" cũng preview thứ 6 sắp tới bằng chính nguồn này (`_apply_friday_preview`) nên hiện sẵn món/giá/ảnh cả tuần, kèm nhãn "🍜 Bún đậu (theo tuần trước)". Sửa menu một thứ 6 → thứ 6 sau tự kế thừa.

Cấu hình trong `.env`: `VOTE_OPEN_TIME` (08:30), `EVENING_OPEN_TIME` (18:30), `ANNOUNCE_TIME` (10:30), `ADMIN_DIGEST_TIME` (20:00)

## Cấu trúc file quan trọng
- `bot.py` — entry point bot, đăng ký handlers + `set_my_commands`
- `config.py` — đọc `.env`
- `database.py` — toàn bộ SQL queries
- `scheduler.py` — 6 jobs: open_vote_evening (18:30 CN–T4), admin_digest (20:00 CN–T4), morning (08:30 T2–T6), announce_roles (10:30 T2–T6), friday_settle (15:00 T6), monthly_summary (14:00)
- `admin_notify.py` — thông báo vote riêng cho admin (digest + real-time), gửi vào chat với bot
- `image_summary.py` — render bảng tổng kết tiền cơm thành ảnh PNG (Pillow + font DejaVuSans)
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
                 --   dish1-4, poll_id, poll_message_id, price, ship_fee, menu_image,
                 --   dish1_price..dish4_price (nullable, giá từng món T6),
                 --   price_override/ship_fee_override (nullable, dormant — không dùng nữa)
vote_entries     -- date+user_id PK, dish, cost (nullable — snapshot 15h T6)
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

- **T2–T5 (cơm)**: `price + round(ship_fee / voter_count)` cho mỗi ngày. Mặc định: 45,000đ + 20,000đ ship chia đều số người vote.
- **T6 (bún đậu) — giá theo món**: mỗi người trả theo món đã chọn. Công thức: `cost = dish_price_người_đó (hoặc daily_votes.price nếu không có giá món) + round(ship_fee / voter_count)`. Trước 15h: tổng kết tính live (preview); sau 15h: đọc `vote_entries.cost` đã khoá (snapshot). Job `friday_settle` 15:00 gọi `snapshot_day_costs(date)` để khoá. Admin nhập giá từng món + ship qua web tab "Tuần này".
- Cả `/summary` bot và web dashboard dùng cùng công thức (`get_monthly_summary` và `get_monthly_detail`).

### Security (web login)
- Timing-safe: `hmac.compare_digest`
- Rate limiting: 5 lần/5 phút per IP (in-memory `_login_attempts`)
- Open redirect prevention: `_safe_redirect()` chỉ cho phép path bắt đầu bằng `/` không phải `//`

### Web dashboard

- Tab "Tuần này": xem ai đặt, nhập 4 món cho từng ngày (admin); riêng T6 nhập **giá từng món** (`dish1_price`..`dish4_price`) + **ship** cho bún đậu (đã bỏ ô "Giá/s" đơn giá)
- Tab "Tháng": bảng chi tiết tiền từng người, nút toggle paid
- Tab "Lịch sử": các ngày đã đóng vote
- Ngày đã qua mà status vẫn `open` → hiện là `closed` (fix trong `get_week_data`)

## Conventions
- Web và bot dùng chung SQLite — không conflict nhờ WAL mode
- Admin check: `user_id in config.ADMIN_IDS`
- `close_daily_vote()`: đóng + chọn người (dùng lúc 10:30). T2–T5: picker + returner; T6 (bún đậu): chỉ picker (returner = None)
- `set_vote_closed()`: chỉ đóng, chưa chọn người (dùng trong announce_roles lúc 10:30)
- **Giới hạn**: Lệnh admin thủ công `/close_vote` và `/assign` KHÔNG áp logic thứ 6 — nếu admin tự đóng/phân công vote thứ 6 sẽ vẫn gán người trả hộp và tính tiền ngay (logic cơm). Ngày bún đậu nên để luồng tự động (10:30 chỉ picker, 15:00 friday_settle) xử lý.
- Web cần restart uvicorn sau khi sửa code Python

## Lưu ý khi deploy
- Fly.io: `fly.toml` đã có; `fly` CLI cần cài riêng (chưa có trên máy này)
- Biến môi trường bắt buộc: `BOT_TOKEN`, `CHAT_ID`, `ADMIN_IDS`
- Biến tuỳ chọn: `ANTHROPIC_API_KEY` (Claude Vision đọc menu từ ảnh)
- **Không commit `.env`** — chứa token thật
- Giá mặc định: `PRICE_PER_MEAL=45000`, `SHIP_FEE=20000`
