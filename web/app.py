from __future__ import annotations
import hashlib
import hmac
import os
import time
import pytz
from collections import defaultdict
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
app.mount("/static", StaticFiles(directory="static", follow_symlink=True), name="static")
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


def _safe_redirect(url: str) -> str:
    """Only allow relative redirects — prevents open redirect attacks."""
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return "/"


# ── Rate limiting ──────────────────────────────────────────────────────────────

_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 phút


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
    return len(_login_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.time())


# ── Time helpers ──────────────────────────────────────────────────────────────

def _current_month() -> str:
    return datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m")


def _current_week_dates() -> list:
    today = datetime.now(pytz.timezone(config.TIMEZONE)).date()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


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
    week_dates = _current_week_dates()
    week_days = await db.get_week_data(week_dates)
    # Load dishes for each day of the week
    week_menu = {}
    for d in week_dates:
        items = await db.get_menu_items(d)
        week_menu[d] = items + [""] * (4 - len(items))  # pad to 4 slots
    detail = await db.get_monthly_detail(month, max_date=max_date)

    paid_ids = await db.get_paid_user_ids(month)

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
        "week_menu": week_menu,
        "detail": detail,
        "paid_count": paid_count,
        "is_admin": _is_admin(request),
    })


@app.post("/login")
async def login(request: Request, password: str = Form(...), next: str = Form("/")):
    redirect_to = _safe_redirect(next)
    ip = request.client.host

    if _is_rate_limited(ip):
        return RedirectResponse(f"{redirect_to}?login_error=2", status_code=303)

    if hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
        _login_attempts.pop(ip, None)  # reset khi đăng nhập thành công
        response = RedirectResponse(redirect_to, status_code=303)
        response.set_cookie(
            COOKIE_NAME, _admin_token(),
            httponly=True, samesite="lax",
            max_age=60 * 60 * 24 * 30,  # 30 days
            path="/",
        )
        return response

    _record_failed_attempt(ip)
    return RedirectResponse(f"{redirect_to}?login_error=1", status_code=303)


@app.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.post("/save-menu-items")
async def save_menu_items_endpoint(
    request: Request,
    date: str = Form(...),
    dish1: str = Form(""),
    dish2: str = Form(""),
    dish3: str = Form(""),
    dish4: str = Form(""),
):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Không có quyền"}, status_code=403)
    dishes = [d.strip() for d in [dish1, dish2, dish3, dish4] if d.strip()]
    await db.save_menu_items(date, dishes)
    return JSONResponse({"ok": True})


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

    # Save by weekday name so next week's upload replaces the old one
    from datetime import datetime as _dt
    weekday = _dt.strptime(date, "%Y-%m-%d").strftime("%a").lower()  # mon, tue, ...
    filename = f"{weekday}{ext}"
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
