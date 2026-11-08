"""视频封面：大字书名 + 钩子 + 作者；文字全部程序绘制。

9:16 给抖音/视频号，16:9 给 B 站。背景优先用该期第一张插画，
没有就用纸底；AI 图里不要带文字。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .cards import (
    COPPER,
    INK,
    PAPER,
    VERMILION,
    WHITE,
    _draw_block,
    _fit,
    _font,
    _lerp,
    _paper,
    _rgba,
    _small_text,
)
from .config import ASPECT_SUFFIX, SIZES, resolve_image


def _background(loaded: dict, plan: dict, aspect: str) -> tuple[Image.Image, bool]:
    """返回 (背景图, 是否有照片)。"""
    width, height = SIZES[aspect]
    cover = plan.get("cover") if isinstance(plan.get("cover"), dict) else {}
    image = str(cover.get("image") or "").strip()
    if not image:
        for scene in plan.get("scenes", []):
            if isinstance(scene, dict) and scene.get("type") == "illustration" and scene.get("image"):
                image = str(scene["image"])
                break
    if image:
        path = resolve_image(loaded, image)
        if path.is_file():
            return ImageOps.fit(Image.open(path).convert("RGB"), (width, height),
                                method=Image.LANCZOS, centering=(0.5, 0.5)), True
    return _paper((width, height)), False


def _darken(image: Image.Image) -> Image.Image:
    """照片背景压暗：上下更暗，中间稍亮，保证白字可读。"""
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        t = y / max(1, height - 1)
        # 中间 0.25，上下 0.62
        alpha = int(150 - 90 * (1 - abs(t - 0.5) * 2) ** 1.4)
        draw.line([(0, y), (width, y)], fill=(10, 12, 16, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def render_cover(loaded: dict, plan: dict, aspect: str, out: Path) -> Path:
    width, height = SIZES[aspect]
    cover = plan.get("cover") if isinstance(plan.get("cover"), dict) else {}
    meta = loaded["meta"]
    title = str(cover.get("title") or f"《{meta.get('book_title') or ''}》")
    line = str(cover.get("line") or "").strip()
    author = str(cover.get("author") or meta.get("author") or "未标注")
    column = str(cover.get("column") or meta.get("column") or "")
    brand = str(meta.get("brand") or "")

    background, has_photo = _background(loaded, plan, aspect)
    image = _darken(background) if has_photo else background.convert("RGB")
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image)
    ink = WHITE if has_photo else INK
    paper = PAPER
    margin = int(width * (0.075 if aspect == "9:16" else 0.065))

    # 顶部栏目/账号
    top_size = 30 if aspect == "9:16" else 28
    if column:
        _small_text(draw, column, (margin, int(height * 0.065)), top_size,
                    _rgba(paper if has_photo else COPPER, 235))
    if brand and "{{" not in brand:
        _small_text(draw, brand, (width - margin, int(height * 0.065)), top_size,
                    _rgba(paper if has_photo else COPPER, 235), anchor="ra")

    # 朱砂短线
    line_y = int(height * (0.235 if aspect == "9:16" else 0.22))
    draw.line([(margin, line_y), (margin + int(width * 0.12), line_y)],
              fill=_rgba(VERMILION, 240), width=6)

    # 大字书名
    title_top = int(height * (0.25 if aspect == "9:16" else 0.24))
    title_bottom = int(height * (0.54 if aspect == "9:16" else 0.52))
    max_title = int(width * 0.17) if aspect == "9:16" else int(height * 0.14)
    title_lines, title_font, clipped = _fit(
        draw, title, "title", width - margin * 2, title_bottom - title_top,
        max(60, max_title), 42, 2)
    _draw_block(image, title_lines, title_font,
                (margin, title_top, width - margin, title_bottom), _rgba(ink), clipped=clipped)
    draw = ImageDraw.Draw(image)

    # 钩子
    if line:
        hook_top = int(height * (0.57 if aspect == "9:16" else 0.55))
        hook_bottom = int(height * (0.70 if aspect == "9:16" else 0.67))
        hook_lines, hook_font, hook_clipped = _fit(
            draw, line, "body", width - margin * 2, hook_bottom - hook_top,
            56 if aspect == "9:16" else 46, 28, 2)
        _draw_block(image, hook_lines, hook_font,
                    (margin, hook_top, width - margin, hook_bottom),
                    _rgba(paper if has_photo else VERMILION), clipped=hook_clipped)
        draw = ImageDraw.Draw(image)

    # 作者
    author_y = int(height * (0.78 if aspect == "9:16" else 0.78))
    _small_text(draw, f"《{meta.get('book_title') or ''}》 · {author}",
                (width / 2, author_y), 34 if aspect == "9:16" else 30,
                _rgba(paper if has_photo else COPPER, 245), anchor="ma")

    # 底部安全区只用一条细线，不放字
    bottom_line = int(height * (0.84 if aspect == "9:16" else 0.86))
    draw.line([(margin, bottom_line), (width - margin, bottom_line)],
              fill=_rgba(paper if has_photo else _lerp(INK, COPPER, 0.5), 90), width=2)

    out.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out, "PNG")
    return out


def render_covers(loaded: dict, plan: dict, aspects: list[str] | None = None) -> dict[str, Path]:
    results = {}
    for aspect in aspects or loaded["meta"].get("aspects") or ["9:16", "16:9"]:
        suffix = ASPECT_SUFFIX[aspect]
        out = loaded["video"] / "out" / f"cover{suffix}.png"
        render_cover(loaded, plan, aspect, out)
        thumb = loaded["video"] / "out" / f"thumb{suffix}.png"
        thumb.write_bytes(out.read_bytes())
        results[aspect] = out
    return results
