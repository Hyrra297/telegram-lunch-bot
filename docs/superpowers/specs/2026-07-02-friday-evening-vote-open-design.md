# Thiết kế: Mở vote thứ 6 từ 20h tối thứ 5

**Ngày:** 2026-07-02
**Trạng thái:** Đã duyệt hướng, chờ review spec

## Vấn đề

Hiện thứ 6 (bún đậu) chỉ tạo vote lúc **08:30 sáng thứ 6** (tối thứ 5 không tạo, không digest). Vì vậy 08:30 thứ 6 là lúc *tạo* vote chứ không *nhắc* như các ngày khác, và không có real-time notify cho admin trong tối thứ 5.

Nhờ feature carryover vừa xong (`get_friday_source` — menu thứ 6 biết trước từ tối thứ 5), giờ có thể mở vote thứ 6 sớm từ tối hôm trước.

## Mục tiêu (phạm vi đã chốt với user)

- **Vote thứ 6 mở lúc 20:00 tối thứ 5** (muộn hơn mốc 18:30 của T2–T5).
- **KHÔNG gửi digest** admin cho thứ 6.
- **Real-time notify** thứ 6 hoạt động từ **20:00 thứ 5** (ping admin từng người đặt/đổi/huỷ).
- **08:30 thứ 6**: nhắc số người đặt như các ngày khác (không còn là lúc tạo vote).
- **Giữ nguyên** khâu chốt bún đậu: 10:30 chỉ 1 picker (không trả hộp, không tính tiền), 15:00 `friday_settle` snapshot, giá theo món.
- **T2–T5 giữ nguyên hoàn toàn** (18:30 mở, 20:00 digest, sun–wed).

## Phi mục tiêu (YAGNI)

- Không đổi lịch/logic T2–T5.
- Không đổi công thức tiền, snapshot, per-dish pricing.
- Không thêm digest cho thứ 6.
- Không đưa giờ 20:00-thứ-6 thành biến config (hardcode; có thể tách config sau nếu cần).

## Kiến trúc / Thay đổi

Chỉ chạm `scheduler.py` + `tests/test_scheduler.py` + `CLAUDE.md`.

### 1. Thêm job `open_vote_friday` (`scheduler.py::build_scheduler`)

```python
# 20:00 thứ 5: mở vote bún đậu cho thứ 6 (offset=1). Muộn hơn T2-T5 (18:30), KHÔNG digest.
scheduler.add_job(
    _scheduled_open_vote,
    trigger=CronTrigger(hour=20, minute=0, day_of_week="thu", timezone=tz),
    args=[app, 1], id="open_vote_friday", replace_existing=True, misfire_grace_time=300,
)
```

Tái dùng nguyên `_scheduled_open_vote(app, day_offset=1)`:
- `target = _target_date(1)` = thứ 6.
- `_is_friday(target)` → `apply_friday_template(target)` (carryover từ thứ 6 gần nhất, đã có từ feature trước) → set món/giá/ship/ảnh.
- Guard "phải có ảnh" pass (menu_image = `fri.jpg` từ carryover) → gửi ảnh + poll bún đậu.
- Wording lấy từ `_open_vote_wording(1, target)` (xem mục 2).

### 2. `_open_vote_wording` tôn trọng `day_offset` cho thứ 6

Hiện nhánh thứ 6 luôn trả "hôm nay". Sửa để khi tạo tối hôm trước (offset≥1) thì dùng "ngày mai":

```python
def _open_vote_wording(day_offset: int, date_str: str | None = None) -> dict:
    if date_str and _is_friday(date_str):
        if day_offset >= 1:
            return {
                "caption": "🍜 Thực đơn bún đậu ngày mai",
                "poll_question": "🥢 Ngày mai ăn bún đậu gì?",
                "day_label": "ngày mai",
            }
        return {
            "caption": "🍜 Thực đơn bún đậu hôm nay",
            "poll_question": "🥢 Hôm nay ăn bún đậu gì?",
            "day_label": "hôm nay",
        }
    if day_offset >= 1:
        return {"caption": "🍽️ Thực đơn ngày mai", "poll_question": "🍱 Ngày mai ăn gì?", "day_label": "ngày mai"}
    return {"caption": "🍽️ Thực đơn hôm nay", "poll_question": "🍱 Hôm nay ăn gì?", "day_label": "hôm nay"}
```

