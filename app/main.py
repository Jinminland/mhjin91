from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.converter import image_to_svg

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "result": None,
            "error": None,
            "fill_color": "#000000",
        }
    )


@app.post("/convert", response_class=HTMLResponse)
async def convert(
        request: Request,
        file: UploadFile = File(...),
        fill_color: str = Form("#000000")
):
    try:
        file_bytes = await file.read()

        svg_result = image_to_svg(
            file_bytes=file_bytes,
            original_filename=file.filename,
            fill_color=fill_color
        )

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "result": svg_result,
                "error": None,
                "fill_color": fill_color,
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "result": None,
                "error": str(e),
                "fill_color": fill_color,
            }
        )


@app.post("/download-svg")
async def download_svg(svg_text: str = Form(...)):
    return Response(
        content=svg_text,
        media_type="image/svg+xml",
        headers={"Content-Disposition": "attachment; filename=converted.svg"}
    )
