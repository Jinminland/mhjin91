import os
import subprocess
import tempfile
from PIL import Image

POTRACE_PATH = os.getenv("POTRACE_PATH")

if not POTRACE_PATH:
    raise ValueError("POTRACE_PATH 환경변수가 설정되지 않았습니다.")

if not os.path.isfile(POTRACE_PATH):
    raise FileNotFoundError(f"potrace 실행 파일을 찾을 수 없습니다: {POTRACE_PATH}")


def image_to_svg(file_bytes: bytes, original_filename: str, fill_color: str = "black") -> str:
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
        bmp_img.save(bmp_path)

        cmd = [POTRACE_PATH, bmp_path, "--svg", "-o", output_path]
        subprocess.run(cmd, check=True)

        with open(output_path, "r", encoding="utf-8") as f:
            svg_content = f.read()

        svg_content = svg_content.replace("<path", f'<path fill="{fill_color}"')

        return svg_content