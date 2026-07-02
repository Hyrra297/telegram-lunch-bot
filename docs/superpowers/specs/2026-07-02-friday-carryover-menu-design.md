# Thiết kế: Thứ 6 tự kế thừa menu từ thứ 6 tuần trước

**Ngày:** 2026-07-02
**Trạng thái:** Đã duyệt hướng, chờ review spec

## Vấn đề

Trên web dashboard tab "Tuần này", cột **Thứ 6 (bún đậu)** của tuần đang xem hiện **trống** (không món / không giá / không ảnh) cho tới tận sáng thứ 6.

### Nguyên nhân gốc (đã điều tra + xác nhận trên prod)

- Menu mỗi ngày lưu **theo từng ngày** trong `daily_votes`. Tab "Tuần này" gọi `get_week_data` → đọc thẳng `daily_votes`.
- Thứ 6 sắp tới **chưa có row** (hoặc có row nhưng chưa có món) vì row chỉ được "materialize" lúc **08:30 sáng thứ 6** khi scheduler chạy `apply_friday_template`.
- Tầng web **không hề biết** đến nguồn menu bún đậu → thứ 6 sắp tới luôn trống trên web dù cơ chế template ở bot vẫn chạy đúng.

Bằng chứng prod (query ngày 2026-07-02):
- `settings.friday_template` đã cấu hình đúng: dishes bún đậu, prices `[35000,40000,45000,45000]`, ship `20000`, image `fri.jpg`.
- Thứ 6 `2026-06-26` (tuần trước): `closed`, đã áp bún đậu (prices đủ, img `fri.jpg`) → **bot chạy đúng**.
- Thứ 6 `2026-07-03` (sắp tới): `status=none`, dishes toàn `None`, img lạc `fri.png` → chưa áp (đúng vì chưa tới 08:30).

→ Bot đúng; **chỉ web thiếu preview**. Đồng thời người dùng muốn nguồn menu thứ 6 là **"copy từ thứ 6 gần nhất"** thay vì một template tĩnh trong DB, để khi sửa menu một tuần thì tuần sau tự kế thừa.

## Mục tiêu

1. Thứ 6 của tuần đang xem **tự kế thừa nguyên menu** (món + giá từng món + ship + ảnh) của **thứ 6 gần nhất trước đó** có món.
2. Áp dụng **cả web (preview) lẫn bot (poll 08:30)** — dùng chung một nguồn để không lệch nhau.
3. `friday_template` chỉ còn là **fallback** khi chưa từng có thứ 6 nào có món.
4. Không đụng: tính tiền, snapshot 15h (`friday_settle`), real-time notify, luồng T2–T5, override thủ công của admin.

## Phi mục tiêu (YAGNI)

- Không thêm UI sửa `friday_template` trên web.
- Không carry-over cho T2–T5 (người dùng tự nhập như hiện tại).
- Không đổi công thức giá / snapshot.

## Kiến trúc

### 1. `database.py` — nguồn menu thứ 6 duy nhất

**`async def get_friday_source(date: str) -> dict | None`**

Trả về menu bún đậu để dùng cho `date` (giả định `date` là thứ 6; caller đảm bảo):

```
dict {
  "dishes":     list[str],        # tên món (đã lọc rỗng)
  "prices":     list[int|None],   # giá từng món, khớp thứ tự dishes
  "ship_fee":   int | None,
  "menu_image": str | None,
}  hoặc None
```

Thuật toán:
1. Nhìn lùi các thứ 6 trước `date`: `cand = date − 7*k` với `k = 1..8`.
2. Với mỗi `cand`, đọc `daily_votes`; nếu có `dish1` (tức có món) → build dict từ row đó và trả về ngay.
   - **Ghép cặp theo slot rồi lọc:** tạo các cặp `(dishN, dishN_price)` cho N=1..4, **bỏ cặp có `dishN` rỗng**, rồi tách thành `dishes` + `prices` đã căn khớp thứ tự (cùng cách web endpoint `save-menu-items` ghép). Tránh lệch giá khi có slot món trống ở giữa.
   - `ship_fee`, `menu_image` lấy trực tiếp từ row.
3. Nếu hết vòng lặp mà không thấy → parse `settings.friday_template` (JSON) làm fallback; trả dict hoặc `None` nếu thiếu/hỏng.

Lưu ý fallback template: `dishes`/`prices` trong JSON template vốn đã căn khớp sẵn (không có slot rỗng) → trả nguyên.

Ghi chú:
- Dùng bước lùi 7 ngày để luôn trúng đúng thứ 6 (không cần hàm weekday trong SQL).
- Cửa sổ 8 tuần đủ để vượt qua vài thứ 6 bị `/skip_today` (không có món).

**`async def get_friday_template() -> dict | None`** (helper phụ, tùy chọn)

Tách phần parse `settings.friday_template` để `get_friday_source` (fallback) và `apply_friday_template` dùng chung, tránh lặp code.

