# Mở vote thứ 6 từ 20h tối thứ 5 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thứ 6 (bún đậu) mở vote lúc 20:00 tối thứ 5 (carryover menu), không digest; 08:30 thứ 6 chỉ nhắc như mọi ngày. T2–T5 giữ nguyên.

**Architecture:** Thêm một job scheduler riêng `open_vote_friday` chạy thứ 5 20:00 gọi `_scheduled_open_vote(app, 1)` (đã xử lý carryover thứ 6). Sửa `_open_vote_wording` để wording thứ 6 tôn trọng `day_offset` ("ngày mai" khi tạo tối hôm trước). Không đụng các job/logic khác.

**Tech Stack:** Python 3.8, APScheduler (CronTrigger), pytest.

## Global Constraints

- Timezone Asia/Ho_Chi_Minh; ngày ISO `YYYY-MM-DD`; `_is_friday` = `weekday()==4`.
- Chạy test từ `d:/telegram-lunch-bot`: `python -m pytest <path> -v`.
- KHÔNG đổi: `open_vote_evening` (18:30, `sun,mon,tue,wed`), `admin_digest` (20:00, `sun,mon,tue,wed`), `_scheduled_open_vote` thân hàm, `_scheduled_morning`, `_scheduled_announce_roles`, `_scheduled_friday_settle`, `handlers/vote.py::_past_evening_digest`.
- Thứ 6: KHÔNG digest; real-time notify tự bật từ 20:00 thứ 5 qua `_past_evening_digest` generic (mốc = ngày−1 lúc `ADMIN_DIGEST_TIME`=20:00).
- Job mới id = `open_vote_friday`, giờ hardcode 20:00, `day_of_week="thu"`, `args=[app, 1]`, `misfire_grace_time=300`.
- `_open_vote_wording(day_offset, date_str=None)` giữ chữ ký; nhánh thứ 6 với offset≥1 → wording "ngày mai".

---

### Task 1: `_open_vote_wording` — thứ 6 tôn trọng `day_offset`

**Files:**
- Modify: `scheduler.py` (hàm `_open_vote_wording`, nhánh `if date_str and _is_friday(date_str):`)
- Test: `tests/test_scheduler.py` (class `TestFridayWording`)

**Interfaces:**
- Produces: `_open_vote_wording(day_offset: int, date_str: str | None = None) -> dict` — với thứ 6 + `day_offset>=1` trả `{caption, poll_question, day_label}` dùng "ngày mai".

- [ ] **Step 1: Viết failing test**

Thêm vào class `TestFridayWording` trong `tests/test_scheduler.py`:
```python
    def test_friday_evening_uses_ngay_mai(self):
        from scheduler import _open_vote_wording
        w = _open_vote_wording(1, "2026-01-02")  # thứ 6, tạo tối hôm trước
        assert w["day_label"] == "ngày mai"
        assert w["caption"] == "🍜 Thực đơn bún đậu ngày mai"
        assert w["poll_question"] == "🥢 Ngày mai ăn bún đậu gì?"
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `python -m pytest "tests/test_scheduler.py::TestFridayWording::test_friday_evening_uses_ngay_mai" -v`
Expected: FAIL — hiện nhánh thứ 6 luôn trả "hôm nay" nên `day_label == "hôm nay"` ≠ "ngày mai".

- [ ] **Step 3: Sửa nhánh thứ 6**

Trong `scheduler.py::_open_vote_wording`, thay khối:
```python
    if date_str and _is_friday(date_str):
        return {
            "caption": "🍜 Thực đơn bún đậu hôm nay",
            "poll_question": "🥢 Hôm nay ăn bún đậu gì?",
            "day_label": "hôm nay",
        }
```
bằng:
```python
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
```

- [ ] **Step 4: Chạy test — kỳ vọng PASS (mới + cũ)**

Run: `python -m pytest "tests/test_scheduler.py::TestFridayWording" -v`
Expected: PASS toàn bộ. `test_friday_uses_bun_dau_wording` (offset=0 → "hôm nay") vẫn xanh vì offset=0 vào nhánh dưới.

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: wording bún đậu thứ 6 tôn trọng day_offset (ngày mai khi tạo tối trước)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Thêm job `open_vote_friday` (thứ 5 20:00)

**Files:**
- Modify: `scheduler.py` (hàm `build_scheduler`, thêm job trước `return scheduler`)
- Test: `tests/test_scheduler.py` (class `TestBuildScheduler`: thêm `test_friday_open_job`, cập nhật `test_job_ids`)

**Interfaces:**
- Consumes: `_scheduled_open_vote(app, day_offset=1)` (đã có; tự xử lý carryover thứ 6), `_open_vote_wording` (Task 1).
- Produces: scheduler có thêm job id `open_vote_friday`, trigger thứ 5 20:00, `args=[app, 1]`.

- [ ] **Step 1: Viết failing test + cập nhật test_job_ids**

Trong `tests/test_scheduler.py`, cập nhật assert trong `test_job_ids` (class `TestBuildScheduler`):
```python
        assert ids == {"open_vote_evening", "open_vote_friday", "morning", "announce_roles", "monthly_summary", "admin_digest", "friday_settle"}
```
Và thêm test mới vào cùng class:
```python
    def test_friday_open_job(self):
        from scheduler import build_scheduler
        sched = build_scheduler(object())
        jobs = {j.id: j for j in sched.get_jobs()}
        assert "open_vote_friday" in jobs
        trig = str(jobs["open_vote_friday"].trigger)
        assert "hour='20'" in trig
        assert "minute='0'" in trig
        assert "day_of_week='thu'" in trig
        assert jobs["open_vote_friday"].args[1] == 1
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `python -m pytest "tests/test_scheduler.py::TestBuildScheduler" -v`
Expected: FAIL — `test_friday_open_job` (job chưa tồn tại) và `test_job_ids` (thiếu `open_vote_friday` trong set thực tế).

