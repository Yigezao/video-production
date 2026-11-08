"""共用小工具：编码、读文件、找 ffmpeg、探测时长、定位一期文件。

只做代码能可靠完成的事，不调用模型。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "episodes"
AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus")
SKIP_TXT = ("readme", "说明", "meta", "publish", "image_prompts", "requirements")


def decode_bytes(data: bytes) -> tuple[str, str]:
    """尽量按 UTF-8 / GB18030 / UTF-16 解码，返回 (文本, 编码名)。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if encoding == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            continue
        if text.count("\ufffd") > 3:
            continue
        return text, encoding
    return data.decode("gb18030", errors="replace"), "gb18030(有替换字符)"


def read_text(path: Path) -> tuple[str, str]:
    text, encoding = decode_bytes(path.read_bytes())
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding


def read_json(path: Path) -> dict:
    text, _ = read_text(path)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return json.loads(text)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _known_ffmpeg() -> list[Path]:
    return [
        Path(r"D:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"D:\my_Software\ffmpeg\bin\ffmpeg.exe"),
    ]


def _config_value(key: str) -> str:
    config = ROOT / "config.json"
    if config.is_file():
        try:
            return str(read_json(config).get(key) or "")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def find_ffmpeg() -> str:
    import os

    for value in (os.environ.get("FFMPEG", ""), _config_value("ffmpeg"), shutil.which("ffmpeg") or ""):
        if value and Path(value).is_file():
            return str(Path(value))
    for path in _known_ffmpeg():
        if path.is_file():
            return str(path)
    return ""


def find_ffprobe() -> str:
    import os

    for value in (os.environ.get("FFPROBE", ""), _config_value("ffprobe"), shutil.which("ffprobe") or ""):
        if value and Path(value).is_file():
            return str(Path(value))
    if shutil.which("ffprobe"):
        return shutil.which("ffprobe") or ""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        candidate = Path(ffmpeg).with_name("ffprobe.exe")
        if candidate.is_file():
            return str(candidate)
    return ""


def probe_duration(path: Path) -> float:
    """返回秒数；WAV 用标准库，其他格式用 ffprobe / ffmpeg -i。"""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                rate = handle.getframerate()
                if rate:
                    return round(handle.getnframes() / rate, 3)
        except (wave.Error, EOFError, OSError):
            pass
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            output = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            value = output.stdout.strip().splitlines()[-1] if output.stdout.strip() else ""
            if value:
                return round(float(value), 3)
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        try:
            output = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output.stderr)
            if match:
                hours, minutes, seconds = match.groups()
                return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)
        except (subprocess.SubprocessError, OSError):
            pass
    return 0.0


def find_by_meta(episode: Path, meta: dict, key: str, fallback: str, extensions: tuple[str, ...]) -> Path | None:
    named = str(meta.get(key) or "").strip()
    if named:
        candidate = (episode / named).resolve()
        if candidate.is_file():
            return candidate
    candidate = episode / fallback
    if candidate.is_file():
        return candidate
    for item in sorted(episode.glob("*")):
        if item.is_file() and item.suffix.lower() in extensions:
            return item
    return None


def find_audio(episode: Path, meta: dict) -> Path | None:
    return find_by_meta(episode, meta, "audio_file", "audio.wav", AUDIO_EXTS)


def find_srt(episode: Path, meta: dict) -> Path | None:
    return find_by_meta(episode, meta, "srt_file", "subtitles.srt", (".srt",))


def find_script(episode: Path, meta: dict) -> Path | None:
    named = str(meta.get("final_file") or "").strip()
    if named and (episode / named).is_file():
        return episode / named
    for name in ("final.txt", "script.txt", "口播稿.txt"):
        candidate = episode / name
        if candidate.is_file():
            return candidate
    for item in sorted(episode.glob("*.txt")):
        if any(word in item.name.lower() for word in SKIP_TXT):
            continue
        return item
    return None


def load_episode(episode: Path) -> dict:
    meta = read_json(episode / "meta.json") if (episode / "meta.json").is_file() else {}
    return {
        "dir": episode,
        "meta": meta,
        "audio": find_audio(episode, meta),
        "srt": find_srt(episode, meta),
        "script": find_script(episode, meta),
    }


def norm(text: str) -> str:
    """对齐用：去空白、去标点、全半角统一、转小写。"""
    import unicodedata

    out = []
    for char in unicodedata.normalize("NFKC", text or ""):
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "S")):
            continue
        out.append(char.lower())
    return "".join(out)


def fmt_sec(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" ._")
    return name or "episode"


def unique_dir(parent: Path, name: str) -> Path:
    target = parent / name
    index = 2
    while target.exists():
        target = parent / f"{name}-{index}"
        index += 1
    return target
