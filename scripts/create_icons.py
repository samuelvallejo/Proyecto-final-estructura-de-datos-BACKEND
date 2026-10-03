"""Iconos vectoriales simples dibujados a alta resolución para la PWA."""
from pathlib import Path
from PIL import Image, ImageDraw

directory = Path('../frontend/public/icons')
directory.mkdir(parents=True, exist_ok=True)
for size in (192, 512):
    image = Image.new('RGB', (size, size), '#0c2419')
    draw = ImageDraw.Draw(image)
    unit = size / 512
    def xy(values):
        return tuple(round(value * unit) for value in values)
    for values in [(126, 126, 196, 126), (126, 126, 126, 196), (316, 126, 386, 126), (386, 126, 386, 196),
                   (126, 316, 126, 386), (126, 386, 196, 386), (316, 386, 386, 386), (386, 316, 386, 386)]:
        draw.line(xy(values), fill='#d9f86a', width=round(16 * unit))
    draw.line(xy((154, 260, 358, 260)), fill='#d9f86a', width=round(12 * unit))
    draw.ellipse(xy((196, 210, 316, 320)), outline='#d9f86a', width=round(12 * unit))
    image.save(directory / f'icon-{size}.png')
