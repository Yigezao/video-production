"""质检：时长、黑帧、静音、音频一致性、分辨率、字幕安全区。

输出 video/qc_report.json。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .config import (
    ASPECT_SUFFIX,
    SIZES,
    episode,
    probe_duration,
    require_ffmpeg,
    write_json,
)

SUBTITLE_BAND = {
    "9:16": (80, 1530, 1000, 1660),
    "16:9": (120, 850, 1800, 960),
}


def _ffmpeg_text(args: list[str]) -> str:
    ffmpeg = require_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-hide_banner"] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200,
    )
    return (result.stdout or "") + (result.stderr or "")


def _item(name: str, level: str, summary: str, issues: list[dict] | None = None) -> dict:
    return {"name": name, "level": level, "summary": summary, "issues": issues or []}


def _problem(message: str, level: str = "warn", detail: str = "") -> dict:
    return {"level": level, "message": message, "detail": str(detail)[:300]}


def _probe_info(path: Path) -> dict:
    text = _ffmpeg_text(["-i", str(path)])
    info = {"duration": 0.0, "width": 0, "height": 0, "audio_hz": 0, "has_audio": False}
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        hours, minutes, seconds = match.groups()
        info["duration"] = round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if match:
        info["width"], info["height"] = int(match.group(1)), int(match.group(2))
    match = re.search(r"Audio:.*?(\d+)\s*Hz", text)
    if match:
        info["audio_hz"] = int(match.group(1))
        info["has_audio"] = True
    return info


def _mean_volume(path: Path) -> float | None:
    text = _ffmpeg_text(["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"])
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
    return float(match.group(1)) if match else None


def _black_segments(path: Path) -> list[tuple[float, float]]:
    text = _ffmpeg_text(["-i", str(path), "-an", "-vf", "blackdetect=d=0.5:pix_th=0.10", "-f", "null", "-"])
    result = []
    for match in re.finditer(r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)", text):
        result.append((float(match.group(1)), float(match.group(2))))
    return result


def _silences(path: Path) -> list[tuple[float, float]]:
    text = _ffmpeg_text(["-i", str(path), "-vn", "-af", "silencedetect=noise=-50dB:d=1", "-f", "null", "-"])
    starts = [float(value) for value in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*(\d+(?:\.\d+)?)", text)]
    result = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else start + 1.0
        result.append((start, end))
    return result


def _frame_brightness(video: Path, seconds: float, out: Path) -> float | None:
    text = _ffmpeg_text(["-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", str(video),
                         "-frames:v", "1", "-q:v", "2", str(out)])
    if not out.is_file():
        return None
    try:
        with Image.open(out) as image:
            return float(ImageStat.Stat(image.convert("L")).mean[0])
    except Exception:  # noqa: BLE001
        return None


def _ass_events(path: Path) -> list[tuple[float, float]]:
    if not path.is_file():
        return []

    def seconds(value: str) -> float:
        hours, minutes, rest = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)

    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"Dialogue:\s*\d+,([\d:.]+),([\d:.]+),", line)
        if match:
            events.append((seconds(match.group(1)), seconds(match.group(2))))
    return events


def _subtitle_changed_pixels(with_subtitle: Path, without_subtitle: Path, aspect: str) -> int | None:
    try:
        with Image.open(with_subtitle) as first, Image.open(without_subtitle) as second:
            x0, y0, x1, y1 = SUBTITLE_BAND[aspect]
            left = first.convert("L").crop((x0, y0, x1, y1))
            right = second.convert("L").crop((x0, y0, x1, y1))
            diff = ImageChops.difference(left, right)
            histogram = diff.histogram()
            return sum(histogram[26:])
    except Exception:  # noqa: BLE001
        return None


def _subtitle_reference(
    events: list[tuple[float, float]], duration: float
) -> tuple[tuple[float, float], float] | None:
    """找一条字幕和附近一个无字幕时刻，用于判断字幕是否烧进画面。"""
    ordered = sorted(events)
    for index, event in enumerate(ordered):
        next_start = ordered[index + 1][0] if index + 1 < len(ordered) else duration
        gap = next_start - event[1]
        if gap > 0.2 and event[1] - event[0] >= 0.5:
            return event, event[1] + min(0.15, gap / 2)
    for event in ordered:
        if event[0] > 0.25 and event[1] - event[0] >= 0.5:
            return event, max(0.05, event[0] - 0.15)
    if ordered:
        event = ordered[-1]
        if duration - event[1] > 0.2 and event[1] - event[0] >= 0.5:
            return event, event[1] + 0.15
    return None


def _check_aspect(episode_path: Path, loaded: dict, aspect: str, temp: Path) -> list[dict]:
    video_dir = loaded["video"]
    suffix = ASPECT_SUFFIX[aspect]
    tag = aspect.replace(":", "x")
    burn_subtitles = str(loaded["meta"].get("subtitle_mode") or "burn") != "none"
    out = video_dir / "out" / f"video{suffix}.mp4"
    ass = video_dir / "subs" / f"subtitles{suffix}.ass"
    checks: list[dict] = []

    if not out.is_file():
        return [_item(f"{aspect} 成片", "fail", f"缺少 {out}")]

    info = _probe_info(out)
    source_duration = probe_duration(loaded["audio"]) if loaded.get("audio") else 0
    duration = info["duration"] or probe_duration(out)
    delta = duration - source_duration if source_duration else 0
    level = "pass"
    if source_duration and abs(delta) > 0.5:
        level = "fail"
    elif source_duration and abs(delta) > 0.2:
        level = "warn"
    checks.append(_item(f"{aspect} 时长", level,
                        f"成片 {duration:.3f}s，音频 {source_duration:.3f}s，差 {delta:+.3f}s"))

    expected = SIZES[aspect]
    resolution_ok = (info["width"], info["height"]) == expected
    checks.append(_item(f"{aspect} 分辨率", "pass" if resolution_ok else "fail",
                        f"{info['width']}x{info['height']}（应为 {expected[0]}x{expected[1]}）"))

    audio_ok = info["has_audio"] and info["audio_hz"] == 48000
    checks.append(_item(f"{aspect} 音频流", "pass" if audio_ok else "fail",
                        f"{info['audio_hz']}Hz" if info["has_audio"] else "没有音频流"))

    blacks = _black_segments(out)
    black_issues = [_problem(f"黑帧 {start:.2f}–{end:.2f}s", "fail" if end - start > 1.0 else "warn")
                    for start, end in blacks]
    checks.append(_item(f"{aspect} 黑帧", "pass" if not black_issues else
                        ("fail" if any(item["level"] == "fail" for item in black_issues) else "warn"),
                        "没有黑帧" if not black_issues else f"{len(black_issues)} 段黑帧", black_issues))

    silences = _silences(out)
    silence_issues = []
    for start, end in silences:
        if duration and start > duration - 1.5 and end >= duration - 0.8:
            silence_issues.append(_problem(f"结尾静音 {start:.2f}–{end:.2f}s", "warn"))
    checks.append(_item(f"{aspect} 静音尾巴", "pass" if not silence_issues else "warn",
                        "没有结尾静音" if not silence_issues else f"{len(silence_issues)} 段", silence_issues))

    if loaded.get("audio") is not None:
        source_mean = _mean_volume(loaded["audio"])
        output_mean = _mean_volume(out)
        if source_mean is not None and output_mean is not None:
            change = output_mean - source_mean
            level = "pass"
            if abs(change) > 3:
                level = "fail"
            elif abs(change) > 1.5:
                level = "warn"
            checks.append(_item(f"{aspect} 音频响度", level,
                                f"原 {source_mean:.1f} dB，成片 {output_mean:.1f} dB，差 {change:+.1f} dB"))

    first = _frame_brightness(out, 0.1, temp / f"{tag}_first.png")
    last = _frame_brightness(out, max(0.0, duration - 0.3), temp / f"{tag}_last.png")
    brightness_issues = []
    for label, value in (("首帧", first), ("尾帧", last)):
        if value is not None and value < 12:
            brightness_issues.append(_problem(f"{label}亮度 {value:.1f}，疑似黑屏", "warn"))
    checks.append(_item(f"{aspect} 首尾画面", "pass" if not brightness_issues else "warn",
                        f"首帧 {first:.1f} / 尾帧 {last:.1f}" if first is not None and last is not None
                        else "读不到首尾帧", brightness_issues))

    events = _ass_events(ass)
    if burn_subtitles:
        checks.append(_item(f"{aspect} 字幕脚本", "pass" if events else "fail",
                            f"{len(events)} 条 ASS 字幕" if events else "ASS 没有字幕事件"))
        if events:
            # 用「有字幕帧」和「无字幕帧」在同一条字幕带上的差异判断是否烧录成功
            reference = _subtitle_reference(events, duration)
            if reference is None:
                checks.append(_item(f"{aspect} 字幕烧录", "pass", "找不到无字幕参照帧，跳过程序判断"))
            else:
                sample, gap = reference
                mid = (sample[0] + sample[1]) / 2
                with_frame = temp / f"{tag}_sub_on.png"
                without_frame = temp / f"{tag}_sub_off.png"
                _ffmpeg_text(["-y", "-ss", f"{mid:.3f}", "-i", str(out), "-frames:v", "1", "-q:v", "2", str(with_frame)])
                _ffmpeg_text(["-y", "-ss", f"{gap:.3f}", "-i", str(out), "-frames:v", "1", "-q:v", "2", str(without_frame)])
                changed = _subtitle_changed_pixels(with_frame, without_frame, aspect)
                if changed is None:
                    checks.append(_item(f"{aspect} 字幕烧录", "warn", "字幕带对比失败，建议人工看一眼"))
                else:
                    level = "pass" if changed > 150 else "warn"
                    checks.append(_item(f"{aspect} 字幕烧录", level,
                                        f"字幕带差异像素 {changed}（>150 视为有字幕）" if changed > 150
                                        else f"字幕带差异像素只有 {changed}，可能没烧上"))
    else:
        srt_ok = (video_dir / "out" / "subtitles.srt").is_file()
        checks.append(_item(f"{aspect} 字幕", "pass" if srt_ok else "warn",
                            "按设置未烧字幕；外挂 SRT 已导出" if srt_ok else "未烧字幕，但外挂 SRT 也缺"))

    if not (video_dir / "out" / f"thumb{suffix}.png").is_file():
        checks.append(_item(f"{aspect} 缩略图", "warn", "缺缩略图"))
    else:
        checks.append(_item(f"{aspect} 缩略图", "pass", "OK"))

    return checks


def run_qc(episode_path: str | Path) -> dict:
    loaded = episode(episode_path)
    video_dir = loaded["video"]
    temp = video_dir / "qc_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    aspects = loaded["meta"].get("aspects") or ["9:16", "16:9"]
    checks: list[dict] = []
    for aspect in aspects:
        try:
            checks.extend(_check_aspect(loaded["dir"], loaded, aspect, temp))
        except Exception as exc:  # noqa: BLE001
            checks.append(_item(f"{aspect} 质检", "fail", f"检查出错：{exc}"))
    if not (video_dir / "render_manifest.json").is_file():
        checks.append(_item("渲染清单", "warn", "缺 render_manifest.json"))
    else:
        checks.append(_item("渲染清单", "pass", "OK"))

    fails = sum(1 for check in checks if check["level"] == "fail")
    warns = sum(1 for check in checks if check["level"] == "warn")
    ok = fails == 0
    report = {
        "episode": loaded["meta"].get("episode") or loaded["dir"].name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "summary": f"{len(checks)} 项：{fails} fail，{warns} warn",
        "checks": checks,
    }
    write_json(video_dir / "qc_report.json", report)
    shutil.rmtree(temp, ignore_errors=True)
    return report
