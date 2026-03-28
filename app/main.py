import io
import json
import os
import zipfile
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
import stripe
from fastapi import FastAPI, Request, UploadFile, File, Form, Header
from fastapi.responses import HTMLResponse, Response, RedirectResponse, JSONResponse
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

FREE_DAILY_LIMIT = 5


# =========================
# Supabase Auth
# =========================
async def get_supabase_user_email(access_token: str | None):
    if not access_token:
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

    return res.json().get("email")


# =========================
# Supabase Plan 관리
# =========================
async def upsert_user_plan(email: str, plan: str):
    url = f"{SUPABASE_URL}/rest/v1/user_plans"

    expires_at = None
    if plan == "monthly":
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    payload = {
        "email": email,
        "plan": plan,
        "expires_at": expires_at,
        "updated_at": datetime.utcnow().isoformat(),
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, headers=headers, json=payload)


async def get_user_plan(email: str):
    url = f"{SUPABASE_URL}/rest/v1/user_plans?email=eq.{quote(email)}"

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    data = res.json()
    return data[0] if data else None


async def is_pro_user(email: str):
    user = await get_user_plan(email)

    if not user:
        return False

    if user["plan"] == "lifetime":
        return True

    if user["plan"] == "monthly":
        expires_at = user.get("expires_at")
        if expires_at:
            return datetime.fromisoformat(expires_at) > datetime.utcnow()

    return False


async def get_plan_status(email: str):
    user = await get_user_plan(email)

    if not user:
        return {"plan": "free", "label": "Free"}

    if user["plan"] == "lifetime":
        return {"plan": "lifetime", "label": "Lifetime Pro"}

    if user["plan"] == "monthly":
        expires_at = user.get("expires_at")
        if expires_at:
            days_left = max(
                (datetime.fromisoformat(expires_at) - datetime.utcnow()).days, 0
            )
            return {
                "plan": "monthly",
                "label": f"Pro Monthly · {days_left} day(s) left",
            }

    return {"plan": "free", "label": "Free"}


# =========================
# Usage (Supabase)
# =========================
async def get_usage(email: str):
    url = f"{SUPABASE_URL}/rest/v1/usage_limits?email=eq.{quote(email)}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

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
        await client.post(url, headers=headers, json=payload)


async def get_today_usage_state(email: str):
    today = datetime.utcnow().date().isoformat()
    usage = await get_usage(email)

    current = 0
    if usage and usage.get("last_date") == today:
        current = int(usage.get("count", 0))

    remaining = max(FREE_DAILY_LIMIT - current, 0)

    return {"today": today, "current": current, "remaining": remaining}


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
        {"request": request, "success_message": "Payment completed!"},
    )


# =========================
# Convert Access
# =========================
@app.post("/check-convert-access")
async def check_convert_access(access_token: str = Form(""), file_count: int = Form(1)):
    email = await get_supabase_user_email(access_token)

    if not email:
        return JSONResponse({"allowed": False}, status_code=401)

    if await is_pro_user(email):
        return JSONResponse({"allowed": True})

    usage = await get_today_usage_state(email)

    if usage["remaining"] < file_count:
        return JSONResponse({"allowed": False})

    return JSONResponse({"allowed": True})


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
    email = await get_supabase_user_email(access_token)

    if not email:
        return templates.TemplateResponse("index.html", {"request": request})

    is_pro = await is_pro_user(email)

    if not is_pro:
        usage = await get_today_usage_state(email)

        if usage["remaining"] < len(files):
            return templates.TemplateResponse("index.html", {"request": request})

    results = []

    for file in files:
        data = await file.read()
        svg = image_to_svg(data, file.filename)

        results.append({
            "filename": file.filename,
            "svg_filename": f"{file.filename}.svg",
            "svg": svg,
        })

    return templates.TemplateResponse("index.html", {"request": request, "results": results})


# =========================
# Stripe
# =========================
@app.post("/create-checkout-session/{plan}")
async def create_checkout_session(plan: str, access_token: str = Form("")):
    email = await get_supabase_user_email(access_token)

    if not email:
        return Response("Login required", status_code=401)

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

    return RedirectResponse(session.url)


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()

    event = stripe.Webhook.construct_event(
        payload, stripe_signature, STRIPE_WEBHOOK_SECRET
    )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")
        plan = session.get("metadata", {}).get("plan")

        if email and plan:
            await upsert_user_plan(email, plan)

    return Response(status_code=200)


# =========================
# Plan Status
# =========================
@app.post("/my-plan-status")
async def my_plan_status(access_token: str = Form("")):
    email = await get_supabase_user_email(access_token)

    if not email:
        return JSONResponse({"plan": "free", "label": "Free"})

    return JSONResponse(await get_plan_status(email))