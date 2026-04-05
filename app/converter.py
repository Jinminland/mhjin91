import os
import shutil
import subprocess
import tempfile
from PIL import Image, ImageOps


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

        # 1) 흰 배경 합성
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.alpha_composite(img)

        # 2) 그레이스케일 변환
        gray = background.convert("L")

        # 3) 자동 대비 보정 (옅은 선 살리기)
        gray = ImageOps.autocontrast(gray)

        # 4) threshold로 직접 흑백화
        # 숫자를 낮추면 더 많은 선이 남고,
        # 높이면 연한 부분이 더 날아감
        threshold = 200
        bw = gray.point(lambda p: 0 if p < threshold else 255, mode="1")

        # 5) 여백 제거
        if remove_whitespace:
            bbox = bw.getbbox()
            if bbox:
                bw = bw.crop(bbox)

        bw.save(bmp_path)

        # 6) potrace 옵션 조정
        cmd = [
            potrace_path,
            bmp_path,
            "--svg",
            "-o", output_path,
            "--flat",
            "--alphamax", "0.7",
            "--opttolerance", "0.1",
            "--turdsize", "1"
        ]
        subprocess.run(cmd, check=True)

        with open(output_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')

        return svg_content