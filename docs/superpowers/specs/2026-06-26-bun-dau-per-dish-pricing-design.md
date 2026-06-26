# Thiết kế: Giá theo món cho ngày bún đậu (per-dish pricing)

**Ngày:** 2026-06-26
**Bối cảnh:** Tính năng "ngày thứ 6 = bún đậu" vừa ship dùng **1 giá chung/ngày** (`daily_votes.price` + `price_override`). Nhưng bún đậu mỗi suất giá khác nhau → cần tính tiền **theo món**. Thay phần đơn giá chung bằng giá theo món, giữ luồng T6 (vote 8h30, 1 picker 10h30, chốt 15h) đã có.

## Mục tiêu

1. Mỗi món trong menu có **giá riêng**; mỗi người trả **giá món họ chọn + ship chia đều**.
2. **15h thứ 6**: chốt (snapshot) số tiền mỗi người → khoá; sau 15h sửa giá món không đổi số đã chốt. Trước 15h bảng tính **live** (xem trước).
3. Bỏ ô "Giá/s" đơn giá chung; giữ ô "Ship". Ngừng dùng `price_override`.
4. Ngày cơm thường (không nhập giá món) → vẫn 1 giá chung như cũ (không đổi hành vi).

## Mô hình dữ liệu

- `daily_votes`: thêm `dish1_price, dish2_price, dish3_price, dish4_price` (nullable INTEGER) — giá cho từng món `dish1–4`.
- `vote_entries`: thêm `cost` (nullable INTEGER) — **snapshot** tiền mỗi người sau khi chốt 15h. NULL = chưa chốt → tính live.
- Giữ nguyên: `daily_votes.price` (giá fallback = giá toàn cục cơm), `daily_votes.ship_fee` (ship/ngày), `vote_entries.dish` (text — món người đó chọn, khớp `dish1–4`).
- `price_override` / `ship_fee_override` (cột Task trước): **ngừng dùng**, để lại trong DB (SQLite khó DROP COLUMN). Không đọc/ghi nữa.

## Công thức tính tiền (1 nguồn dùng chung)

Cho mỗi `vote_entries` của 1 ngày `closed`:

```
nếu ve.cost IS NOT NULL:   per_person = ve.cost            # đã chốt (khoá)
ngược lại:                 per_person = dish_price + round(ship / count)
  trong đó:
    dish_price = giá của món ve.dish (khớp dish1–4 → dishN_price), nếu NULL → daily_votes.price
    ship       = daily_votes.ship_fee
    count      = số người vote ngày đó
```

Khớp món → giá bằng SQL CASE:

```sql
CASE ve.dish
  WHEN dv.dish1 THEN dv.dish1_price
  WHEN dv.dish2 THEN dv.dish2_price
  WHEN dv.dish3 THEN dv.dish3_price
  WHEN dv.dish4 THEN dv.dish4_price
  ELSE NULL
END
```

Áp dụng ở **cả** `get_monthly_summary` và `get_monthly_detail` (đọc thêm `ve.cost`, `ve.dish`, `dv.dish1–4`, `dv.dishN_price`; `count` vẫn đếm trong Python như hiện tại).

## Chốt 15h (thứ 6) — đổi `_scheduled_friday_settle`

Thay logic cũ (áp 1 giá `set_day_actual_price` + 1 `cost_per_person`) bằng **snapshot theo người**:

- Guard như cũ: chỉ T6; bỏ qua nếu không có vote hợp lệ (`status not in (open,closed)`) hoặc không ai vote.
- `count = len(voters)`, `ship = daily_votes.ship_fee`.
- Với mỗi `vote_entries` ngày đó: `cost = (dish_price khớp món, nếu NULL → daily_votes.price) + round(ship / count)` → ghi `vote_entries.cost`.
- Im lặng (không gửi tin), như đã chốt trước đó.
- Hàm DB mới: `snapshot_day_costs(date)` — đọc entries + giá món, tính, UPDATE `vote_entries.cost`. Trả số người đã chốt (để log).

## Web — nhập giá theo món (tab "Tuần này")

