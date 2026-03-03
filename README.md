# Telegram Lunch Bot 🍱

Bot Telegram quản lý đặt cơm hàng ngày cho nhóm.

## Tính năng
- **Vote hàng ngày**: Tự động mở/đóng vote đặt cơm theo giờ đã cài
- **Chọn người lấy cơm**: Luân phiên theo thứ tự, ưu tiên từ danh sách người đã vote hôm đó
- **Tổng kết tháng**: Hiển thị số suất và số tiền mỗi người cần trả

## Cài đặt

### 1. Yêu cầu
- Python 3.11+
- Tài khoản Telegram và bot token từ [@BotFather](https://t.me/BotFather)

### 2. Cài thư viện
```bash
pip install -r requirements.txt
```

### 3. Cấu hình
```bash
cp .env.example .env
# Chỉnh sửa file .env với thông tin của bạn
```

**Cách lấy CHAT_ID:**
1. Thêm bot vào nhóm
2. Gửi 1 tin nhắn bất kỳ trong nhóm
3. Truy cập `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Tìm `"chat":{"id": -100xxxxxxxxx}` - đó là CHAT_ID

**Cách lấy ADMIN_IDS:**
- Nhắn tin [@userinfobot](https://t.me/userinfobot) để biết user_id của bạn

### 4. Thêm thành viên vào danh sách
Sau khi bot chạy, admin reply vào tin nhắn của từng thành viên và dùng:
```
/add_member
```

### 5. Chạy bot
```bash
python bot.py
```

## Lệnh Bot

| Lệnh | Ai dùng | Mô tả |
|------|---------|-------|
| `/open_vote` | Admin | Mở vote đặt cơm ngay lập tức |
| `/close_vote` | Admin | Đóng vote và thông báo người lấy cơm |
| `/summary` | Tất cả | Tổng kết chi tiêu tháng hiện tại |
| `/summary 2026-03` | Tất cả | Tổng kết tháng cụ thể |
| `/set_price 35000` | Admin | Cập nhật giá mỗi suất |
| `/set_time 08:00 10:30` | Admin | Cập nhật giờ mở/đóng vote |
| `/add_member` | Admin | Thêm thành viên (reply tin nhắn người đó) |
| `/remove_member` | Admin | Xoá thành viên (reply tin nhắn người đó) |
| `/rotation` | Admin | Xem thứ tự luân phiên lấy cơm |

## Cách hoạt động

### Vote hàng ngày
1. Đến giờ mở (mặc định 08:00), bot tự gửi tin nhắn vote vào nhóm
2. Thành viên bấm **✅ Tôi đặt** hoặc **❌ Bỏ phiếu**
3. Tin nhắn cập nhật danh sách người đặt realtime
4. Đến giờ đóng (mặc định 10:30), bot đóng vote và thông báo người đi lấy cơm

### Luân phiên lấy cơm
- Danh sách thành viên xếp theo thứ tự `rotation_index`
- Mỗi ngày, từ danh sách người đã vote, chọn người tiếp theo trong vòng xoay sau người được chọn hôm trước
- Nếu người tiếp theo không vote hôm đó, bỏ qua và xét người kế tiếp
- Hết vòng thì quay về đầu

### Tổng kết tháng
```
📊 Tổng kết tháng 3/2026
────────────────────────
👤 Nguyễn A         : 18 suất = 630,000đ
👤 Trần B           : 15 suất = 525,000đ
👤 Lê C             : 20 suất = 700,000đ
────────────────────────
Giá mỗi suất: 35,000đ
```

## Cấu trúc project
```
telegram-lunch-bot/
├── bot.py              # Điểm khởi động
├── config.py           # Đọc cấu hình .env
├── database.py         # Khởi tạo DB và các hàm truy vấn
├── scheduler.py        # Lịch tự động mở/đóng vote
├── handlers/
│   ├── vote.py         # Lệnh vote và callback button
│   ├── admin.py        # Lệnh quản trị
│   └── summary.py      # Lệnh tổng kết
├── requirements.txt
├── .env.example
└── lunch_bot.db        # SQLite database (tự tạo khi chạy)
```
