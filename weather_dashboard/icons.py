"""
Vector weather + metric icons for a black / white / red e-paper panel.

Icons are drawn as filled shapes (the look of colour e-paper dashboards) and
translated to the panel's three inks:
  - solid red          — sun, UV, lightning, the "bad" end of gauges
  - dithered black     — greys (clouds, moon, droplet), via an ordered Bayer
                         pattern aligned to the panel grid so shades tile cleanly.
                         Use only 1/8, 1/4, 1/2 or 3/4: those levels form regular
                         grids; in-between levels (e.g. 0.62) give an uneven,
                         noisy texture that looks blurry on the panel.
  - solid black        — outlines, rain, snow, fog bars, line icons

Shapes are drawn 4x supersampled in unit coordinates (0..1 of the icon box)
and reduced to 1 bit. Each layer occludes what's beneath it in both planes,
so a cloud in front of the sun really covers it.
"""

import math
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 4  # supersampling factor

# 4x4 Bayer matrix -> ordered dither thresholds
_BAYER = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]


class _Layer:
    __slots__ = ("mask", "plane", "level", "outline")

    def __init__(self, mask, plane, level=1.0, outline=0):
        self.mask = mask          # 'L' image at S x S, 255 = inside
        self.plane = plane        # "black" | "red"
        self.level = level        # 1.0 solid, <1 dithered shade
        self.outline = outline    # px of solid black outline at final size


class _Canvas:
    """Unit-coordinate drawing helpers on a supersampled mask."""

    def __init__(self, size: int):
        self.size = size
        self.S = size * SS

    def new(self):
        m = Image.new("L", (self.S, self.S), 0)
        return m, ImageDraw.Draw(m)

    def px(self, u):
        return u * self.S

    def disc(self, d, cx, cy, r):
        d.ellipse([self.px(cx - r), self.px(cy - r), self.px(cx + r), self.px(cy + r)], fill=255)

    def line(self, d, pts, w):
        width = max(1, int(round(self.px(w))))
        d.line([(self.px(x), self.px(y)) for x, y in pts], fill=255, width=width)
        # round caps
        for x, y in (pts[0], pts[-1]):
            self.disc(d, x, y, w / 2)

    def arc(self, d, cx, cy, r, start, end, w):
        d.arc([self.px(cx - r), self.px(cy - r), self.px(cx + r), self.px(cy + r)],
              start, end, fill=255, width=max(1, int(round(self.px(w)))))

    def cloud(self, x, y, w):
        """Cloud silhouette with its left edge at x, top at y, width w (units)."""
        m, d = self.new()
        self.disc(d, x + 0.27 * w, y + 0.42 * w, 0.17 * w)
        self.disc(d, x + 0.52 * w, y + 0.30 * w, 0.24 * w)
        self.disc(d, x + 0.78 * w, y + 0.44 * w, 0.17 * w)
        d.rounded_rectangle(
            [self.px(x + 0.08 * w), self.px(y + 0.40 * w),
             self.px(x + 0.95 * w), self.px(y + 0.61 * w)],
            radius=self.px(0.105 * w), fill=255,
        )
        return m

    def crescent(self, cx, cy, r, cut_dx, cut_dy, cut_r):
        a, da = self.new()
        self.disc(da, cx, cy, r)
        b, db = self.new()
        self.disc(db, cx + cut_dx, cy + cut_dy, cut_r)
        return ImageChops.subtract(a, b)

    def grow(self, mask, u):
        """Dilate a mask by u units (used to cut a white gap behind front shapes)."""
        return _dilate(mask, int(self.px(u)))


def _dilate(mask, r):
    """Square dilation by r px. Box blur + threshold is O(n), unlike MaxFilter's O(n*k^2)."""
    if r <= 0:
        return mask
    return mask.filter(ImageFilter.BoxBlur(r)).point(lambda p: 255 if p > 0 else 0)


