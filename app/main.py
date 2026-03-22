import io
import json
import zipfile

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.converter import image_to_svg

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(path="app/static/robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    return FileResponse(path="app/static/sitemap.xml", media_type="application/xml")


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