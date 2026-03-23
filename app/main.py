import io
import json
import os
import zipfile
from datetime import datetime

import stripe
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.converter import image_to_svg

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Stripe 설정
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

MONTHLY_PRICE_ID = "price_1TEEGHDwkY6zitSbrBCUMkNL"
LIFETIME_PRICE_ID = "price_1TEEHNDwkY6zitSbqo6jN25S"
DOMAIN = "https://mhjin91-docker.onrender.com"

# 무료 사용량 저장 (IP 기준, 하루 5개)
usage = {}


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
        headers={"Content-Type": "application/xml; charset=utf-8"},
    )


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


@app.post("/convert", response_class=HTMLResponse)
async def convert_images(
    request: Request,
    files: list[UploadFile] = File(...),
):
    user_ip = request.client.host if request.client else "unknown"
    today = datetime.utcnow().date()

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
                "error": "무료 사용량 5개를 모두 사용했어요 😊 무제한 사용하려면 Pro로 업그레이드 해주세요!",
            },
        )

    results = []
    error = None

    try:
        for file in files:
            if not file.filename:
                continue

            file_bytes = await file.read()
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
async def download_all_svgs(
    results_json: str = Form(...),
):
    results = json.loads(results_json)

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in results:
            svg_filename = item["svg_filename"]
            svg_text = item["svg"]
            zip_file.writestr(svg_filename, svg_text)

    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="converted_svgs.zip"'},
    )


@app.post("/create-checkout-session/{plan}")
async def create_checkout_session(plan: str):
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
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        mode=mode,
        success_url=f"{DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{DOMAIN}/",
    )

    return RedirectResponse(session.url, status_code=303)


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    return templates.TemplateResponse(
        "success.html",
        {"request": request},
    )