def _erode(mask, r):
    if r <= 0:
        return mask
    return mask.filter(ImageFilter.BoxBlur(r)).point(lambda p: 255 if p >= 250 else 0)


def _minus(a, b):
    return ImageChops.subtract(a, b)


# ---------------------------------------------------------------------------
# Weather icons
# ---------------------------------------------------------------------------

def _sun(c: _Canvas, **_):
    m, d = c.new()
    c.disc(d, 0.5, 0.5, 0.36)
    return [_Layer(m, "red")]


def _moon(c: _Canvas, **_):
    return [_Layer(c.crescent(0.46, 0.5, 0.34, 0.2, -0.13, 0.30), "black", 0.5, outline=1)]


def _behind_cloud(c: _Canvas, back_layers, cloud_mask, cloud_level):
    gap = c.grow(cloud_mask, 0.035)
    out = [_Layer(_minus(l.mask, gap), l.plane, l.level, l.outline) for l in back_layers]
    out.append(_Layer(cloud_mask, "black", cloud_level, outline=1))
    return out


def _partly_cloudy(c: _Canvas, **_):
    m, d = c.new()
    c.disc(d, 0.66, 0.36, 0.23)
    return _behind_cloud(c, [_Layer(m, "red")], c.cloud(0.02, 0.24, 0.80), 0.25)


def _partly_cloudy_night(c: _Canvas, **_):
    moon = c.crescent(0.62, 0.30, 0.26, 0.15, -0.10, 0.22)
    return _behind_cloud(c, [_Layer(moon, "black", 0.5, outline=1)], c.cloud(0.02, 0.30, 0.80), 0.25)


def _cloud(c: _Canvas, **_):
    back = _Layer(c.cloud(0.0, 0.10, 0.66), "black", 0.5, outline=1)
    return _behind_cloud(c, [back], c.cloud(0.24, 0.27, 0.74), 0.25)


def _cloud_top(c: _Canvas, level):
    return _Layer(c.cloud(0.06, 0.02, 0.88), "black", level, outline=1)


def _rain(c: _Canvas, **_):
    m, d = c.new()
    for x in (0.30, 0.50, 0.70):
        c.line(d, [(x + 0.04, 0.66), (x - 0.04, 0.86)], 0.055)
    return [_cloud_top(c, 0.5), _Layer(m, "black")]


def _snow(c: _Canvas, **_):
    m, d = c.new()
    for x, y in ((0.30, 0.70), (0.50, 0.74), (0.70, 0.70), (0.40, 0.88), (0.60, 0.88)):
        c.disc(d, x, y, 0.045)
    return [_cloud_top(c, 0.25), _Layer(m, "black")]


def _thunder(c: _Canvas, **_):
    m, d = c.new()
    bolt = [(0.56, 0.44), (0.36, 0.72), (0.50, 0.72), (0.42, 0.97), (0.68, 0.62), (0.53, 0.62), (0.62, 0.44)]
    d.polygon([(c.px(x), c.px(y)) for x, y in bolt], fill=255)
    cloud = _cloud_top(c, 0.5)
    cloud.mask = _minus(cloud.mask, c.grow(m, 0.03))
    return [cloud, _Layer(m, "red")]


def _fog(c: _Canvas, **_):
    m, d = c.new()
    for y, x0, x1 in ((0.70, 0.10, 0.90), (0.81, 0.20, 0.80), (0.92, 0.32, 0.68)):
        c.line(d, [(x0, y), (x1, y)], 0.06)
    cloud = _Layer(c.cloud(0.08, 0.0, 0.84), "black", 0.25, outline=1)
    cloud.mask = _minus(cloud.mask, c.grow(m, 0.04))
    return [cloud, _Layer(m, "black")]


# ---------------------------------------------------------------------------
# Metric icons (small line icons for the details grid)
# ---------------------------------------------------------------------------

_LW = 0.075  # line weight for metric icons, in units


