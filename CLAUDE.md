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
| 18:00 | CN–T4 | Tạo vote cho ngày hôm sau (T2–T5), wording "ngày mai". **Thiếu ảnh thực đơn → KHÔNG tạo vote, nhắn riêng admin** |
| 20:00 | T5 | **`open_vote_friday`**: tạo vote bún đậu cho **thứ 6** (offset=1, carryover menu từ thứ 6 trước), wording "ngày mai". Thứ 6 KHÔNG digest |
| 19:00 | CN–T4 | Digest riêng admin: danh sách + số người đã đặt cho vote ngày mai. Không chạy T5 (không digest trước thứ 6) |
| 08:30 | T2–T6 | Đã có vote → nhắc số người vote; chưa có → tạo vote (lưới an toàn, vẫn cần ảnh). Thứ 6: giờ vote đã có từ 20:00 T5 → 08:30 chỉ **nhắc** như mọi ngày (job 08:30 vẫn là lưới an toàn nếu job 20:00 lỡ) |
| 09:30 | T2–T6 | **`early_close`**: CHỈ đóng vote cho ngày admin tick "⏱️ Đóng vote 9:30" (`daily_votes.early_close=1`) — gọi `lock_vote_now()` (đóng poll + phân công + tính tiền, y như 10:30 nhưng sớm hơn). Ngày không tick: không làm gì, vote mở tới 10:30 như thường. Giờ đổi qua `EARLY_CLOSE_TIME` |
| 10:30 | T2–T5 | Đóng vote + chốt sổ + phân công lấy cơm/trả hộp + tính tiền. **Ngày tick "Cơm tòa nhà"** (`daily_votes.building_order=1`): chỉ gửi tin chốt sổ (không giải thích lý do), KHÔNG phân công lấy/trả (round-robin giữ nguyên), KHÔNG tính ship. **Ngày tick "Freeship"** (`daily_votes.freeship=1`): phân công như thường, chỉ bỏ ship |
| 10:30 | T6 | Đóng vote + **1 picker** đi lấy bún đậu (luôn 1 người, bất kể số suất). **KHÔNG phân công trả hộp, KHÔNG tính tiền** |
| 14:00 | Cuối tháng | Gửi tổng kết tiền cơm cả tháng (dạng ảnh) |
| 15:00 | T6 | **`friday_settle`**: gọi `snapshot_day_costs(date)` — tính và khoá tiền từng người vào `vote_entries.cost` (mỗi người = giá món + ship/số người). Im lặng (không gửi tin) |

Mọi ngày T2–T5 đều tạo vote từ 18:00 tối hôm trước (CN tạo vote cho T2). Riêng **thứ 6 là ngày bún đậu** — vote tạo lúc **20:00 tối thứ 5** (job `open_vote_friday`, carryover menu từ thứ 6 trước), KHÔNG digest. Job 08:30 thứ 6 khi đó chỉ **nhắc** số người đặt như các ngày khác (và là lưới an toàn tạo bù nếu job 20:00 lỡ).
Ngoài ra: **sau digest gửi admin lúc 19:00 tối hôm trước**, mọi thay đổi vote cho ngày
đó (đặt mới, đổi món, huỷ) đều được nhắn riêng admin real-time (không vào nhóm) cho tới
khi đóng vote 10:30 — kể cả thay đổi trong buổi tối/đêm hôm trước. T6: real-time notify hoạt động từ **20:00 thứ 5**–10:30 thứ 6 (sau khi vote được tạo 20:00 T5). Trước mốc digest không
báo real-time. Cổng thời gian: `_past_evening_digest(date)` trong `handlers/vote.py`
(so giờ với `ADMIN_DIGEST_TIME` của tối hôm trước); mẫu tin trong `admin_notify.py`.

**Giá bún đậu T6 (giá theo món)**: admin nhập **giá từng món** (`dish1_price`..`dish4_price`) và **ship** trực tiếp trong web tab "Tuần này" (không còn ô "Giá/s" đơn giá). Job `friday_settle` lúc 15:00 gọi `snapshot_day_costs(date)` → khoá cost từng người vào `vote_entries.cost`. Trước 15h: tổng kết tính live (preview); sau 15h: đọc snapshot đã khoá. Công thức: `cost = giá_món_người_đó (hoặc daily_votes.price nếu không có giá món) + round(ship_fee / voter_count)`. Cột `price_override`/`ship_fee_override` còn trong DB nhưng không còn dùng.

