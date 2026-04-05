import os
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


def image_to_svg(
    file_bytes: bytes,
    original_filename: str,
    fill_color: str = "black",
    remove_whitespace: bool = False
) -> str:
    potrace_path = get_potrace_path()

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, original_filename)
        bmp_path = os.path.join(temp_dir, "temp.bmp")
        output_path = os.path.join(temp_dir, "output.svg")

        with open(input_path, "wb") as f:
            f.write(file_bytes)

        img = Image.open(input_path).convert("RGBA")

        # 1) 투명 여백 제거
        if remove_whitespace:
            alpha = img.getchannel("A")
            bbox = alpha.getbbox()
            if bbox:
                img = img.crop(bbox)

        # 2) 흰 배경 합성
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.alpha_composite(img)

        # 3) 그레이스케일 + 대비 보정
        gray = background.convert("L")
        gray = ImageOps.autocontrast(gray)

        # 4) 흑백화
        threshold = 200
        bw = gray.point(lambda p: 0 if p < threshold else 255, mode="1")
        bw.save(bmp_path)

        # 5) 기본값부터 시작해서 점진적으로 압축
        # 앞쪽일수록 품질 우선, 뒤로 갈수록 용량 우선
        attempts = [
            {"opttolerance": "0.1", "turdsize": "1"},
            {"opttolerance": "0.1", "turdsize": "2"},
            {"opttolerance": "0.1", "turdsize": "4"},
            {"opttolerance": "0.2", "turdsize": "4"},
            {"opttolerance": "0.3", "turdsize": "4"},
            {"opttolerance": "0.3", "turdsize": "6"},
            {"opttolerance": "0.5", "turdsize": "6"},
            {"opttolerance": "0.7", "turdsize": "8"},
        ]

        best_svg = None
        best_size = None

        for attempt in attempts:
            svg_content = run_potrace(
                potrace_path=potrace_path,
                bmp_path=bmp_path,
                output_path=output_path,
                opttolerance=attempt["opttolerance"],
                turdsize=attempt["turdsize"],
            )

            svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')
            size_kb = get_svg_size_kb(svg_content)

            # 가장 작은 결과도 같이 기억
            if best_svg is None or size_kb < best_size:
                best_svg = svg_content
                best_size = size_kb

            # 150KB 이하가 되면 바로 반환
            if size_kb <= MAX_SVG_KB:
                return svg_content

        # 끝까지 안 되면 가장 작은 결과 반환
        return best_svg