def _horizon_sun(c: _Canvas, up: bool):
    sun, ds = c.new()
    ds.pieslice([c.px(0.24), c.px(0.36), c.px(0.76), c.px(0.88)], 180, 360, fill=255)
    lines, dl = c.new()
    c.line(dl, [(0.08, 0.66), (0.92, 0.66)], _LW)
    c.line(dl, [(0.28, 0.82), (0.72, 0.82)], _LW)
    tip, tail = (0.04, 0.28) if up else (0.28, 0.04)
    c.line(dl, [(0.5, tail), (0.5, tip)], _LW)
    sgn = 1 if up else -1
    c.line(dl, [(0.38, tip + sgn * 0.11), (0.5, tip), (0.62, tip + sgn * 0.11)], _LW)
    return [_Layer(_minus(sun, c.grow(lines, 0.04)), "red"), _Layer(lines, "black")]


def _sunrise(c, **_):
    return _horizon_sun(c, up=True)


def _sunset(c, **_):
    return _horizon_sun(c, up=False)


def _wind(c: _Canvas, **_):
    m, d = c.new()
    c.line(d, [(0.06, 0.32), (0.64, 0.32)], _LW)
    c.arc(d, 0.64, 0.20, 0.12, 180, 450, _LW)
    c.line(d, [(0.06, 0.52), (0.84, 0.52)], _LW)
    c.line(d, [(0.06, 0.72), (0.54, 0.72)], _LW)
    c.arc(d, 0.54, 0.84, 0.12, -90, 180, _LW)
    return [_Layer(m, "black")]


def _humidity(c: _Canvas, **_):
    m, d = c.new()
    c.disc(d, 0.5, 0.64, 0.27)
    d.polygon([(c.px(0.5), c.px(0.06)), (c.px(0.255), c.px(0.56)), (c.px(0.745), c.px(0.56))], fill=255)
    return [_Layer(m, "black", 0.5, outline=1)]


def _pressure(c: _Canvas, **_):
    m, d = c.new()
    c.arc(d, 0.5, 0.5, 0.40, 0, 360, _LW)
    for a in (-210, -150, -90, -30, 30):
        r = math.radians(a)
        c.line(d, [(0.5 + 0.28 * math.cos(r), 0.5 + 0.28 * math.sin(r)),
                   (0.5 + 0.33 * math.cos(r), 0.5 + 0.33 * math.sin(r))], 0.05)
    c.line(d, [(0.5, 0.5), (0.68, 0.30)], _LW)
    c.disc(d, 0.5, 0.5, 0.07)
    return [_Layer(m, "black")]


def _uv(c: _Canvas, **_):
    m, d = c.new()
    c.disc(d, 0.5, 0.5, 0.2)
    for i in range(8):
        a = math.radians(i * 45)
        c.line(d, [(0.5 + 0.30 * math.cos(a), 0.5 + 0.30 * math.sin(a)),
                   (0.5 + 0.42 * math.cos(a), 0.5 + 0.42 * math.sin(a))], _LW)
    return [_Layer(m, "red")]


def _visibility(c: _Canvas, **_):
    lens_a, da = c.new()
    c.disc(da, 0.5, 1.08, 0.74)
    lens_b, db = c.new()
    c.disc(db, 0.5, -0.08, 0.74)
    lens = ImageChops.multiply(lens_a, lens_b)
    pupil, dp = c.new()
    c.disc(dp, 0.5, 0.5, 0.09)
    ring = _minus(lens, _erode(lens, int(c.px(_LW))))
    return [_Layer(ImageChops.lighter(ring, pupil), "black")]


