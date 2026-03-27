import io
import json
import os
import zipfile
from datetime import datetime
from urllib.parse import quote

import httpx
import stripe
from fastapi import FastAPI, Request, UploadFile, File, Form, Header
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.converter import image_to_svg

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

MONTHLY_PRICE_ID = "price_1TEEGHDwkY6zitSbrBCUMkNL"
LIFETIME_PRICE_ID = "price_1TEEHNDwkY6zitSbqo6jN25S"
DOMAIN = "https://mhjin91-docker.onrender.com"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

PAID_USERS_FILE = "paid_users.json"


# =========================
# Paid user 관리
# =========================
def load_paid_users():
    if not os.path.exists(PAID_USERS_FILE):
        return {}
    try:
        with open(PAID_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_paid_users(data):
    with open(PAID_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_paid_user(email: str | None):
    if not email:
        return False

    paid_users = load_paid_users()
    user = paid_users.get(email.lower().strip())
    if not user:
        return False

    if user.get("plan") == "monthly":
        paid_at = datetime.fromisoformat(user["paid_at"])
        days = (datetime.utcnow() - paid_at).days
        if days > 30:
            return False

    return True


def add_paid_user(email: str, plan: str):
    paid_users = load_paid_users()
    paid_users[email.lower().strip()] = {
        "plan": plan,
        "paid_at": datetime.utcnow().isoformat()
    }
    save_paid_users(paid_users)


# =========================
# Supabase 로그인 확인
# =========================
async def get_supabase_user_email(access_token: str | None):
    if not access_token or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None

    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": SUPABASE_ANON_KEY,
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code != 200:
        return None

    data = res.json()
    return data.get("email")


# =========================
# usage (Supabase)
# =========================
async def get_usage(email: str):
    safe_email = quote(email)
    url = f"{SUPABASE_URL}/rest/v1/usage_limits?email=eq.{safe_email}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code >= 400:
        raise RuntimeError(f"Supabase get_usage failed: {res.status_code} - {res.text}")

    data = res.json()
    return data[0] if data else None


async def upsert_usage(email: str, count: int, today: str):
    url = f"{SUPABASE_URL}/rest/v1/usage_limits"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    payload = {
        "email": email,
        "count": count,
        "last_date": today,
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(url, headers=headers, json=payload)

    if res.status_code >= 400:
        raise RuntimeError(f"Supabase upsert_usage failed: {res.status_code} - {res.text}")


# =========================
# Home
# =========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "success_message": "Payment completed successfully! Your Pro access should now be active."
        },
    )


# =========================
# Convert
# =========================
@app.post("/convert", response_class=HTMLResponse)
async def convert_images(
    request: Request,
    files: list[UploadFile] = File(...),
    remove_whitespace: str = Form(None),
    access_token: str = Form(""),
):
    try:
        today = datetime.utcnow().date().isoformat()

        email = await get_supabase_user_email(access_token)
        if not email:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": "Login required 🔒"},
            )

        is_pro = is_paid_user(email)
        valid_files = [f for f in files if f.filename]

        if not valid_files:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": "No valid files uploaded."},
            )

        if not is_pro:
            usage = await get_usage(email)

            if not usage:
                current = 0
            else:
                current = 0 if usage.get("last_date") != today else int(usage.get("count", 0))

            if current + len(valid_files) > 5:
                return templates.TemplateResponse(
                    "index.html",
                    {"request": request, "error": "Free limit reached (5/day)"},
                )
        else:
            current = 0

        results = []
        converted = 0

        for file in valid_files:
            data = await file.read()
            if not data:
                continue

            svg = image_to_svg(
                data,
                file.filename,
                remove_whitespace=bool(remove_whitespace),
            )

            results.append({
                "filename": file.filename,
                "svg_filename": f"{os.path.splitext(file.filename)[0]}.svg",
                "svg": svg,
            })
            converted += 1

        if not results:
            return templates.TemplateResponse(
                "index.html",
                {"request": request, "error": "No files were converted."},
            )

        if not is_pro and converted > 0:
            await upsert_usage(email, current + converted, today)

        return templates.TemplateResponse(
            "index.html",
            {"request": request, "results": results},
        )

    except Exception as e:
        print("🔥 /convert error:", repr(e))
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"Server error: {str(e)}"},
        )


# =========================
# Download all
# =========================
@app.post("/download-all")
async def download_all(results_json: str = Form(...)):
    try:
        results = json.loads(results_json)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for item in results:
                svg_filename = item.get("svg_filename", "converted.svg")
                svg_content = item.get("svg", "")
                zip_file.writestr(svg_filename, svg_content)

        zip_buffer.seek(0)

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=svg_files.zip"},
        )
    except Exception as e:
        return Response(f"ZIP download failed: {str(e)}", status_code=500)


# =========================
# Stripe
# =========================
@app.post("/create-checkout-session/{plan}")
async def create_checkout_session(
    plan: str,
    access_token: str = Form(""),
):
    email = await get_supabase_user_email(access_token)

    if not email:
        return Response("Login required", status_code=401)

    if plan not in {"monthly", "lifetime"}:
        return Response("Invalid plan", status_code=400)

    price_id = MONTHLY_PRICE_ID if plan == "monthly" else LIFETIME_PRICE_ID
    mode = "subscription" if plan == "monthly" else "payment"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode=mode,
        customer_email=email,
        metadata={"plan": plan, "user_email": email},
        success_url=f"{DOMAIN}/success",
        cancel_url=f"{DOMAIN}/",
    )

    return RedirectResponse(session.url, status_code=303)


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return Response(f"Webhook error: {str(e)}", status_code=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")
        plan = session.get("metadata", {}).get("plan")

        if email and plan:
            add_paid_user(email, plan)

    return Response(status_code=200)


# =========================
# Check Pro
# =========================
@app.get("/check-pro")
async def check_pro(email: str):
    return {"pro": is_paid_user(email)}