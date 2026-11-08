"""粒子叠层：灰尘 / 雪 / 火星，黑底，渲染时用 screen 混合。

不依赖外部素材，纯程序生成，重复使用。
"""

from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .config import ASPECT_SUFFIX, FPS, SIZES, require_ffmpeg

STYLES = {"dust", "snow", "embers"}
DURATION = 10.0
SEED = {"dust": 11, "snow": 23, "embers": 37}


def _particles(style: str, width: int, height: int) -> list[dict]:
    rng = random.Random(SEED[style] + width)
    count = {"dust": 90, "snow": 130, "embers": 55}[style]
    particles = []
    for _ in range(count):
        if style == "dust":
            radius = rng.uniform(0.5, 1.8)
            vx, vy = rng.uniform(-2.0, 2.0), rng.uniform(-2.5, 1.0)
            alpha = rng.randint(18, 70)
            color = (235, 231, 220) if rng.random() > 0.2 else (255, 235, 200)
        elif style == "snow":
            radius = rng.uniform(0.8, 2.6)
            vx, vy = rng.uniform(-3.0, 3.0), rng.uniform(9.0, 22.0)
            alpha = rng.randint(70, 160)
            color = (245, 248, 255)
        else:  # embers
            radius = rng.uniform(0.7, 2.0)
            vx, vy = rng.uniform(-2.0, 2.0), rng.uniform(-12.0, -4.0)
            alpha = rng.randint(50, 150)
            color = (255, 120, 40)
        particles.append({
            "x": rng.uniform(0, width), "y": rng.uniform(0, height),
            "r": radius, "vx": vx, "vy": vy, "alpha": alpha,
            "color": color, "phase": rng.uniform(0, math.tau), "sway": rng.uniform(0.5, 2.0),
        })
    return particles


def generate_overlay(episode_path: str | Path, style: str, aspect: str, force: bool = False) -> Path | None:
    if style == "none":
        return None
    if style not in STYLES:
        raise ValueError(f"未知粒子样式：{style}")
    from .config import episode

    loaded = episode(episode_path)
    width, height = SIZES[aspect]
    half = (max(2, width // 2), max(2, height // 2))
    suffix = ASPECT_SUFFIX[aspect]
    out = loaded["video"] / "overlays" / f"{style}{suffix}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file() and not force:
        return out

    ffmpeg = require_ffmpeg()
    frames = int(DURATION * FPS)
    particles = _particles(style, *half)
    command = [
        ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{half[0]}x{half[1]}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", str(out),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame_index in range(frames):
            image = Image.new("RGB", half, (0, 0, 0))
            draw = ImageDraw.Draw(image)
            for particle in particles:
                particle["x"] += particle["vx"] / FPS
                particle["y"] += particle["vy"] / FPS
                sway = math.sin(particle["phase"] + frame_index / FPS * particle["sway"]) * 0.25
                x = (particle["x"] + sway) % half[0]
                y = particle["y"] % half[1]
                radius = particle["r"]
                alpha = particle["alpha"]
                if style == "embers":
                    alpha = int(alpha * (0.65 + 0.35 * math.sin(particle["phase"] + frame_index / 5)))
                color = tuple(int(channel * max(0, alpha) / 255) for channel in particle["color"])
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
            image = image.filter(ImageFilter.GaussianBlur(0.35))
            process.stdin.write(image.tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        if process.wait() != 0:
            raise RuntimeError(f"粒子叠层生成失败：\n{stderr[-2000:]}")
    finally:
        if process.poll() is None:
            process.kill()
    return out