**Template bún đậu mặc định**: Mỗi thứ 6 lúc 08:30, job morning gọi `db.apply_friday_template(date)` để tự áp menu bún đậu cố định — không cần admin làm gì. Template lưu ở `settings.friday_template` (JSON: `{"dishes": [...], "prices": [...], "ship_fee": int, "menu_image": "fri.jpg"}`). Hàm chỉ áp nếu ngày đó **chưa có món** — nếu admin đã set món khác qua web (override) hoặc dùng `/skip_today`, template không ghi đè. Để đổi menu bún đậu mặc định: cập nhật giá trị setting `friday_template` trong DB (không cần deploy lại). Ảnh dùng lại `fri.jpg` (upload một lần, tái sử dụng mỗi tuần). Từ 2026-07-02: nguồn menu thứ 6 ưu tiên **copy nguyên thứ 6 gần nhất có món** (`get_friday_source(date)` — lùi tối đa 8 tuần), `friday_template` chỉ còn là **fallback** khi chưa từng có thứ 6 nào có món. Web tab "Tuần này" cũng preview thứ 6 sắp tới bằng chính nguồn này (`_apply_friday_preview`) nên hiện sẵn món/giá/ảnh cả tuần, kèm nhãn "🍜 Bún đậu (theo tuần trước)". Sửa menu một thứ 6 → thứ 6 sau tự kế thừa.

Cấu hình trong `.env`: `VOTE_OPEN_TIME` (08:30), `EVENING_OPEN_TIME` (18:00), `ANNOUNCE_TIME` (10:30), `ADMIN_DIGEST_TIME` (19:00), `EARLY_CLOSE_TIME` (09:30)

## Mở vote bằng tay
- **`/open_vote_mai`** — mở vote cho **ngày mai**, dùng khi job 18:00 (hoặc 20:00 T5) đã lỡ vì lúc đó chưa có ảnh thực đơn. Đi qua `scheduler.open_vote_for(bot, day_offset=1, require_image=False)` — cùng hàm với job tự động nên **tự áp menu bún đậu + ship của thứ 6 + wording đúng**; khác duy nhất: KHÔNG bắt buộc có ảnh (admin đã chủ động gõ lệnh).
- **`/open_vote`** (hôm nay) vẫn là code riêng cũ trong `handlers/vote.py` — có Claude Vision đọc ảnh menu, nhưng **KHÔNG áp menu bún đậu thứ 6, không dùng ship của ngày, wording luôn là "Hôm nay ăn gì?"**. Mở vote thứ 6 bằng lệnh này sẽ ra sai món/giá → nên dùng `/open_vote_mai` từ tối thứ 5, hoặc để job tự động.

## Đóng vote sớm / đóng tay
Hai đường đóng vote đều gọi **cùng một luật** trong `roles.py` (`assign_and_settle`) qua `handlers.vote.lock_vote_now(bot, date)` nên không lệch nhau — thứ 6 chỉ 1 người lấy, ngày cơm tòa nhà không phân công, freeship không cộng ship:
- **Job `early_close` 09:30** — tự động, chỉ cho ngày `roles.closes_early(daily)` (tick `early_close` HOẶC `building_order`).
- **`/close_vote`** trong Telegram (lệnh admin, có từ trước).

**Đã thử và bỏ — đừng làm lại:**
1. *Nút inline dưới poll* (`send_poll(reply_markup=...)` — Telegram CHO gắn, đã kiểm chứng). Bỏ vì inline keyboard là thuộc tính của message nên **cả nhóm đều thấy nút**, không ẩn theo người được. Nếu cần nút trong Telegram mà không lộ: gửi tin riêng admin kèm nút (như `admin_notify`), đừng gắn vào poll nhóm.
2. *Nút "Đóng vote ngay" trên web* (`POST /close-vote`). Bỏ theo yêu cầu user (2026-08-24): đã có đóng tự động 9:30/10:30 nên nút bấm tay là dư.

Sau khi đóng sớm, job 10:30 thấy `picker_user_id` đã có (hoặc ngày tòa nhà đã `closed`) → im lặng, không phân công lại, không gửi tin trùng.