### KHÔNG đổi

- `open_vote_evening` (18:30, `sun,mon,tue,wed`) và `admin_digest` (20:00, `sun,mon,tue,wed`) → T2–T5 nguyên vẹn, thứ 6 không digest.
- `_scheduled_open_vote` (thân hàm) — đã xử lý thứ 6 qua `_is_friday` + carryover.
- `_scheduled_morning` (08:30 mon–fri) — thứ 6: vote đã `open` (tạo 20h thứ 5) → chạy `_send_vote_reminder` (nhắc như mọi ngày); nếu tối lỡ → tạo bù (offset=0, wording "hôm nay").
- `_scheduled_announce_roles` (10:30) — thứ 6 chỉ picker (giữ nguyên).
- `_scheduled_friday_settle` (15:00) — giữ nguyên.
- `handlers/vote.py::_past_evening_digest` — generic (mốc = `date − 1 ngày` lúc `ADMIN_DIGEST_TIME` = 20:00). Với thứ 6 → thứ 5 20:00 → real-time notify tự bật đúng từ 20:00 thứ 5. Không cần sửa.

## Luồng dữ liệu (thứ 6)

| Mốc | Hành động |
|---|---|
| Thứ 5 20:00 | `open_vote_friday` → tạo poll bún đậu cho thứ 6 (carryover menu), wording "ngày mai" |
| Thứ 5 20:00 → thứ 6 10:30 | real-time notify admin mọi thay đổi (qua `_past_evening_digest`) |
| Thứ 6 08:30 | `morning` → vote `open` → nhắc số người đặt |
| Thứ 6 10:30 | `announce_roles` → đóng vote, chọn 1 người đi lấy bún đậu |
| Thứ 6 15:00 | `friday_settle` → snapshot tiền (giá món + ship/số người) |

## Xử lý lỗi / biên

- **Job 20h thứ 5 lỡ** (misfire > grace 300s): 08:30 thứ 6 `morning` tạo bù (offset=0 → wording "hôm nay"). Lưới an toàn giữ nguyên.
- **Row thứ 6 cũ status `none`** (vd ảnh lạc): `_scheduled_open_vote` chỉ skip khi status ∈ (`open`,`closed`) → `none` vẫn tạo bình thường.
- **Không có thứ 6 trước + không template**: `apply_friday_template` trả False → không có món → guard "cần ảnh" → notify admin, không tạo (hiếm; đã có sẵn hành vi này).
- **Trùng giờ 20:00**: `admin_digest` không chạy thứ 5 (`sun,mon,tue,wed`) nên không đụng job `open_vote_friday` thứ 5.

## Kiểm thử

Thêm (`tests/test_scheduler.py`):
- `test_friday_open_job`: job `open_vote_friday` tồn tại; trigger `day_of_week='thu'`, `hour='20'`, `minute='0'`; `args[1] == 1`.
- `test_job_ids`: cập nhật set kỳ vọng thêm `open_vote_friday`.
- `test_friday_evening_wording_ngay_mai`: `_open_vote_wording(1, "2026-01-02")` → `day_label="ngày mai"`, caption/poll bún đậu "ngày mai".

Giữ nguyên (không đổi): `test_evening_job_trigger`, `test_digest_job_excludes_thursday`, `test_morning_job_trigger`, `test_friday_uses_bun_dau_wording` (offset=0 vẫn "hôm nay"), `test_evening_job_passes_day_offset_one`.

Cập nhật `CLAUDE.md`: bảng lịch scheduler (thêm dòng 20:00 thứ 5 mở vote thứ 6; ghi chú thứ 6 không digest, real-time notify từ 20h thứ 5, 08:30 thứ 6 nhắc như mọi ngày).

## Files thay đổi

- `scheduler.py` — thêm job `open_vote_friday`; sửa `_open_vote_wording` (thứ 6 tôn trọng offset).
- `tests/test_scheduler.py` — thêm 2 test + cập nhật `test_job_ids`.
- `CLAUDE.md` — cập nhật bảng lịch + ghi chú thứ 6.