- [ ] **Step 3: Thêm job vào `build_scheduler`**

Trong `scheduler.py::build_scheduler`, ngay TRƯỚC `return scheduler` (sau job `friday_settle`), thêm:
```python
    # 20:00 thứ 5: mở vote bún đậu cho thứ 6 (offset=1). Muộn hơn T2-T5 (18:30), KHÔNG digest.
    scheduler.add_job(
        _scheduled_open_vote,
        trigger=CronTrigger(hour=20, minute=0, day_of_week="thu", timezone=tz),
        args=[app, 1], id="open_vote_friday", replace_existing=True, misfire_grace_time=300,
    )
```

- [ ] **Step 4: Chạy test — kỳ vọng PASS**

Run: `python -m pytest "tests/test_scheduler.py::TestBuildScheduler" -v`
Expected: PASS toàn bộ (gồm `test_friday_open_job`, `test_job_ids`, và các test cron cũ `test_evening_job_trigger`/`test_digest_job_excludes_thursday` không đổi).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: job open_vote_friday — mở vote bún đậu thứ 6 lúc 20h thứ 5

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Cập nhật CLAUDE.md + verify toàn bộ

**Files:**
- Modify: `CLAUDE.md` (bảng "Lịch tự động (scheduler)" + đoạn ghi chú ngay dưới bảng)

- [ ] **Step 1: Cập nhật bảng lịch trong CLAUDE.md**

Mở `CLAUDE.md`, tìm bảng dưới heading `## Lịch tự động (scheduler)`. Thêm MỘT dòng vào bảng (ngay sau dòng `18:30 | CN–T4`):
```
| 20:00 | T5 | **`open_vote_friday`**: tạo vote bún đậu cho **thứ 6** (offset=1, carryover menu từ thứ 6 trước), wording "ngày mai". Thứ 6 KHÔNG digest |
```
Và sửa dòng `18:30 | CN–T4` để bỏ ghi chú "T5 không tạo vote cho T6 — T6 do job 08:30 đảm nhận" (giờ T6 do job 20:00 T5 tạo). Đồng thời sửa mô tả dòng `08:30 | T2–T6`: thứ 6 giờ vote đã có từ 20:00 T5 → 08:30 **nhắc** như mọi ngày (job 08:30 vẫn là lưới an toàn nếu job 20:00 lỡ).

- [ ] **Step 2: Cập nhật đoạn văn ghi chú dưới bảng**

Ngay dưới bảng có đoạn bắt đầu "Mọi ngày T2–T5 đều tạo vote từ 18:30 tối hôm trước...". Sửa để phản ánh: **thứ 6 mở vote 20:00 tối thứ 5** (muộn hơn T2–T5, không digest), real-time notify thứ 6 hoạt động **từ 20:00 thứ 5** (không phải 08:30). Giữ nguyên phần mô tả `_past_evening_digest`. Cụ thể thay câu "Riêng **thứ 6 là ngày bún đậu** — vote tạo lúc 08:30 sáng T6 (không tạo tối T5, không digest tối T5)." bằng:
```
Riêng **thứ 6 là ngày bún đậu** — vote tạo lúc **20:00 tối thứ 5** (job `open_vote_friday`, carryover menu từ thứ 6 trước), KHÔNG digest. Job 08:30 thứ 6 khi đó chỉ **nhắc** số người đặt như các ngày khác (và là lưới an toàn tạo bù nếu job 20:00 lỡ).
```
Và sửa câu "T6: real-time notify hoạt động từ 08:30–10:30 (sau khi vote được tạo)." thành "T6: real-time notify hoạt động từ **20:00 thứ 5**–10:30 thứ 6 (sau khi vote được tạo 20:00 T5)."

- [ ] **Step 3: Chạy toàn bộ test suite**

Run: `python -m pytest -q`
Expected: PASS toàn bộ (baseline trước đó 160; không giảm).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: lịch thứ 6 — mở vote 20h thứ 5, không digest, 08:30 nhắc

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Vote thứ 6 mở 20:00 thứ 5 → Task 2 (job `open_vote_friday`). ✓
- Wording "ngày mai" khi tạo tối trước → Task 1. ✓
- Không digest thứ 6 → không thêm Thursday vào `admin_digest` (giữ nguyên). ✓
- Real-time notify từ 20h thứ 5 → tự động qua `_past_evening_digest` generic (không cần code). ✓
- 08:30 thứ 6 nhắc như mọi ngày → tự động qua `_scheduled_morning` khi vote đã open (không cần code). ✓
- Giữ nguyên T2–T5 + khâu chốt bún đậu → không task nào chạm. ✓
- Docs → Task 3. ✓

**Placeholder scan:** Không TBD/TODO; mọi step có code/command cụ thể. Task 3 (docs) mô tả rõ câu cần thay + nội dung mới. ✓

**Type consistency:** `_open_vote_wording(day_offset, date_str)` giữ chữ ký; job id `open_vote_friday` nhất quán giữa code + test_job_ids + test_friday_open_job; `args=[app, 1]` khớp `_scheduled_open_vote(app, day_offset=1)`; CronTrigger `hour=20, minute=0, day_of_week="thu"` khớp assert test (`hour='20'`, `minute='0'`, `day_of_week='thu'`). ✓