## Cấu trúc file quan trọng
- `bot.py` — entry point bot, đăng ký handlers + `set_my_commands`
- `config.py` — đọc `.env`
- `database.py` — toàn bộ SQL queries
- `roles.py` — **luật chốt sổ dùng chung**: `assign_and_settle()` (phân công + khoá tiền theo loại ngày), `cost_per_person()`, `is_friday()`, `meal_name()`. Dùng bởi scheduler 10:30, `/close_vote`, nút 🔒, `/assign` — sửa luật chỉ sửa ở đây
- `scheduler.py` — 8 jobs: open_vote_evening (18:00 CN–T4), open_vote_friday (20:00 T5), admin_digest (19:00 CN–T4), morning (08:30 T2–T6), early_close (09:30 T2–T6), announce_roles (10:30 T2–T6), friday_settle (15:00 T6), monthly_summary (14:00)
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
                 --   dish1-5, poll_id, poll_message_id, price, ship_fee, menu_image,
                 --   dish1_price..dish5_price (nullable, giá từng món T6),
                 --   building_order (0/1 — cơm tòa nhà: không phân công lấy/trả, không ship),
                 --   freeship (0/1 — bỏ tiền ship, vẫn phân công bình thường),
                 --   early_close (0/1 — đóng vote 9:30 thay vì 10:30),
                 --   price_override/ship_fee_override (nullable, dormant — không dùng nữa)
vote_entries     -- date+user_id PK, dish, cost (nullable — snapshot 15h T6)
settings         -- key/value (price, ship_fee, open_time, close_time)
monthly_payments -- year_month+user_id PK
```

Migration thêm cột: vòng lặp `try/except ALTER TABLE` trong `init_db()`.

## Tính năng đã implement

### Vote poll
- Nếu admin nhập món ăn trong web → bot gửi native Telegram poll với tối đa 5 món (`database.MAX_DISHES`)
- Nếu không có món → fallback inline keyboard ✅/❌
- `PollAnswerHandler` xử lý vote từ native poll → ghi vào `vote_entries.dish`

### Round-robin phân công
- **Lấy cơm**: `rotation_index` + `last_picked_at`
- **Trả hộp**: `return_index` + `last_returned_at` (queue độc lập)
- Thành viên mới join vào cuối cả 2 queue
- Chỉ chọn từ những người đã vote hôm đó

### Người chuyển tiền luôn "đã đóng"
`settings.treasurer_user_id` (prod: `462506085` — Nguyễn Quang Hưng) là người gom tiền cả nhóm rồi chuyển cho quán, nên **luôn được tính là đã đóng, không cần đánh dấu mỗi tháng**. Cài ở `get_paid_user_ids()` (union thêm treasurer) nên áp cho mọi nơi đọc trạng thái: web dashboard, ảnh tổng kết tháng (scheduler 14:00 + `/summary`), `/dong_tien`, `/tien`. Web hiện chữ "(người chuyển tiền)" thay cho nút Huỷ/Đánh dấu. Đổi người: `UPDATE settings SET value='<user_id>' WHERE key='treasurer_user_id'` (không cần deploy).

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

- **Giá theo món áp cho MỌI ngày** (không chỉ T6): `unit = dish_price của món người đó chọn; NULL → daily_votes.price`. Admin nhập giá từng món trên web, để trống là 45k mặc định.

- **T2–T5 (cơm)**: `price + round(ship_fee / voter_count)` cho mỗi ngày. Mặc định: 45,000đ + 20,000đ ship chia đều số người vote.
- **T6 (bún đậu) — giá theo món**: mỗi người trả theo món đã chọn. Công thức: `cost = dish_price_người_đó (hoặc daily_votes.price nếu không có giá món) + round(ship_fee / voter_count)`. Trước 15h: tổng kết tính live (preview); sau 15h: đọc `vote_entries.cost` đã khoá (snapshot). Job `friday_settle` 15:00 gọi `snapshot_day_costs(date)` để khoá. Admin nhập giá từng món + ship qua web tab "Tuần này".
- Cả `/summary` bot và web dashboard dùng cùng công thức (`get_monthly_summary` và `get_monthly_detail`).

### Security (web login)
- Timing-safe: `hmac.compare_digest`
- Rate limiting: 5 lần/5 phút per IP (in-memory `_login_attempts`)
- Open redirect prevention: `_safe_redirect()` chỉ cho phép path bắt đầu bằng `/` không phải `//`

