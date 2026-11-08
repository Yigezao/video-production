"""渲染引擎共用配置：路径、比例、字体、FFmpeg。

实现者只改这里和 cards.py / render.py / qc.py，不改 tools/。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.common import (  # noqa: E402
    find_ffmpeg,
    find_ffprobe,
    load_episode,
    probe_duration,
    read_json,
    read_text,
    write_json,
)

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
ASPECT_SUFFIX = {"9:16": "_9x16", "16:9": "_16x9"}
FPS = 30
CRF = 22
PRESET = "veryfast"

# 02-画面与字幕规范
COLORS = {
    "ink": "#17181C",
    "paper": "#F5EFE3",
    "vermilion": "#C84630",
    "copper": "#B08A57",
    "grey_paper": "#D8CDBC",
    "white": "#FFFFFF",
}
ASS = {
    # 比旧版 52/46 放大；手机上看 16:9 尤其需要大一点
    "9:16": {"play_res": (1080, 1920), "font_size": 64, "margin_v": 260, "margin_lr": 80,
             "max_chars": 14, "outline": 3},
    "16:9": {"play_res": (1920, 1080), "font_size": 64, "margin_v": 120, "margin_lr": 120,
             "max_chars": 20, "outline": 3},
}
MOTION_ZOOM = (1.00, 1.04)
TRANSITION_SECONDS = 0.3


def episode_dir(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"期目录不存在：{path}")
    if not (path / "meta.json").is_file():
        raise FileNotFoundError(f"期目录缺少 meta.json：{path}")
    return path


def episode(episode_path: str | Path) -> dict:
    path = episode_dir(episode_path)
    loaded = load_episode(path)
    loaded["video"] = path / "video"
    loaded["video"].mkdir(parents=True, exist_ok=True)
    return loaded


def load_plan(loaded: dict) -> dict:
    path = loaded["video"] / "video_plan.json"
    if not path.is_file():
        raise FileNotFoundError(f"缺少 video_plan.json：{path}（先做 Step 2 视觉导演）")
    return read_json(path)


def resolve_image(loaded: dict, image: str | Path) -> Path:
    """图片优先找 video/，再找期目录，再找项目根（series/ 复用图）。"""
    path = Path(image)
    if path.is_absolute():
        return path
    candidates = [loaded["video"] / path, loaded["dir"] / path, ROOT / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_sentences(loaded: dict) -> dict:
    path = loaded["video"] / "sentences.json"
    if not path.is_file():
        raise FileNotFoundError(f"缺少 sentences.json：{path}（先跑 tools/prepare.py）")
    return read_json(path)


def require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "找不到 FFmpeg。装 FFmpeg，或在 Video_Production/config.json 写 "
            '{"ffmpeg": "D:/ffmpeg/bin/ffmpeg.exe"}。'
        )
    return ffmpeg


def font_path(role: str = "body") -> Path:
    """role = body（思源黑体）| title（思源宋体）。"""
    names = (
        ["NotoSansSC-Medium.otf", "NotoSansSC-VF.ttf", "msyh.ttc", "simhei.ttf"]
        if role == "body"
        else ["NotoSerifSC-SemiBold.otf", "NotoSerifSC-VF.ttf", "simsun.ttc"]
    )
    for name in names:
        for base in (ROOT / "fonts", Path(r"C:\Windows\Fonts")):
            candidate = base / name
            if candidate.is_file():
                return candidate
    raise FileNotFoundError("找不到中文字体；把 Noto Sans/Serif SC 放进 Video_Production/fonts/")


__all__ = [
    "ROOT", "SIZES", "ASPECT_SUFFIX", "FPS", "CRF", "PRESET", "COLORS", "ASS",
    "MOTION_ZOOM", "TRANSITION_SECONDS", "episode_dir", "episode", "load_plan",
    "load_sentences", "require_ffmpeg", "font_path", "resolve_image", "find_ffprobe", "probe_duration",
    "read_json", "read_text", "write_json",
]