- Mỗi ngày: 4 dòng `Món N [tên] [giá]` (thêm input giá cạnh mỗi ô tên món). **Bỏ** ô "Giá/s" đơn giá chung. **Giữ** ô "Ship".
- Endpoint `/save-menu-items`: nhận thêm `price1..price4` + giữ `ship_fee`; **bỏ** param `price` (đơn giá).
  - Ghi tên món (như cũ) + `dishN_price` vào `daily_votes` (hàm mới `set_day_dish_prices(date, [p1..p4])`).
  - Ghi `ship_fee` thẳng vào `daily_votes.ship_fee` (hàm `set_day_ship(date, ship)`); rỗng/không số → giữ nguyên (không đổi).
  - Ngừng gọi `set_day_price` (override đơn giá).
- Prefill: `get_week_data` trả thêm `dish1_price..dish4_price` để điền lại ô giá. (Tên món vẫn lấy từ `week_menu`.)
- `_parse_int` giữ nguyên (rỗng/không số → None).

## Dọn phần đơn giá chung (revert một phần)

- `_scheduled_open_vote`: **bỏ** đoạn đọc `price_override`/`ship_fee_override` (Task 5). Quay lại dùng giá/ship toàn cục khi tạo vote (admin nhập giá món + ship sau, lúc 12–13h).
- `set_day_price`, `set_day_actual_price`: bỏ dùng (thay bằng `set_day_dish_prices` + `set_day_ship` + `snapshot_day_costs`). Có thể xoá hàm nếu không còn ai gọi.
- Cột `price_override`/`ship_fee_override`: để lại, không dùng.

## Edge cases

- Món không nhập giá (`dishN_price` NULL) → fallback `daily_votes.price` (giá cơm toàn cục). Admin nên nhập giá cho mọi món bún đậu.
- Ngày dùng ✅/❌ (không có món) → `ve.dish` NULL → fallback `daily_votes.price` (1 giá chung như cũ).
- Ngày cơm thường (không nhập giá món) → mọi `dishN_price` NULL → fallback `daily_votes.price` = giá cơm. **Hành vi không đổi.**
- `ship = 0` → mỗi người = đúng giá món.
- Sau 15h sửa giá món → `ve.cost` đã set, summary đọc snapshot → **không đổi**.
- Admin nhập giá/ship lúc 12–13h (sau 8h30 tạo vote) → ghi thẳng `daily_votes`, không bị tạo vote ghi đè.

## File sẽ sửa

- `database.py` — migration `dish1_price..dish4_price` + `vote_entries.cost`; thêm `set_day_dish_prices`, `set_day_ship`, `snapshot_day_costs`; sửa `get_monthly_summary` + `get_monthly_detail` (công thức theo món + đọc `ve.cost`); `get_week_data` trả thêm `dishN_price`; bỏ dùng `set_day_price`/`set_day_actual_price`.
- `scheduler.py` — `_scheduled_friday_settle` đổi sang snapshot per-person; `_scheduled_open_vote` bỏ đọc override.
- `web/app.py` — `/save-menu-items` nhận `price1..price4` + `ship_fee`, bỏ `price`; gọi `set_day_dish_prices` + `set_day_ship`.
- `web/templates/index.html` — thêm ô giá mỗi món, bỏ ô "Giá/s", giữ ô "Ship".
- Tests: `test_database.py` (công thức theo món, snapshot, get_week_data), `test_scheduler.py` (settle snapshot), `test_web.py` (lưu giá món + ship).

## Kiểm thử

- 2 người chọn 2 món giá khác nhau (40k, 50k) + ship 10k/2 → mỗi người 45k/55k (live, trước chốt).
- Sau `snapshot_day_costs` → `ve.cost` = 45k/55k; sửa `dish_price` → summary vẫn 45k/55k (khoá).
- Món không giá → fallback `daily.price`.
- Ngày cơm thường (không giá món) → mỗi người = `daily.price` + ship/count (không đổi).
- `_scheduled_friday_settle` T6: snapshot đúng; non-T6: no-op (`ve.cost` vẫn NULL).
- Web: lưu `price1..price4` + ship → `dishN_price` + `ship_fee` đúng; không còn ghi `price_override`.
- `get_week_data` trả `dishN_price` để prefill.

## Ngoài phạm vi (YAGNI)

- Không giá riêng theo từng người (đã chọn: giá theo món).
- Không xoá cột `price_override`/`ship_fee_override` (để lại dormant).
- Không đổi luồng vote 8h30 / picker 10h30 / wording (giữ nguyên Task 1–3).
- Không đổi ngày cơm thường.