### Web dashboard

- Tab "Tuần này": xem ai đặt, nhập tối đa 5 món cho từng ngày (admin), **mỗi món có ô giá riêng** (`dish1_price`..`dish5_price`) — để trống = `daily_votes.price` (45k), dùng khi một số suất giá khác (VD 50k). Ô **ship** chỉ hiện ở T6.
- Tab "Tuần này" — 2 ô tick per ngày (admin, cùng endpoint `POST /toggle-day-flag` với `flag=building_order|freeship`, whitelist `db.DAY_FLAGS`):
  - **🏢 Cơm tòa nhà** (`daily_votes.building_order`) — **ô tick DUY NHẤT trên web**, gồm cả 3 tác dụng: KHÔNG phân công lấy cơm/trả hộp (round-robin không advance), KHÔNG tính ship, và đóng vote 9:30. Tin nhắn chỉ "Chốt sổ!/Vote đã đóng! N người đặt cơm." — không giải thích lý do. Ý nghĩa ghi 1 dòng ở `card-header` tab "Tuần này" (chỉ admin thấy), không lặp trong từng ô ngày.
  - `freeship` và `early_close` vẫn là cột DB + logic thật, nhưng **không còn ô tick trên web** (user bỏ 2026-08-24 vì cơm tòa nhà đã bao hàm). Muốn bật riêng cho một ngày: gọi `POST /toggle-day-flag` với `flag=freeship|early_close`, hoặc `db.set_day_flag(...)`. Endpoint và whitelist `DAY_FLAGS` vẫn nhận cả 3.
  - Ngụ ý được tính ở tầng đọc, KHÔNG ghi đè DB: ship qua `database._effective_ship`, đóng sớm qua `roles.closes_early`. Bỏ tick tòa nhà là 2 cờ kia trở về đúng giá trị đã lưu.
  - Ai cũng thấy badge "🏢 Cơm tòa nhà" / "🚚 Freeship" trên ô ngày. Ship = 0 áp cả 4 chỗ tính tiền: `get_monthly_summary`, `get_monthly_detail`, `snapshot_day_costs` (helper `_effective_ship`), scheduler 10:30 và `/assign`. `/close_vote` thủ công vẫn KHÔNG áp logic building_order (giống giới hạn thứ 6) — ngày tòa nhà nên để luồng tự động xử lý.
- Tab "Tháng": bảng chi tiết tiền từng người, nút toggle paid
- Tab "Lịch sử": các ngày đã đóng vote
- Ngày đã qua mà status vẫn `open` → hiện là `closed` (fix trong `get_week_data`)

## Conventions
- Web và bot dùng chung SQLite — không conflict nhờ WAL mode
- Admin check: `user_id in config.ADMIN_IDS`
- `close_daily_vote()`: đóng + chọn người (dùng lúc 10:30). T2–T5: picker + returner; T6 (bún đậu): luôn chỉ 1 picker (bất kể số suất), không dùng `returner_user_id`. T6 không phân công trả hộp và không tính tiền lúc 10:30.
- `set_vote_closed()`: chỉ đóng, chưa chọn người (dùng trong announce_roles lúc 10:30)
- `/close_vote`, nút 🔒 và `/assign` đều đi qua `roles.assign_and_settle()` nên áp ĐÚNG luật thứ 6 / cơm tòa nhà / freeship (từ 2026-08-24; trước đó chúng gán sai cho ngày bún đậu).
- Web cần restart uvicorn sau khi sửa code Python

## Lưu ý khi deploy
- Fly.io: `fly.toml` đã có; `fly` CLI cần cài riêng (chưa có trên máy này)
- Biến môi trường bắt buộc: `BOT_TOKEN`, `CHAT_ID`, `ADMIN_IDS`
- Biến tuỳ chọn: `ANTHROPIC_API_KEY` (Claude Vision đọc menu từ ảnh)
- **Không commit `.env`** — chứa token thật
- Giá mặc định: `PRICE_PER_MEAL=45000`, `SHIP_FEE=20000`
