import os
import shutil
import subprocess
import tempfile
from PIL import Image


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


def image_to_svg(file_bytes: bytes, original_filename: str, fill_color: str = "black", remove_whitespace: bool = False) -> str:
    potrace_path = get_potrace_path()

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, original_filename)
        bmp_path = os.path.join(temp_dir, "temp.bmp")
        output_path = os.path.join(temp_dir, "output.svg")

        with open(input_path, "wb") as f:
            f.write(file_bytes)

        img = Image.open(input_path).convert("RGBA")

        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.paste(img, mask=img.split()[3])

        bmp_img = background.convert("L")

        # ===== 여백 제거 =====
        if remove_whitespace:
            bbox = bmp_img.getbbox()
            if bbox:
                bmp_img = bmp_img.crop(bbox)
        # ====================

        bmp_img.save(bmp_path)

        cmd = [potrace_path, bmp_path, "--svg", "-o", output_path]
        subprocess.run(cmd, check=True)

        with open(output_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')

        return svg_content