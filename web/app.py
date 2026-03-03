from __future__ import annotations
import hashlib
import hmac
import os
import pytz
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import database as db

MENU_DIR = Path("static/menus")
MENU_DIR.mkdir(parents=True, exist_ok=True)
QR_DIR = Path("static/qr")
QR_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
COOKIE_NAME = "admin_token"

app = FastAPI(title="Lunch Bot Dashboard")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="web/templates")


@app.on_event("startup")
async def startup():
    await db.init_db()


def _fmt_vnd(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


templates.env.filters["format_vnd"] = _fmt_vnd


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _admin_token() -> str:
    """Fixed token derived from SECRET_KEY + ADMIN_PASSWORD."""
    return hashlib.sha256(
        (config.SECRET_KEY + ":" + config.ADMIN_PASSWORD).encode()
    ).hexdigest()


def _is_admin(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME, "")
    expected = _admin_token()
    return bool(token) and hmac.compare_digest(token, expected)


# ── Time helpers ──────────────────────────────────────────────────────────────

def _current_month() -> str:
    return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m")


def _current_week_dates() -> list:
    today = datetime.now(pytz.timezone(config.TIMEZONE)).date()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


# ── Sample data ───────────────────────────────────────────────────────────────

def _sample_detail(month: str) -> dict:
    """Hardcoded preview data shown when no real closed votes exist yet."""
    from datetime import date as dt_date
    WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    year, m = map(int, month.split("-"))

    # Pick Mon–Fri for the first 2 full weeks of the month
    import calendar
    first_day = dt_date(year, m, 1)
    # Align to first Monday on or after the 1st
    offset = (7 - first_day.weekday()) % 7
    monday1 = first_day + timedelta(days=offset)

    days = []
    price = 35000
    for week in range(2):
        for i in range(5):
            d = monday1 + timedelta(weeks=week, days=i)
            if d.month != m:
                continue
            days.append({
                "date": d.isoformat(),
                "date_short": f"{d.day:02d}/{d.month:02d}",
                "weekday": WEEKDAYS[d.weekday()],
                "price": price,
            })

    ship_fee = 20000
    names = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Minh Cường", "Phạm Thu Hà"]
    # Deterministic vote pattern per member (1 = đặt, 0 = không đặt)
    patterns = [
        [1, 1, 0, 1, 1,  1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1,  0, 1, 1, 0, 1],
        [0, 1, 1, 1, 0,  1, 1, 0, 1, 1],
        [1, 1, 1, 0, 1,  1, 1, 1, 1, 0],
    ]
    # Số người đặt mỗi ngày để chia ship
    day_counts = [
        sum(1 for p in patterns if i < len(p) and p[i])
        for i in range(len(days))
    ]
    members = []
    for idx, name in enumerate(names):
        pat = patterns[idx % len(patterns)]
        votes = {}
        for i in range(len(days)):
            if i < len(pat) and pat[i]:
                count = day_counts[i] or 1
                votes[days[i]["date"]] = price + round(ship_fee / count)
        members.append({"full_name": name, "votes": votes, "total": sum(votes.values())})

    return {"days": days, "members": members}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, month: str = "", tab: str = "week"):
    if not month:
        month = _current_month()

    # Only include today's data after 12:00 noon (local time)
    now_local = datetime.now(pytz.timezone(config.TIMEZONE))
    if now_local.hour >= 12:
        max_date = now_local.date().isoformat()
    else:
        max_date = (now_local.date() - timedelta(days=1)).isoformat()

    summary = await db.get_monthly_summary(month, max_date=max_date)
    history = await db.get_daily_history(month)
    months = await db.get_available_months()
    week_days = await db.get_week_data(_current_week_dates())
    detail = await db.get_monthly_detail(month, max_date=max_date)

    is_sample = not detail["members"]
    paid_ids = await db.get_paid_user_ids(month)
    if is_sample:
        detail = _sample_detail(month)

    # Attach paid status to each member
    for member in detail["members"]:
        member["paid"] = member.get("user_id") in paid_ids

    total_amount = sum(member["total"] for member in detail["members"])
    paid_count = sum(1 for m in detail["members"] if m["paid"])

    year, m = month.split("-")
    month_label = f"Tháng {int(m)}/{year}"

    today = datetime.now(pytz.timezone(config.TIMEZONE)).date()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    week_label = f"{monday.day}/{monday.month} – {friday.day}/{friday.month}/{friday.year}"

    def _find_qr(name: str):
        for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            if (QR_DIR / f"{name}{ext}").exists():
                return f"/static/qr/{name}{ext}"
        return None

    return templates.TemplateResponse("index.html", {
        "request": request,
        "tab": tab,
        "month": month,
        "month_label": month_label,
        "week_label": week_label,
        "summary": summary,
        "history": history,
        "months": months,
        "week_days": week_days,
        "total_amount": total_amount,
        "qr_zalopay": _find_qr("zalopay"),
        "qr_bank": _find_qr("bank"),
        "detail": detail,
        "is_sample": is_sample,
        "paid_count": paid_count,
        "is_admin": _is_admin(request),
    })


@app.post("/login")
async def login(request: Request, password: str = Form(...), next: str = Form("/")):
    if password == config.ADMIN_PASSWORD:
        response = RedirectResponse(next, status_code=303)
        response.set_cookie(
            COOKIE_NAME, _admin_token(),
            httponly=True, samesite="lax",
            max_age=60 * 60 * 24 * 30,  # 30 days
            path="/",
        )
        return response
    # Wrong password – redirect back with error flag
    return RedirectResponse(f"{next}&login_error=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    redirect_to = request.headers.get("referer", "/")
    response = RedirectResponse(redirect_to, status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.post("/upload-menu")
async def upload_menu(
    request: Request,
    date: str = Form(...),
    file: UploadFile = File(...),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return JSONResponse({"ok": False, "error": "Chỉ hỗ trợ JPG, PNG, WEBP, GIF"}, status_code=400)

    filename = f"{date}{ext}"
    dest = MENU_DIR / filename
    content = await file.read()
    dest.write_bytes(content)

    await db.set_menu_image(date, filename)
    return JSONResponse({"ok": True, "filename": filename, "url": f"/static/menus/{filename}"})


@app.post("/upload-qr")
async def upload_qr(
    request: Request,
    type: str = Form(...),
    file: UploadFile = File(...),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)
    if type not in ("zalopay", "bank"):
        return JSONResponse({"ok": False, "error": "Loại QR không hợp lệ"}, status_code=400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return JSONResponse({"ok": False, "error": "Chỉ hỗ trợ JPG, PNG, WEBP, GIF"}, status_code=400)

    # Remove old files for this type
    for old_ext in ALLOWED_EXT:
        old = QR_DIR / f"{type}{old_ext}"
        if old.exists():
            old.unlink()

    dest = QR_DIR / f"{type}{ext}"
    dest.write_bytes(await file.read())
    return JSONResponse({"ok": True, "url": f"/static/qr/{type}{ext}"})


@app.post("/toggle-paid")
async def toggle_paid_endpoint(
    request: Request,
    year_month: str = Form(...),
    user_id: int = Form(...),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)
    paid = await db.toggle_monthly_paid(year_month, user_id)
    return JSONResponse({"ok": True, "paid": paid})


@app.get("/health")
async def health():
    return {"status": "ok"}
