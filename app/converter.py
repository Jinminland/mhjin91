import os
import re
import shutil
import subprocess
import tempfile
from PIL import Image, ImageOps


MAX_SVG_KB = 150


def get_potrace_path() -> str:
    potrace_path = os.getenv("POTRACE_PATH")

    if potrace_path:
        if os.path.isfile(potrace_path):
            return potrace_path
        raise FileNotFoundError(f"potrace 실행 파일을 찾을 수 없습니다: {potrace_path}")

    auto_path = shutil.which("potrace")
    if auto_path:
        return auto_path

    raise RuntimeError(
        "potrace를 찾을 수 없습니다. "
        "POTRACE_PATH 환경변수를 설정하거나, potrace를 설치해야 합니다."
    )


def run_potrace(
    potrace_path: str,
    bmp_path: str,
    output_path: str,
    opttolerance: str,
    turdsize: str,
) -> str:
    cmd = [
        potrace_path,
        bmp_path,
        "--svg",
        "-o", output_path,
        "--flat",
        "--alphamax", "0.7",
        "--opttolerance", opttolerance,
        "--turdsize", turdsize,
    ]
    subprocess.run(cmd, check=True)

    with open(output_path, "r", encoding="utf-8") as f:
        return f.read()


def get_svg_size_kb(svg_content: str) -> float:
    return len(svg_content.encode("utf-8")) / 1024


def minify_svg(svg_content: str) -> str:
    svg_content = re.sub(r">\s+<", "><", svg_content)
    svg_content = re.sub(r"\s{2,}", " ", svg_content)
    svg_content = svg_content.replace("\n", "").replace("\t", "")
    return svg_content.strip()


def make_bw_image(
    img: Image.Image,
    remove_whitespace: bool,
    threshold: int,
    scale: float,
) -> Image.Image:
    img = img.convert("RGBA")

    # 1) 투명 여백 제거
    if remove_whitespace:
        alpha = img.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            img = img.crop(bbox)

    # 2) 강제 압축 모드에서는 이미지 자체를 축소
    if scale < 1.0:
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # 3) 흰 배경 합성
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    background.alpha_composite(img)

    # 4) 그레이스케일 + 대비 보정
    gray = background.convert("L")
    gray = ImageOps.autocontrast(gray)

    # 5) 흑백화
    bw = gray.point(lambda p: 0 if p < threshold else 255, mode="1")
    return bw


def image_to_svg(
    file_bytes: bytes,
    original_filename: str,
    fill_color: str = "black",
    remove_whitespace: bool = False,
    compress_more: bool = False,
) -> tuple[str, float]:
    potrace_path = get_potrace_path()

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, original_filename)
        bmp_path = os.path.join(temp_dir, "temp.bmp")
        output_path = os.path.join(temp_dir, "output.svg")

        with open(input_path, "wb") as f:
            f.write(file_bytes)

        original_img = Image.open(input_path).convert("RGBA")

        # =========================
        # 기본 모드: 그냥 SVG 변환만
        # =========================
        if not compress_more:
            bw = make_bw_image(
                img=original_img,
                remove_whitespace=remove_whitespace,
                threshold=200,
                scale=1.0,
            )
            bw.save(bmp_path)

            svg_content = run_potrace(
                potrace_path=potrace_path,
                bmp_path=bmp_path,
                output_path=output_path,
                opttolerance="0.1",
                turdsize="1",
            )

            svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')
            svg_content = minify_svg(svg_content)
            size_kb = get_svg_size_kb(svg_content)
            return svg_content, round(size_kb, 1)

        # =========================
        # 강제 압축 모드: 150KB 이하가 될 때까지 계속 시도
        # =========================
        attempts = [
            {"scale": 1.00, "threshold": 200, "opttolerance": "0.3", "turdsize": "4"},
            {"scale": 1.00, "threshold": 210, "opttolerance": "0.5", "turdsize": "6"},
            {"scale": 0.90, "threshold": 210, "opttolerance": "0.7", "turdsize": "8"},
            {"scale": 0.80, "threshold": 220, "opttolerance": "1.0", "turdsize": "10"},
            {"scale": 0.70, "threshold": 225, "opttolerance": "1.2", "turdsize": "12"},
            {"scale": 0.60, "threshold": 230, "opttolerance": "1.5", "turdsize": "14"},
            {"scale": 0.50, "threshold": 235, "opttolerance": "2.0", "turdsize": "16"},
            {"scale": 0.40, "threshold": 240, "opttolerance": "2.5", "turdsize": "20"},
            {"scale": 0.30, "threshold": 245, "opttolerance": "3.0", "turdsize": "24"},
        ]

        best_svg = None
        best_size = None

        for attempt in attempts:
            bw = make_bw_image(
                img=original_img.copy(),
                remove_whitespace=remove_whitespace,
                threshold=attempt["threshold"],
                scale=attempt["scale"],
            )
            bw.save(bmp_path)

            svg_content = run_potrace(
                potrace_path=potrace_path,
                bmp_path=bmp_path,
                output_path=output_path,
                opttolerance=attempt["opttolerance"],
                turdsize=attempt["turdsize"],
            )

            svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')
            svg_content = minify_svg(svg_content)
            size_kb = get_svg_size_kb(svg_content)

            if best_svg is None or best_size is None or size_kb < best_size:
                best_svg = svg_content
                best_size = size_kb

            if size_kb <= MAX_SVG_KB:
                return svg_content, round(size_kb, 1)

        # 끝까지 못 맞췄으면 가장 작은 결과 반환
        return best_svg, round(best_size, 1)