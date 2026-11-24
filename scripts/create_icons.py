"""Simple vector icons drawn at high resolution for the PWA."""
from pathlib import Path
from PIL import Image, ImageDraw


class IconPainter:
    """Draws the scanner-frame logo on a 512-unit canvas scaled to each icon size."""
    BACKGROUND, INK = '#0c2419', '#d9f86a'
    CORNERS = ((126, 126, 196, 126), (126, 126, 126, 196), (316, 126, 386, 126), (386, 126, 386, 196),
               (126, 316, 126, 386), (126, 386, 196, 386), (316, 386, 386, 386), (386, 316, 386, 386))

    def __init__(self, directory: Path):
        self.directory = directory

    def paint(self, size: int) -> Path:
        unit = size / 512
        scale = lambda values: tuple(round(value * unit) for value in values)
        image = Image.new('RGB', (size, size), self.BACKGROUND)
        draw = ImageDraw.Draw(image)
        for values in self.CORNERS:
            draw.line(scale(values), fill=self.INK, width=round(16 * unit))
        draw.line(scale((154, 260, 358, 260)), fill=self.INK, width=round(12 * unit))
        draw.ellipse(scale((196, 210, 316, 320)), outline=self.INK, width=round(12 * unit))
        target = self.directory / f'icon-{size}.png'
        image.save(target)
        return target


if __name__ == '__main__':
    output = Path('../frontend/public/icons')
    output.mkdir(parents=True, exist_ok=True)
    painter = IconPainter(output)
    for icon_size in (192, 512):
        painter.paint(icon_size)
