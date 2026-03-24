import io
import json
import os
import zipfile
from datetime import datetime

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

usage = {}
PAID_USERS_FILE = "paid_users.json"


# =========================
# 안전 파일 처리
# =========================
def load_paid_users():
    if not os.path.exists(PAID_USERS_FILE):
        return {}
    try:
        with open(PAID_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_paid_users(data):
    with open(PAID_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_paid_user(email: str | None):
    if not email:
        return False
    paid_users = load_paid_users()
    return email.lower().strip() in paid_users


def add_paid_user(email: str, plan: str):
    paid_users = load_paid_users()
    paid_users[email.lower().strip()] = {
        "plan": plan,
        "paid_at": datetime.utcnow().isoformat()
    }
    save_paid_users(paid_users)


# =========================
# 기본 라우팅 (🔥 핵심 수정)
# =========================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": None,
            "error": None,
        },
    )


# =========================
# robots / sitemap
# =========================
@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return Response(
        content="""User-agent: *
Allow: /
Sitemap: https://mhjin91-docker.onrender.com/sitemap.xml
""",
        media_type="text/plain",
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://mhjin91-docker.onrender.com/</loc>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
</urlset>
"""
    return Response(
        content=xml_content,
        media_type="application/xml",
    )


# =========================
# SVG 변환
# =========================
@app.post("/convert", response_class=HTMLResponse)
async def convert_images(
    request: Request,
    files: list[UploadFile] = File(...),
    user_email: str = Form(""),
):
    user_ip = request.client.host if request.client else "unknown"
    today = datetime.utcnow().date()
    normalized_email = user_email.lower().strip() if user_email else ""

    if not is_paid_user(normalized_email):
        if user_ip not in usage:
            usage[user_ip] = {"date": today, "count": 0}

        if usage[user_ip]["date"] != today:
            usage[user_ip] = {"date": today, "count": 0}

        if usage[user_ip]["count"] + len(files) > 5:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "results": None,
                    "error": "Free limit reached (5/day). Upgrade to Pro 😊",
                },
            )

    results = []
    error = None

    try:
        for file in files:
            if not file.filename:
                continue

            file_bytes = await file.read()

            # 🔥 안전 처리 추가 (모바일 업로드 실패 방지)
            if not file_bytes:
                continue

            svg_result = image_to_svg(file_bytes, file.filename)

            base_name = file.filename.rsplit(".", 1)[0]
            svg_filename = f"{base_name}.svg"

            results.append(
                {
                    "filename": file.filename,
                    "svg_filename": svg_filename,
                    "svg": svg_result,
                }
            )

        if not is_paid_user(normalized_email):
            usage[user_ip]["count"] += len(files)

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": results,
            "error": error,
        },
    )


# =========================
# 다운로드
# =========================
@app.post("/download-svg")
async def download_svg(
    svg_text: str = Form(...),
    filename: str = Form("converted.svg"),
):
    return Response(
        content=svg_text,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/download-all")
async def download_all_svgs(results_json: str = Form(...)):
    results = json.loads(results_json)

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in results:
            zip_file.writestr(item["svg_filename"], item["svg"])

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="converted_svgs.zip"'},
    )


# =========================
# Stripe
# =========================
@app.post("/create-checkout-session/{plan}")
async def create_checkout_session(
    plan: str,
    user_email: str = Form(...),
):
    if plan == "monthly":
        price_id = MONTHLY_PRICE_ID
        mode = "subscription"
    elif plan == "lifetime":
        price_id = LIFETIME_PRICE_ID
        mode = "payment"
    else:
        return Response(content="Invalid plan", status_code=400)

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode=mode,
        customer_email=user_email,
        metadata={"plan": plan, "user_email": user_email},
        success_url=f"{DOMAIN}/success",
        cancel_url=f"{DOMAIN}/",
    )

    return RedirectResponse(session.url, status_code=303)


@app.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload,
            stripe_signature,
            STRIPE_WEBHOOK_SECRET,
        )
    except Exception:
        return Response(status_code=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")
        plan = session.get("metadata", {}).get("plan", "unknown")

        if email:
            add_paid_user(email, plan)

    return Response(status_code=200)


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request})