**`apply_friday_template(date)`** — giữ tên (scheduler đang gọi), đổi phần thân:
1. Nếu `get_menu_items(date)` không rỗng → `return False` (admin override thắng — **giữ nguyên**).
2. `src = await get_friday_source(date)`; nếu `None` hoặc `src["dishes"]` rỗng → `return False`.
3. Áp: `save_menu_items(date, src["dishes"])`, `set_day_dish_prices(date, src["prices"])`,
   `set_day_ship(date, src["ship_fee"])` **chỉ khi** `ship_fee is not None`,
   `set_menu_image(date, src["menu_image"])` **chỉ khi** `menu_image` truthy.
4. `return True`.

(Docstring cập nhật: "áp menu bún đậu cho thứ 6 — ưu tiên copy thứ 6 gần nhất có món, fallback `friday_template`; chỉ áp khi ngày chưa có món.")

### 2. `web/app.py` — preview trên tab "Tuần này"

Sau khi dựng `week_days` + `week_menu` trong route `index`, gọi một helper:

**`async def _apply_friday_preview(week_days, week_menu) -> None`** (mutate tại chỗ)

Với mỗi `day` trong `week_days`:
- Nếu `day["weekday"] == "Thứ 6"` **và** menu hiện tại rỗng (`not any(week_menu[day["date"]])`):
  - `src = await db.get_friday_source(day["date"])`
  - Nếu `src` và `src["dishes"]`:
    - `week_menu[day["date"]] = (src["dishes"] + [""]*4)[:4]`
    - `day["dish1_price".."dish4_price"] = (src["prices"] + [None]*4)[:4]`
    - `day["ship_fee"] = src["ship_fee"]`
    - `day["menu_image"] = src["menu_image"]`
    - `day["is_template_preview"] = True`

Ghi chú:
- Chỉ **đọc + overlay để hiển thị**, KHÔNG ghi DB.
- Điều kiện "chưa có món" bảo toàn override admin: nếu admin nhập món khác cho thứ 6 → có món → preview tắt.

### 3. `web/templates/index.html`

Trong vòng lặp `week_days`, khi `day.is_template_preview` → hiện nhãn nhỏ (vd `🍜 Bún đậu (theo tuần trước)`) gần badge trạng thái, để admin hiểu đây là xem trước chưa chốt. Các ô form đã prefill sẵn giá trị (dishes/giá/ship/ảnh) nhờ overlay ở app.py.

## Luồng dữ liệu (prod, ví dụ 2026-07-03)

- **Web (trước 08:30):** 07-03 chưa có món → `_apply_friday_preview` → `get_friday_source(07-03)` → thấy 06-26 có bún đậu → overlay → web hiện bún đậu + giá 35/40/45/45 + `fri.jpg`.
- **Bot 08:30 (07-03):** `apply_friday_template(07-03)` → chưa có món → `get_friday_source` → 06-26 → áp món/giá/ship + `set_menu_image('fri.jpg')` (ghi đè `fri.png` lạc) → poll bún đậu.
- **Nhất quán:** web preview và poll dùng cùng `get_friday_source` → giống nhau.

## Xử lý lỗi / biên

- `get_friday_source` trả `None` (không thứ 6 trước + không template hợp lệ) → apply `return False`, web không overlay (hiện trống như cũ). Không vỡ.
- JSON template hỏng → coi như không có template (fallback `None`).
- Thứ 6 trước bị skip (không món) → vòng lặp bỏ qua, lùi tiếp.
- `date` không phải thứ 6 (không xảy ra từ caller hiện tại) → hàm vẫn chạy nhưng ý nghĩa "lùi 7 ngày" chỉ đúng khi date là thứ 6; được document rõ.

## Kiểm thử

Giữ nguyên (vẫn xanh vì test dùng thứ 6 đơn lẻ không có thứ 6 trước → fallback template):
- `TestFridayTemplate` (test_database.py), `TestFridayTemplateOpenVote` (test_scheduler.py).

Thêm mới (test_database.py):
- `get_friday_source` copy đúng thứ 6 gần nhất có món (dishes/prices/ship/image).
- Ưu tiên thứ 6 gần nhất **hơn** template (khi cả hai tồn tại).
- Bỏ qua thứ 6 bị skip (không món), lấy thứ 6 xa hơn.
- Fallback template khi không có thứ 6 trước.
- `apply_friday_template` copy nguyên từ thứ 6 trước (không phải template) khi thứ 6 trước có món.

Thêm mới (test_web.py hoặc test_database.py cho helper preview):
- `_apply_friday_preview` overlay đúng khi thứ 6 rỗng; không overlay khi thứ 6 đã có món.

Verify thủ công: chạy `uvicorn`, mở tab "Tuần này", xác nhận cột Thứ 6 hiện bún đậu + ảnh + giá.

## Files thay đổi

- `database.py` — thêm `get_friday_source` (+ tùy chọn `get_friday_template`); đổi thân `apply_friday_template`.
- `web/app.py` — thêm `_apply_friday_preview`, gọi trong route `index`.
- `web/templates/index.html` — nhãn preview khi `is_template_preview`.
- `tests/test_database.py` — thêm test carryover.
- `tests/test_web.py` — thêm test overlay preview (nếu phù hợp).
- `CLAUDE.md` — cập nhật mô tả cơ chế thứ 6 (copy tuần trước, template là fallback).
