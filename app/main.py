from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.converter import image_to_svg

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": None,
            "fill_color": "#000000",
            "error": None,
        },
    )


@app.post("/convert", response_class=HTMLResponse)
async def convert_images(
    request: Request,
    files: list[UploadFile] = File(...),
    fill_color: str = Form("#000000"),
):
    results = []
    error = None

    try:
        for file in files:
            if not file.filename:
                continue

            file_bytes = await file.read()
            svg_result = image_to_svg(file_bytes, file.filename, fill_color)

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
            "fill_color": fill_color,
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