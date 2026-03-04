# Telegram Lunch Bot — Tài liệu hệ thống

## Cấu trúc thư mục

```
telegram-lunch-bot/
├── bot.py              # Entry point — khởi động bot Telegram
├── config.py           # Đọc biến môi trường (.env)
├── database.py         # Tất cả logic tương tác SQLite
├── scheduler.py        # Tự động mở/đóng vote theo giờ
├── handlers/
│   ├── vote.py         # /open_vote, /close_vote, xử lý poll
│   ├── admin.py        # /add_user, /remove_user, /rotation, /reset_vote
│   ├── summary.py      # /summary — tóm tắt tháng
│   ├── payment.py      # /dong_tien + callback xác nhận
│   └── menu.py         # Nhận ảnh thực đơn qua Telegram
├── web/
│   ├── app.py          # FastAPI web dashboard
│   └── templates/
│       └── index.html  # Giao diện web
└── static/
    ├── menus/          # Ảnh thực đơn upload lên
    └── qr/             # Ảnh QR ZaloPay/bank
```

---

## Luồng hoạt động chính

### 1. Khởi động (`bot.py`)

```
bot.py
  └── post_init()
        ├── init_db()         → Tạo/migrate database SQLite
        └── scheduler.start() → Bắt đầu lịch tự động
```

Bot chạy **polling** — liên tục hỏi Telegram API có tin nhắn mới không, không cần server public.

---

### 2. Mở vote hàng ngày

```
8:00 sáng (scheduler) hoặc /open_vote (admin)
  │
  ├── get_menu_items(today)
  │     └── Lấy dish1–4 từ DB (admin nhập trên web)
  │
  ├── [Có món] → send_poll()       ← Native Telegram poll
  │     └── PollAnswerHandler      ← Telegram gửi update khi ai vote
  │           └── vote_for_dish()  → Ghi vào vote_entries
  │
  └── [Không có món] → send_message() + InlineKeyboard ✅/❌
        └── CallbackQueryHandler
              └── toggle_vote()    → Ghi/xóa vote_entries
```

---

### 3. Đóng vote

```
10:30 (scheduler) hoặc /close_vote (admin)
  │
  ├── get_voters(today)        → Ai đặt cơm?
  ├── pick_next_fetcher()      → Round-robin: người lấy cơm
  ├── pick_next_returner()     → Round-robin riêng: người trả hộp
  ├── close_daily_vote()       → Update DB, ghi last_picked_at
  └── stop_poll()              → Đóng poll Telegram
```

**Round-robin**: Mỗi user có `rotation_index` (lấy cơm) và `return_index` (trả hộp).
Mỗi lần đóng vote, hệ thống tìm người tiếp theo sau index của người vừa được chọn lần trước. Hết vòng thì quay lại đầu.

---

### 4. Database (SQLite)

| Bảng | Lưu gì |
|---|---|
| `users` | Danh sách thành viên + rotation index |
| `daily_votes` | Mỗi ngày: giá, status, ai lấy cơm, ai trả hộp, 4 món |
| `vote_entries` | Ai đặt cơm ngày nào, chọn món gì |
| `settings` | Cấu hình động (giá, phí ship) |
| `monthly_payments` | Ai đã đóng tiền tháng nào |

---

### 5. Web Dashboard (FastAPI)

Chạy song song với bot (2 process riêng biệt).

```
Admin truy cập web
  ├── Tab "Tuần này"  → Xem ai đặt, nhập 4 món cho từng ngày
  ├── Tab "Tháng"     → Bảng chi tiết từng người đóng bao nhiêu
  └── Tab "Lịch sử"  → Xem các ngày đã đóng vote
```

Web và bot **dùng chung 1 file SQLite** — SQLite dùng WAL mode để tránh xung đột đọc/ghi đồng thời.

---

### 6. /dong_tien

```
User: /dong_tien
  └── Bot gửi vào nhóm: "💰 @An báo đã đóng tiền tháng 3/2026"
        + nút [✅ Xác nhận đã nhận tiền]

Admin bấm nút
  ├── Kiểm tra người bấm có trong ADMIN_IDS không
  ├── toggle_monthly_paid() → Ghi vào monthly_payments
  ├── Xóa nút khỏi tin nhắn cũ
  └── Gửi thông báo công khai: "✅ @An đã đóng tiền — xác nhận bởi Admin"
```

Trạng thái đóng tiền hiển thị ✅ trên web dashboard tab tháng.

---

## Commands tham khảo

| Lệnh | Ai dùng | Chức năng |
|---|---|---|
| `/open_vote` | Admin | Mở vote thủ công |
| `/close_vote` | Admin | Đóng vote thủ công |
| `/add_user` | Admin | Thêm thành viên |
| `/remove_user` | Admin | Xóa thành viên |
| `/rotation` | Admin | Xem thứ tự lượt lấy/trả |
| `/reset_vote` | Admin | Xóa vote hôm nay để test lại |
| `/summary` | Tất cả | Tóm tắt đặt cơm tháng này |
| `/dong_tien` | Thành viên | Báo đã đóng tiền tháng |