def _air_quality(c: _Canvas, value: Optional[int] = None, **_):
    left, dl = c.new()
    dl.pieslice([c.px(0.08), c.px(0.22), c.px(0.92), c.px(1.06)], 180, 270, fill=255)
    right, dr = c.new()
    dr.pieslice([c.px(0.08), c.px(0.22), c.px(0.92), c.px(1.06)], 270, 360, fill=255)
    hole, dh = c.new()
    c.disc(dh, 0.5, 0.64, 0.26)
    left, right = _minus(left, hole), _minus(right, hole)
    needle, dn = c.new()
    frac = 0.5 if value is None else max(0.0, min(1.0, value / 100.0))
    a = math.radians(180 + 180 * frac)
    c.line(dn, [(0.5, 0.64), (0.5 + 0.40 * math.cos(a), 0.64 + 0.40 * math.sin(a))], _LW)
    c.disc(dn, 0.5, 0.64, 0.07)
    gap = c.grow(needle, 0.04)
    return [_Layer(_minus(left, gap), "black", 0.5),
            _Layer(_minus(right, gap), "red"),
            _Layer(needle, "black")]


_ICONS: Dict[str, Callable[..., List[_Layer]]] = {
    "sun": _sun,
    "moon": _moon,
    "partly_cloudy": _partly_cloudy,
    "partly_cloudy_night": _partly_cloudy_night,
    "cloud": _cloud,
    "rain": _rain,
    "snow": _snow,
    "thunder": _thunder,
    "fog": _fog,
    "sunrise": _sunrise,
    "sunset": _sunset,
    "wind": _wind,
    "humidity": _humidity,
    "pressure": _pressure,
    "uv": _uv,
    "visibility": _visibility,
    "air_quality": _air_quality,
}


# ---------------------------------------------------------------------------
# Compositing onto the panel buffers
# ---------------------------------------------------------------------------

_PATTERNS: Dict[float, Image.Image] = {}
_PATTERN_SIZE = (808, 488)  # panel + one tile period, so any crop offset fits


def _pattern(level: float) -> Image.Image:
    pat = _PATTERNS.get(level)
    if pat is None:
        w, h = _PATTERN_SIZE
        cut = level * 16
        rows = [bytes(255 if _BAYER[y][x % 4] + 0.5 < cut else 0 for x in range(w)) for y in range(4)]
        pat = Image.frombytes("L", (w, h), b"".join(rows) * (h // 4))
        _PATTERNS[level] = pat
    return pat


def dither_mask(level: float, x0: int, y0: int, w: int, h: int) -> Image.Image:
    """'L' mask (255 = ink) of an ordered-dither shade, aligned to panel coords."""
    if level >= 1.0:
        return Image.new("L", (w, h), 255)
    ox, oy = x0 % 4, y0 % 4
    if w + ox > _PATTERN_SIZE[0] or h + oy > _PATTERN_SIZE[1]:
        raise ValueError("dither region larger than the panel")
    return _pattern(level).crop((ox, oy, ox + w, oy + h))


def _reduce(mask: Image.Image, size: int) -> Image.Image:
    return mask.resize((size, size), Image.BOX).point(lambda p: 255 if p >= 110 else 0)


def draw_icon(black_img: Image.Image, red_img: Image.Image, kind: str,
              cx: int, cy: int, size: int, **kw) -> None:
    """Draw icon `kind` centred at (cx, cy) in a size x size box onto both planes."""
    fn = _ICONS.get(kind, _cloud)
    canvas = _Canvas(size)
    x0, y0 = cx - size // 2, cy - size // 2
    for layer in fn(canvas, **kw):
        area = _reduce(layer.mask, size)
        # Occlude whatever is beneath this layer, in both planes.
        black_img.paste(255, (x0, y0), area)
        red_img.paste(255, (x0, y0), area)
        ink = ImageChops.multiply(area, dither_mask(layer.level, x0, y0, size, size))
        target = red_img if layer.plane == "red" else black_img
        target.paste(0, (x0, y0), ink)
        if layer.outline:
            k = layer.outline * 2 + 1
            edge = _minus(area, area.filter(ImageFilter.MinFilter(k)))
            red_img.paste(255, (x0, y0), edge)
            black_img.paste(0, (x0, y0), edge)
