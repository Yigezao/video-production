"""程序排版卡（Pillow）。

文字全部由程序绘制，不让绘图 AI 生成中文。
输出 9:16 与 16:9 两套，互不裁切。
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .config import (
    ASPECT_SUFFIX,
    COLORS,
    SIZES,
    episode,
    font_path,
    load_plan,
    resolve_image,
    write_json,
)

TEMPLATE_VERSION = "0.4.0"
CARD_TYPES = {"title_card", "book_card", "section_card", "quote_card",
              "character_card", "timeline_card", "end_card"}
PANEL_TYPES = {"character_card", "timeline_card", "quote_card"}


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


INK = _rgb(COLORS["ink"])
PAPER = _rgb(COLORS["paper"])
VERMILION = _rgb(COLORS["vermilion"])
COPPER = _rgb(COLORS["copper"])
GREY_PAPER = _rgb(COLORS["grey_paper"])
WHITE = _rgb(COLORS["white"])


def _rgba(color: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return color[0], color[1], color[2], alpha


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


@lru_cache(maxsize=64)
def _font(role: str, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(font_path(role)), size)
    try:
        font.set_variation_by_name("SemiBold" if role == "title" else "Medium")
    except Exception:  # noqa: BLE001 - 字体不是可变字体时忽略
        pass
    return font


def _paper(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, _rgba(PAPER))
    draw = ImageDraw.Draw(image, "RGBA")
    top, bottom = PAPER, _lerp(PAPER, GREY_PAPER, 0.35)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=_rgba(_lerp(top, bottom, y / max(1, height - 1))))
    rng = random.Random(width * 31 + height)
    for _ in range(max(1200, width * height // 2200)):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.point((x, y), fill=_rgba(INK, rng.randint(3, 7)))
    for y in range(0, height, max(90, height // 16)):
        draw.line([(0, y), (width, y)], fill=_rgba(INK, 3), width=1)
    return image


def _ink(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, _rgba(INK))
    draw = ImageDraw.Draw(image, "RGBA")
    top = _lerp(INK, (34, 36, 44), 0.0)
    bottom = _lerp(INK, (34, 36, 44), 0.55)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=_rgba(_lerp(top, bottom, y / max(1, height - 1))))
    return image


def _overlay(image: Image.Image, draw_callback) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw_callback(ImageDraw.Draw(overlay, "RGBA"))
    return Image.alpha_composite(image, overlay)


def _fold(image: Image.Image, aspect: str) -> Image.Image:
    width, height = image.size
    fold = int(width * (0.09 if aspect == "9:16" else 0.065))

    def draw(draw: ImageDraw.ImageDraw) -> None:
        draw.polygon([(width - fold, height), (width, height - fold), (width, height)],
                     fill=_rgba(GREY_PAPER, 255))
        draw.line([(width - fold, height), (width, height - fold)],
                  fill=_rgba(VERMILION, 220), width=max(4, width // 180))

    return _overlay(image, draw)


def _stamp(image: Image.Image, char: str | None) -> Image.Image:
    if not char:
        return image
    width, height = image.size
    size = int(width * 0.065)
    margin = int(width * 0.075)
    fold = int(width * 0.09)
    x = width - margin - size
    y = height - margin - fold - size - int(width * 0.02)
    if y < height * 0.55:
        return image

    def draw(draw: ImageDraw.ImageDraw) -> None:
        draw.rounded_rectangle((x, y, x + size, y + size), radius=6,
                               fill=_rgba(VERMILION, 235), outline=_rgba(WHITE, 90), width=2)
        font = _font("title", int(size * 0.62))
        draw.text((x + size / 2, y + size / 2 + 2), char, font=font,
                  fill=_rgba(WHITE, 245), anchor="mm")

    return _overlay(image, draw)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    closing = set("，。！？；：、）】》”’」』…")
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
            current = ""
            continue
        if not current:
            current = char
            continue
        if draw.textlength(current + char, font=font) <= max_width:
            current += char
            continue
        if char in closing and lines:
            lines[-1] += char
            continue
        if char in closing and current:
            current += char
            lines.append(current)
            current = ""
            continue
        lines.append(current)
        current = char
    if current:
        lines.append(current)
    return lines or [""]


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    role: str,
    box_width: float,
    box_height: float,
    max_size: int,
    min_size: int = 28,
    max_lines: int = 3,
) -> tuple[list[str], ImageFont.FreeTypeFont, bool]:
    clipped = False
    chosen: tuple[list[str], ImageFont.FreeTypeFont] | None = None
    for size in range(max_size, min_size - 1, -2):
        font = _font(role, size)
        lines = _wrap(draw, text, font, box_width)
        line_height = size * 1.32
        if len(lines) <= max_lines and len(lines) * line_height <= box_height:
            widths = [draw.textlength(line, font=font) for line in lines]
            if all(width <= box_width * 1.02 for width in widths):
                chosen = (lines, font)
                break
    if chosen is None:
        clipped = True
        font = _font(role, min_size)
        lines = _wrap(draw, text, font, box_width)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        line_height = min_size * 1.32
        while len(lines) > 1 and len(lines) * line_height > box_height:
            lines.pop()
        chosen = (lines, font)
    return chosen[0], chosen[1], clipped


def _draw_block(
    image: Image.Image,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    box: tuple[float, float, float, float],
    fill: tuple[int, int, int, int],
    align: str = "center",
    clipped: bool = False,
) -> None:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    line_height = int(font.size * 1.32)
    total = line_height * len(lines)
    start_y = y0 + (y1 - y0 - total) / 2
    for index, line in enumerate(lines):
        center_y = start_y + line_height * index + line_height / 2
        if align == "center":
            draw.text(((x0 + x1) / 2, center_y), line, font=font, fill=fill, anchor="mm")
        else:
            draw.text((x0, center_y), line, font=font, fill=fill, anchor="lm")
    if clipped:
        draw.rectangle((x0, y0, x1, y1), outline=_rgba(VERMILION, 220), width=4)
        draw.text((x0 + 8, y1 - 24), "文字溢出", font=_font("body", 24),
                  fill=_rgba(VERMILION, 240), anchor="lm")


def _small_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[float, float],
    size: int,
    fill: tuple[int, int, int, int],
    anchor: str = "la",
) -> None:
    if not text:
        return
    draw.text(xy, str(text), font=_font("body", size), fill=fill, anchor=anchor)


def _top_labels(
    draw: ImageDraw.ImageDraw,
    scene: dict,
    meta: dict,
    aspect: str,
    on_ink: bool = False,
) -> None:
    width, height = SIZES[aspect]
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    size = 30 if aspect == "9:16" else 28
    color = _rgba(PAPER if on_ink else COPPER, 230)
    brand = str(meta.get("brand") or "")
    if "{{" in brand:
        brand = ""
    column = str(scene.get("column") or meta.get("column") or "")
    y = int(height * 0.065)
    if brand:
        _small_text(draw, brand, (margin, y), size, color)
    if column:
        _small_text(draw, column, (width - margin, y), size, color, anchor="ra")


def _panel(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    def draw(draw: ImageDraw.ImageDraw) -> None:
        draw.rounded_rectangle(box, radius=22, fill=_rgba(PAPER, 238),
                               outline=_rgba(COPPER, 140), width=2)
        draw.line([(box[0] + 22, box[1] + 12), (box[0] + 22, box[3] - 12)],
                  fill=_rgba(VERMILION, 190), width=4)

    return _overlay(image, draw)


def _title_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    meta = loaded["meta"]
    image = _paper((width, height))
    draw = ImageDraw.Draw(image)
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    _top_labels(draw, scene, meta, aspect)

    line_y = int(height * 0.125)
    draw.line([(margin, line_y), (width - margin, line_y)], fill=_rgba(VERMILION, 210), width=3)

    title = str(scene.get("title") or f"《{meta.get('book_title') or ''}》")
    title_max = int(width * 0.14) if aspect == "9:16" else int(height * 0.135)
    lines, font, clipped = _fit(draw, title, "title", width - margin * 2, height * 0.30,
                                max(64, title_max), 48, 2)
    _draw_block(image, lines, font, (margin, height * 0.20, width - margin, height * 0.52),
                _rgba(INK), clipped=clipped)

    hook = str(scene.get("line") or "")
    hook_max = int(width * 0.05) if aspect == "9:16" else int(height * 0.05)
    lines2, font2, clipped2 = _fit(draw, hook, "body", width - margin * 2, height * 0.15,
                                   max(32, hook_max), 30, 2)
    _draw_block(image, lines2, font2, (margin, height * 0.555, width - margin, height * 0.70),
                _rgba(VERMILION), clipped=clipped2)

    author = str(meta.get("author") or "未标注")
    _small_text(draw, f"《{meta.get('book_title') or ''}》 · {author}",
                (width / 2, height * 0.775), 30 if aspect == "9:16" else 28,
                _rgba(COPPER, 235), anchor="ma")

    image = _fold(image, aspect)
    image = _stamp(image, None)
    return image


def _darken_background(image: Image.Image) -> Image.Image:
    """把插画背景压暗，让书封卡融入视频，而不是一块白板。"""
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        t = y / max(1, height - 1)
        alpha = int(165 - 75 * (1 - abs(t - 0.5) * 2) ** 1.3)
        draw.line([(0, y), (width, y)], fill=(8, 10, 14, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGBA")


def _book_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    """书封卡：一本立着的书，封面文字全部程序绘制。"""
    width, height = SIZES[aspect]
    meta = loaded["meta"]
    route = str(meta.get("visual_route") or "cinema")
    background = str(scene.get("image") or "").strip()
    has_photo = False
    image = None
    if background:
        path = resolve_image(loaded, background)
        if path.is_file():
            image = ImageOps.fit(Image.open(path).convert("RGB"), (width, height),
                                 method=Image.LANCZOS, centering=(0.5, 0.5))
            image = _darken_background(image)
            has_photo = True
    if image is None:
        # cinema 用深色底，classic/type 用纸底；不再给 B 路线一块白板
        image = _ink((width, height)) if route == "cinema" else _paper((width, height))
    draw = ImageDraw.Draw(image)
    brand = str(meta.get("brand") or "")
    if "{{" not in brand:
        _small_text(draw, brand, (int(width * 0.075), int(height * 0.065)),
                    30, _rgba(PAPER if (has_photo or route == "cinema") else COPPER, 235))

    # 书封颜色从背景里取，压成同一套色调，不要一块高对比白板
    if has_photo:
        average = tuple(int(value) for value in ImageStat.Stat(image.convert("RGB")).mean)
        cover_color = _lerp(average, PAPER, 0.22)
    elif route == "cinema":
        cover_color = _lerp(INK, PAPER, 0.18)
    else:
        cover_color = PAPER
    luminance = 0.299 * cover_color[0] + 0.587 * cover_color[1] + 0.114 * cover_color[2]
    cover_text = PAPER if luminance < 140 else INK
    cover_sub = _lerp(cover_text, COPPER, 0.45)
    edge_color = _lerp(cover_color, PAPER, 0.45)
    spine_color = _lerp(cover_color, INK, 0.35)
    border_color = _lerp(cover_color, INK, 0.45)

    # AI 书封图：图里已经有书，不再画一本程序书；标题/作者放在上下留白
    if bool(scene.get("book_image")) and has_photo:
        margin = int(width * (0.075 if aspect == "9:16" else 0.06))
        column = str(scene.get("column") or meta.get("column") or "")
        if column:
            _small_text(draw, column, (width - margin, int(height * 0.065)),
                        30, _rgba(PAPER, 235), anchor="ra")
        title = str(scene.get("title") or f"《{meta.get('book_title') or ''}》")
        title_box = (margin, int(height * (0.075 if aspect == "9:16" else 0.07)),
                     width - margin, int(height * (0.31 if aspect == "9:16" else 0.32)))
        lines, font, clipped = _fit(
            draw, title, "title", title_box[2] - title_box[0], title_box[3] - title_box[1],
            int(width * 0.13) if aspect == "9:16" else int(height * 0.13), 44, 2)
        _draw_block(image, lines, font, title_box, _rgba(PAPER), clipped=clipped)
        draw = ImageDraw.Draw(image)
        draw.line([(margin, int(height * 0.345)), (margin + int(width * 0.12), int(height * 0.345))],
                  fill=_rgba(VERMILION, 235), width=6)
        line = str(scene.get("line") or "")
        if line:
            line_box = (margin, int(height * (0.72 if aspect == "9:16" else 0.70)),
                        width - margin, int(height * (0.82 if aspect == "9:16" else 0.80)))
            lines2, font2, clipped2 = _fit(
                draw, line, "body", line_box[2] - line_box[0], line_box[3] - line_box[1],
                48 if aspect == "9:16" else 40, 28, 2)
            _draw_block(image, lines2, font2, line_box, _rgba(cover_sub), clipped=clipped2)
        author = str(scene.get("author") or meta.get("author") or "未标注")
        _small_text(draw, author, (width / 2, int(height * 0.88)),
                    34 if aspect == "9:16" else 30, _rgba(cover_sub, 245), anchor="ma")
        draw.line([(margin, int(height * 0.925)), (width - margin, int(height * 0.925))],
                  fill=_rgba(PAPER, 70), width=2)
        return image

    if aspect == "9:16":
        book_h = int(height * 0.60)
        top = int(height * 0.21)
    else:
        book_h = int(height * 0.72)
        top = int(height * 0.13)
    book_w = int(book_h * 0.70)
    left = (width - book_w) // 2
    right = left + book_w
    bottom = top + book_h

    # 阴影
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((left + 14, top + 18, right + 14, bottom + 18),
                                  radius=12, fill=(0, 0, 0, 55))
    image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(18)))
    draw = ImageDraw.Draw(image)

    # 书页侧边
    edge = max(8, int(book_w * 0.035))
    draw.rounded_rectangle((left + edge, top + edge, right + edge, bottom + edge),
                           radius=8, fill=_rgba(edge_color))
    for offset in range(6, 0, -2):
        draw.line([(left + edge + 2, top + edge + offset), (right + edge - 2, top + edge + offset)],
                  fill=_rgba(INK, 25), width=1)

    # 封面
    draw.rounded_rectangle((left, top, right, bottom), radius=8,
                           fill=_rgba(cover_color), outline=_rgba(border_color, 180), width=2)
    spine = max(18, int(book_w * 0.055))
    draw.rectangle((left, top, left + spine, bottom), fill=_rgba(spine_color))
    draw.line([(left + spine, top + 12), (left + spine, bottom - 12)],
              fill=_rgba(VERMILION, 210), width=4)

    inner_left = left + spine + max(22, int(book_w * 0.06))
    inner_right = right - max(26, int(book_w * 0.06))
    column = str(scene.get("column") or meta.get("column") or "")
    if column:
        _small_text(draw, column, (inner_left, top + int(book_h * 0.055)),
                    max(22, int(book_w * 0.038)), _rgba(cover_sub, 240))

    title = str(scene.get("title") or f"《{meta.get('book_title') or ''}》")
    title_box = (inner_left, top + int(book_h * 0.20), inner_right, top + int(book_h * 0.60))
    max_lines = 1 if len(title.strip("《》")) <= 6 else 2
    lines, font, clipped = _fit(
        draw, title, "title", title_box[2] - title_box[0], title_box[3] - title_box[1],
        max(40, int(book_w * 0.18) if aspect == "9:16" else int(book_h * 0.15)), 30, max_lines)
    _draw_block(image, lines, font, title_box, _rgba(cover_text), clipped=clipped)
    draw = ImageDraw.Draw(image)

    author = str(scene.get("author") or meta.get("author") or "未标注")
    _small_text(draw, author, ((inner_left + inner_right) / 2, top + int(book_h * 0.68)),
                max(24, int(book_w * 0.045)), _rgba(cover_sub, 245), anchor="ma")

    line = str(scene.get("line") or "")
    if line:
        lines2, font2, clipped2 = _fit(
            draw, line, "body", inner_right - inner_left, int(book_h * 0.13),
            max(22, int(book_w * 0.036)), 20, 2)
        _draw_block(image, lines2, font2,
                    (inner_left, top + int(book_h * 0.75), inner_right, top + int(book_h * 0.90)),
                    _rgba(cover_sub), clipped=clipped2)

    # 封面朱砂印
    seal = max(34, int(book_w * 0.09))
    sx = right - seal - max(20, int(book_w * 0.045))
    sy = bottom - seal - max(20, int(book_w * 0.045))
    draw.rounded_rectangle((sx, sy, sx + seal, sy + seal), radius=5,
                           fill=_rgba(VERMILION, 240))
    seal_char = (column or "读")[:1]
    draw.text((sx + seal / 2, sy + seal / 2 + 1), seal_char,
              font=_font("title", max(18, int(seal * 0.58))), fill=_rgba(WHITE, 245), anchor="mm")
    return image


def _section_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    meta = loaded["meta"]
    image = _ink((width, height))
    draw = ImageDraw.Draw(image)
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    _top_labels(draw, scene, meta, aspect, on_ink=True)

    index_text = str(scene.get("index") or "01")
    index_size = min(int(width * 0.17), int(height * 0.19))
    draw.text((margin, height * 0.145), index_text, font=_font("title", max(80, index_size)),
              fill=_rgba(COPPER, 235), anchor="la")

    draw.line([(margin, height * 0.365), (margin + width * 0.12, height * 0.365)],
              fill=_rgba(VERMILION, 230), width=6)

    name = str(scene.get("name") or "")
    lines, font, clipped = _fit(draw, name, "title", width - margin * 2, height * 0.18,
                                min(int(width * 0.085), int(height * 0.105)), 40, 2)
    _draw_block(image, lines, font, (margin, height * 0.38, width - margin, height * 0.56),
                _rgba(PAPER), align="left", clipped=clipped)

    line = str(scene.get("line") or "")
    lines2, font2, clipped2 = _fit(draw, line, "body", width - margin * 2, height * 0.12,
                                   40 if aspect == "9:16" else 34, 28, 2)
    _draw_block(image, lines2, font2, (margin, height * 0.60, width - margin, height * 0.72),
                _rgba(GREY_PAPER), align="left", clipped=clipped2)

    image = _fold(image, aspect)
    image = _stamp(image, str(scene.get("column") or meta.get("column") or "")[:1] or None)
    return image


def _quote_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    meta = loaded["meta"]
    lower = scene.get("layout") == "lower_third"
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0)) if lower else _paper((width, height))
    draw = ImageDraw.Draw(image)
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    if lower:
        box = (margin, int(height * 0.635), width - margin, int(height * 0.775))
        image = _panel(image, box)
        draw = ImageDraw.Draw(image)
        quote_box = (box[0] + 34, box[1] + 18, box[2] - 34, box[1] + int((box[3] - box[1]) * 0.68))
        source_y = box[3] - 26
        quote_max = 40 if aspect == "9:16" else 34
    else:
        _top_labels(draw, scene, meta, aspect)
        quote_box = (margin, height * 0.26, width - margin, height * 0.58)
        source_y = height * 0.655
        quote_max = int(width * 0.075) if aspect == "9:16" else int(height * 0.085)

    quote = str(scene.get("quote") or "")
    lines, font, clipped = _fit(draw, quote, "title", quote_box[2] - quote_box[0],
                                quote_box[3] - quote_box[1], max(44, quote_max), 30, 3)
    _draw_block(image, lines, font, quote_box, _rgba(INK if not lower else INK), clipped=clipped)
    draw = ImageDraw.Draw(image)

    if not lower:
        draw.line([(width / 2 - 120, height * 0.615), (width / 2 + 120, height * 0.615)],
                  fill=_rgba(VERMILION, 200), width=3)
    source = str(scene.get("source") or "")
    if scene.get("quote_type") == "paraphrase":
        source = ("转述" + (" · " if source else "") + source).strip()
    if source:
        _small_text(draw, source, (width / 2, source_y), 28 if aspect == "9:16" else 26,
                    _rgba(COPPER, 240), anchor="ma")

    image = _fold(image, aspect) if not lower else image
    return image


def _character_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    lower = scene.get("layout") == "lower_third"
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0)) if lower else _paper((width, height))
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    if lower:
        box = (margin, int(height * 0.645), width - margin, int(height * 0.765))
    else:
        box = (margin, int(height * 0.34), width - margin, int(height * 0.66))
    image = _panel(image, box)
    draw = ImageDraw.Draw(image)
    characters = scene.get("characters") or []
    if not characters:
        return image
    columns = 2 if len(characters) > 2 else max(1, len(characters))
    rows = math.ceil(len(characters) / columns)
    cell_w = (box[2] - box[0]) / columns
    cell_h = (box[3] - box[1]) / rows
    name_size = 40 if aspect == "9:16" else 36
    role_size = 26 if aspect == "9:16" else 24
    for index, person in enumerate(characters[:4]):
        col, row = index % columns, index // columns
        x0 = box[0] + col * cell_w + 20
        y0 = box[1] + row * cell_h + 8
        cell_width = cell_w - 40
        cell_height = cell_h - 16
        name = str(person.get("name") or "")
        role = str(person.get("role") or "")
        name_lines, name_font, name_clipped = _fit(
            draw, name, "body", cell_width, cell_height * 0.52, name_size, 24, 1)
        _draw_block(image, name_lines, name_font,
                    (x0, y0, x0 + cell_width, y0 + cell_height * 0.52),
                    _rgba(INK), align="left", clipped=name_clipped)
        if role:
            role_lines, role_font, role_clipped = _fit(
                draw, role, "body", cell_width, cell_height * 0.40, role_size, 18, 1)
            _draw_block(image, role_lines, role_font,
                        (x0, y0 + cell_height * 0.54, x0 + cell_width, y0 + cell_height),
                        _rgba(_lerp(INK, COPPER, 0.45)), align="left", clipped=role_clipped)
    return image


def _timeline_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    lower = scene.get("layout") == "lower_third"
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0)) if lower else _paper((width, height))
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    if lower:
        box = (margin, int(height * 0.645), width - margin, int(height * 0.765))
    else:
        box = (margin, int(height * 0.32), width - margin, int(height * 0.68))
    image = _panel(image, box)
    draw = ImageDraw.Draw(image)
    nodes = scene.get("nodes") or []
    if not nodes:
        return image
    nodes = nodes[:4]
    x0, y0, x1, y1 = box
    pad = 62
    line_y = y0 + (y1 - y0) * 0.56
    draw.line([(x0 + pad, line_y), (x1 - pad, line_y)], fill=_rgba(COPPER, 220), width=3)
    step = (x1 - x0 - pad * 2) / max(1, len(nodes) - 1)
    label_width = min(max(90, step - 12), x1 - x0 - 20)
    for index, node in enumerate(nodes):
        cx = x0 + pad + step * index
        draw.ellipse((cx - 7, line_y - 7, cx + 7, line_y + 7), fill=_rgba(VERMILION, 240))
        label = str(node.get("label") or "")
        detail = str(node.get("detail") or "")
        left = max(x0 + 8, cx - label_width / 2)
        right = min(x1 - 8, cx + label_width / 2)
        label_lines, label_font, _ = _fit(draw, label, "body", right - left,
                                          (line_y - y0) * 0.70, 30 if aspect == "9:16" else 26, 20, 2)
        _draw_block(image, label_lines, label_font,
                    (left, y0 + 8, right, line_y - 12), _rgba(INK))
        if detail:
            detail_lines, detail_font, _ = _fit(draw, detail, "body", right - left,
                                               (y1 - line_y) * 0.72, 24 if aspect == "9:16" else 21, 18, 2)
            _draw_block(image, detail_lines, detail_font,
                        (left, line_y + 12, right, y1 - 6), _rgba(_lerp(INK, COPPER, 0.5)))
    return image


def _end_card(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    meta = loaded["meta"]
    image = _ink((width, height))
    draw = ImageDraw.Draw(image)
    margin = int(width * (0.075 if aspect == "9:16" else 0.06))
    _top_labels(draw, scene, meta, aspect, on_ink=True)

    draw.line([(margin, height * 0.145), (width - margin, height * 0.145)],
              fill=_rgba(VERMILION, 210), width=3)

    title = str(scene.get("title") or "下期见")
    lines, font, clipped = _fit(draw, title, "title", width - margin * 2, height * 0.22,
                                int(width * 0.10) if aspect == "9:16" else int(height * 0.10), 44, 2)
    _draw_block(image, lines, font, (margin, height * 0.26, width - margin, height * 0.48),
                _rgba(PAPER), clipped=clipped)

    line = str(scene.get("line") or "")
    lines2, font2, clipped2 = _fit(draw, line, "body", width - margin * 2, height * 0.16,
                                   46 if aspect == "9:16" else 38, 28, 2)
    _draw_block(image, lines2, font2, (margin, height * 0.52, width - margin, height * 0.68),
                _rgba(GREY_PAPER), clipped=clipped2)

    brand = str(meta.get("brand") or "")
    if "{{" not in brand:
        _small_text(draw, brand, (width / 2, height * 0.79), 30, _rgba(COPPER, 230), anchor="ma")
    column = str(scene.get("column") or meta.get("column") or "")
    image = _fold(image, aspect)
    image = _stamp(image, column[:1] or None)
    return image


def _background(aspect: str) -> Image.Image:
    width, height = SIZES[aspect]
    image = _paper((width, height))
    image = _fold(image, aspect)
    return image


def _dispatch(scene: dict, loaded: dict, aspect: str) -> Image.Image:
    scene_type = scene.get("type")
    if scene_type == "title_card":
        return _title_card(scene, loaded, aspect)
    if scene_type == "book_card":
        return _book_card(scene, loaded, aspect)
    if scene_type == "section_card":
        return _section_card(scene, loaded, aspect)
    if scene_type == "quote_card":
        return _quote_card(scene, loaded, aspect)
    if scene_type == "character_card":
        return _character_card(scene, loaded, aspect)
    if scene_type == "timeline_card":
        return _timeline_card(scene, loaded, aspect)
    if scene_type == "end_card":
        return _end_card(scene, loaded, aspect)
    return _background(aspect)


def _content_hash(scene: dict, loaded: dict, aspect: str) -> str:
    meta = loaded["meta"]
    payload = {
        "template": TEMPLATE_VERSION,
        "aspect": aspect,
        "scene": scene,
        "brand": meta.get("brand"),
        "column": meta.get("column"),
        "book_title": meta.get("book_title"),
        "author": meta.get("author"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def background_file(loaded: dict, aspect: str) -> Path:
    suffix = ASPECT_SUFFIX.get(aspect, "_9x16")
    return loaded["video"] / "cards" / f"bg{suffix}.png"


def composite_overlay(background: Path, card: Path, out: Path) -> Path:
    """把 lower_third 透明卡叠到品牌底上。"""
    base = Image.open(background).convert("RGBA")
    overlay = Image.open(card).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.LANCZOS)
    base.alpha_composite(overlay)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, "PNG")
    return out


def card_jobs(loaded: dict) -> list[dict]:
    """列出这一期需要生成的卡片，不渲染。"""
    plan = load_plan(loaded)
    aspects = loaded["meta"].get("aspects") or ["9:16", "16:9"]
    jobs = []
    for scene in plan.get("scenes", []):
        if not isinstance(scene, dict) or scene.get("type") not in CARD_TYPES:
            continue
        for aspect in aspects:
            suffix = ASPECT_SUFFIX.get(aspect, "_9x16")
            width, height = SIZES.get(aspect, SIZES["9:16"])
            jobs.append({
                "scene_id": scene.get("id"),
                "type": scene.get("type"),
                "aspect": aspect,
                "width": width,
                "height": height,
                "path": loaded["video"] / "cards" / f"{scene.get('id')}{suffix}.png",
                "scene": scene,
            })
    return jobs


def render_cards(episode_path: str | Path, force: bool = False) -> int:
    """渲染所有卡片 PNG，返回本次生成数量。"""
    loaded = episode(episode_path)
    cards_dir = loaded["video"] / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cards_dir / ".cache.json"
    cache: dict[str, str] = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    aspects = loaded["meta"].get("aspects") or ["9:16", "16:9"]
    jobs: list[tuple[Path, str, callable]] = []
    for job in card_jobs(loaded):
        scene = job["scene"]
        jobs.append((
            job["path"],
            _content_hash(scene, loaded, job["aspect"]),
            lambda scene=scene, aspect=job["aspect"]: _dispatch(scene, loaded, aspect),
        ))
    for aspect in aspects:
        path = background_file(loaded, aspect)
        jobs.append((
            path,
            _content_hash({"type": "background"}, loaded, aspect),
            lambda aspect=aspect: _background(aspect),
        ))

    count = 0
    for path, digest, render in jobs:
        if not force and path.is_file() and cache.get(path.name) == digest:
            continue
        image = render()
        # 保留 alpha：lower_third 卡是透明底，转 RGB 会把透明区压成黑色
        image.save(path, "PNG")
        cache[path.name] = digest
        count += 1
        print(f"[cards] {path.name}")

    write_json(cache_path, cache)
    return count
