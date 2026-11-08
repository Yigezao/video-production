"""渲染：分段 MP4 → 拼接 → ASS 字幕 → 音频。

铁律：音频不动；视频服从音频；不用 -shortest 兜底。
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from datetime import datetime
from pathlib import Path

from .cards import (
    CARD_TYPES,
    background_file,
    composite_overlay,
    render_cards,
)
from .cover import render_covers
from .overlays import generate_overlay
from .config import (
    ASPECT_SUFFIX,
    CRF,
    FPS,
    PRESET,
    SIZES,
    ASS,
    COLORS,
    episode,
    font_path,
    load_plan,
    load_sentences,
    probe_duration,
    resolve_image,
    require_ffmpeg,
    write_json,
)

MOTIONS = {"fade", "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right", "none"}
TEMPLATE_VERSION = "0.2.0"

_COMMANDS: list[str] = []


# ---------------------------- 进程 ----------------------------


def _run(args: list[str], cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    _COMMANDS.append(" ".join(shlex.quote(str(item)) for item in args))
    result = subprocess.run(
        [str(item) for item in args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg 失败：\n" + " ".join(str(item) for item in args) + "\n\n"
            + (result.stderr or "")[-3000:]
        )
    return result


# ---------------------------- 时间轴 ----------------------------


def _scene_spans(plan: dict, sentences: list[dict], audio_duration: float) -> list[dict]:
    index = {sentence["id"]: position for position, sentence in enumerate(sentences)}
    spans: list[dict] = []
    for scene in plan.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        start_id = str(scene.get("from") or "")
        end_id = str(scene.get("to") or "")
        if start_id not in index or end_id not in index:
            raise ValueError(f"场景 {scene.get('id')} 的 from/to 不在 sentences.json 里")
        start = float(sentences[index[start_id]]["start"])
        end = float(sentences[index[end_id]]["end"])
        if end <= start:
            raise ValueError(f"场景 {scene.get('id')} 时长为 0")
        spans.append({"scene": scene, "start": round(start, 3), "end": round(end, 3)})
    if not spans:
        raise ValueError("video_plan.json 没有可用场景")

    def filler(scene_id: str, motion: str, image_of: dict) -> dict:
        """补头尾时优先延续插画，避免出现空纸底。"""
        image = image_of.get("image") if image_of.get("type") == "illustration" else None
        scene = {"id": scene_id, "type": "illustration" if image else "background",
                 "hold_seconds": 0, "motion": motion, "layout": "full"}
        if image:
            scene["image"] = image
        return scene

    if spans[0]["start"] > 0.02:
        spans.insert(0, {
            "scene": filler("LEAD", "slow_zoom_in", spans[0]["scene"]),
            "start": 0.0,
            "end": spans[0]["start"],
        })
    if spans[-1]["end"] < audio_duration - 0.02:
        spans.append({
            "scene": filler("TAIL", "slow_zoom_in", spans[-1]["scene"]),
            "start": spans[-1]["end"],
            "end": round(audio_duration + 0.3, 3),
        })
    return spans


def _preview_spans(full: list[dict], preview: int, audio_duration: float) -> list[dict]:
    if audio_duration <= preview + 0.5:
        return full
    head: list[dict] = []
    for span in full:
        if span["start"] >= preview:
            break
        if span["end"] <= preview + 0.01:
            head.append(span)
        else:
            clipped = dict(span)
            clipped["end"] = float(preview)
            head.append(clipped)
            break
    tail = next((span for span in reversed(full) if span["scene"].get("id") != "TAIL"), full[-1])
    candidates = [
        span for span in full
        if span["start"] >= preview - 0.01 and span is not tail and span["scene"].get("id") != "TAIL"
    ]
    preferred = [
        span for span in candidates
        if span["scene"].get("type") in ("section_card", "quote_card", "character_card", "timeline_card")
    ]
    if preferred:
        middle = preferred[0]
    elif candidates:
        middle = min(candidates, key=lambda span: abs((span["start"] + span["end"]) / 2 - audio_duration / 2))
    else:
        middle = None
    picks = head[:]
    if middle is not None:
        picks.append(middle)
    if tail not in picks and tail["start"] >= preview - 0.01:
        picks.append(tail)
    unique: dict[tuple, dict] = {}
    for span in picks:
        key = (span["start"], span["end"], span["scene"].get("id"))
        unique[key] = span
    return sorted(unique.values(), key=lambda span: span["start"])


# ---------------------------- 字幕 ----------------------------


def _split_chunks(text: str, max_chars: int) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    limit = max_chars * 2
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = limit
        for index in range(min(limit, len(remaining)) - 1, max_chars, -1):
            if remaining[index] in "，。；：！？、":
                cut = index + 1
                break
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _wrap_subtitle(text: str, max_chars: int) -> list[str]:
    text = str(text or "").strip()
    lines: list[str] = []
    while len(text) > max_chars:
        cut = max_chars
        for index in range(max_chars - 1, max(1, max_chars // 2), -1):
            if text[index] in "，。；：！？、":
                cut = index + 1
                break
        lines.append(text[:cut].strip())
        text = text[cut:].strip().lstrip("，。；：、")
    if text:
        lines.append(text)
    return lines[:2] or [""]


def _build_events(sentences: list[dict], max_chars: int) -> list[dict]:
    events: list[dict] = []
    for sentence in sentences:
        text = str(sentence.get("text") or "").strip()
        if not text:
            continue
        chunks = _split_chunks(text, max_chars)
        if not chunks:
            continue
        total = sum(len(chunk) for chunk in chunks) or 1
        start = float(sentence["start"])
        end = float(sentence["end"])
        cursor = start
        for index, chunk in enumerate(chunks):
            if index == len(chunks) - 1:
                chunk_end = end
            else:
                chunk_end = cursor + (end - start) * len(chunk) / total
            if chunk_end - cursor >= 0.15:
                events.append({
                    "start": round(cursor, 3),
                    "end": round(max(cursor + 0.3, chunk_end), 3),
                    "text": chunk,
                })
            cursor = chunk_end
    return events


def _events_for_spans(events: list[dict], spans: list[dict]) -> list[dict]:
    output: list[dict] = []
    offset = 0.0
    for span in spans:
        length = span["end"] - span["start"]
        for event in events:
            if event["end"] <= span["start"] or event["start"] >= span["end"]:
                continue
            start = max(event["start"], span["start"])
            end = min(event["end"], span["end"])
            if end - start < 0.2:
                continue
            output.append({
                "start": round(offset + start - span["start"], 3),
                "end": round(offset + end - span["start"], 3),
                "text": event["text"],
            })
        offset += length
    return output


def _ass_time(seconds: float) -> str:
    total = max(0, int(round(float(seconds) * 100)))
    hours, rest = divmod(total, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _srt_time(seconds: float) -> str:
    total = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_color(hex_value: str) -> str:
    value = hex_value.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"&H00{blue:02X}{green:02X}{red:02X}"


def _ass_font_name() -> str:
    name = font_path("body").name.lower()
    if "notosans" in name:
        return "Noto Sans SC"
    if "msyh" in name:
        return "Microsoft YaHei"
    if "simhei" in name:
        return "SimHei"
    return "Noto Sans SC"


def _write_ass(events: list[dict], aspect: str, path: Path) -> None:
    width, height = SIZES[aspect]
    style = ASS[aspect]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{_ass_font_name()},{style['font_size']},&H00FFFFFF,&H000000FF,"
        f"{_ass_color(COLORS['ink'])},&H00000000,0,0,0,0,100,100,0,0,1,{style.get('outline', 3)},0,2,"
        f"{style['margin_lr']},{style['margin_lr']},{style['margin_v']},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    max_chars = style["max_chars"]
    for event in events:
        lines_text = _wrap_subtitle(event["text"], max_chars)
        text = "\\N".join(lines_text).replace("{", "｛").replace("}", "｝")
        lines.append(
            f"Dialogue: 0,{_ass_time(event['start'])},{_ass_time(event['end'])},Default,,0,0,0,,{text}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_srt(events: list[dict], aspect: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_chars = ASS[aspect]["max_chars"]
    blocks = []
    for index, event in enumerate(events, start=1):
        text = "\n".join(_wrap_subtitle(event["text"], max_chars))
        blocks.append(f"{index}\n{_srt_time(event['start'])} --> {_srt_time(event['end'])}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def _setup_fonts(video_dir: Path) -> str:
    fonts = video_dir / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    source = font_path("body")
    target = fonts / f"subtitle{source.suffix.lower()}"
    if not target.is_file():
        target.write_bytes(source.read_bytes())
    return _ass_font_name()


# ---------------------------- 画面 ----------------------------


def _image_for(scene: dict, aspect: str, loaded: dict) -> Path:
    video_dir = loaded["video"]
    suffix = ASPECT_SUFFIX[aspect]
    scene_type = scene.get("type")
    if scene_type in CARD_TYPES:
        path = video_dir / "cards" / f"{scene.get('id')}{suffix}.png"
        if not path.is_file():
            raise FileNotFoundError(f"卡片不存在：{path}（先跑 python -m video_engine cards）")
        return path
    if scene_type == "illustration":
        image = str(scene.get("image") or "").strip()
        if image:
            path = resolve_image(loaded, image)
            if path.is_file():
                return path
    return background_file(loaded, aspect)


def _render_still(
    image: Path,
    duration: float,
    motion: str,
    out: Path,
    aspect: str,
    video_dir: Path,
) -> None:
    ffmpeg = require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, float(duration))
    frames = max(1, int(round(duration * FPS)))
    width, height = SIZES[aspect]
    motion = motion if motion in MOTIONS else "none"

    if motion in ("none", "fade"):
        filters = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,format=yuv420p"
        )
        args = [
            ffmpeg, "-y", "-loop", "1", "-i", str(image), "-t", f"{duration:.3f}",
            "-vf", filters, "-r", str(FPS), "-c:v", "libx264", "-preset", PRESET,
            "-crf", str(CRF), "-pix_fmt", "yuv420p", "-an", str(out),
        ]
        _run(args, cwd=video_dir)
        return

    # zoompan 的 x/y 是整数像素，直接在 1080p 上做慢速运动会 1px/2px 阶梯抖动。
    # 统一 4x 输入；平移最明显，再 2x 输出后 Lanczos 缩回；推拉 1x 输出即可。
    pan = motion in ("pan_left", "pan_right")
    output_scale = 2 if pan else 1
    scale_w, scale_h = width * 4, height * 4
    base = (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={scale_w}:{scale_h}"
    )
    denominator = max(1, frames - 1)
    if motion == "slow_zoom_in":
        step = (1.06 - 1.0) / frames
        z = f"min(zoom+{step:.8f},1.06)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "slow_zoom_out":
        step = (1.06 - 1.0) / denominator
        z = f"max(1.0,1.06-{step:.8f}*on)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        z = "1.08"
        x = f"(iw-iw/zoom)*(on/{denominator})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z = "1.08"
        x = f"(iw-iw/zoom)*(1-on/{denominator})"
        y = "ih/2-(ih/zoom/2)"
    else:
        z = "1.0"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    if output_scale == 2:
        tail = f",scale={width}:{height}:flags=lanczos"
    else:
        tail = ""
    filters = (
        f"{base},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:"
        f"s={width * output_scale}x{height * output_scale}:fps={FPS}"
        f"{tail},setsar=1,format=yuv420p"
    )
    args = [
        ffmpeg, "-y", "-i", str(image), "-vf", filters, "-frames:v", str(frames),
        "-r", str(FPS), "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-an", str(out),
    ]
    _run(args, cwd=video_dir)


def _concat(segments: list[Path], out: Path, video_dir: Path) -> None:
    if not segments:
        raise ValueError("没有可拼接的分段")
    ffmpeg = require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    list_path = out.with_suffix(".txt")
    lines = []
    for segment in segments:
        path = segment.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{path}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
          "-c", "copy", str(out)], cwd=video_dir)


def _render_scene(span: dict, aspect: str, loaded: dict, out: Path, temp_dir: Path) -> None:
    scene = span["scene"]
    duration = float(span["end"] - span["start"])
    video_dir = loaded["video"]
    background = background_file(loaded, aspect)

    if scene.get("type") in CARD_TYPES:
        card = _image_for(scene, aspect, loaded)
        hold = scene.get("hold_seconds")
        try:
            hold = float(hold)
        except (TypeError, ValueError):
            hold = 0.0
        if hold <= 0 or hold > duration:
            hold = duration
        hold = max(0.1, min(hold, duration))
        phase_image = card
        if scene.get("layout") == "lower_third":
            phase_image = composite_overlay(
                background, card, temp_dir / f"{scene.get('id')}_{ASPECT_SUFFIX[aspect]}_overlay.png"
            )
        if duration - hold > 0.15:
            first = temp_dir / f"{scene.get('id')}_{ASPECT_SUFFIX[aspect]}_a.mp4"
            second = temp_dir / f"{scene.get('id')}_{ASPECT_SUFFIX[aspect]}_b.mp4"
            _render_still(phase_image, hold, "none", first, aspect, video_dir)
            # 卡片到点不再切品牌纸底（会闪白），继续用卡片本身走完本段
            _render_still(phase_image, duration - hold, "slow_zoom_in", second, aspect, video_dir)
            _concat([first, second], out, video_dir)
        else:
            _render_still(phase_image, duration, "none", out, aspect, video_dir)
        return

    image = _image_for(scene, aspect, loaded)
    motion = str(scene.get("motion") or "slow_zoom_in")
    if scene.get("type") == "illustration" and motion == "fade":
        motion = "slow_zoom_in"
    _render_still(image, duration, motion, out, aspect, video_dir)


def _extract_preview_audio(spans: list[dict], audio: Path, out: Path, video_dir: Path) -> float:
    ffmpeg = require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(spans) == 1:
        span = spans[0]
        _run([ffmpeg, "-y", "-ss", f"{span['start']:.3f}", "-t", f"{span['end'] - span['start']:.3f}",
              "-i", str(audio), "-vn", "-c:a", "pcm_s16le", str(out)], cwd=video_dir)
        return float(span["end"] - span["start"])
    filters = []
    labels = []
    for index, span in enumerate(spans):
        filters.append(
            f"[0:a]atrim=start={span['start']:.3f}:end={span['end']:.3f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
        labels.append(f"[a{index}]")
    filters.append("".join(labels) + f"concat=n={len(spans)}:v=0:a=1[aout]")
    _run([ffmpeg, "-y", "-i", str(audio), "-filter_complex", ";".join(filters),
          "-map", "[aout]", "-c:a", "pcm_s16le", str(out)], cwd=video_dir)
    return sum(float(span["end"] - span["start"]) for span in spans)


def _mux(
    concat_video: Path,
    audio_input: Path,
    ass_path: Path,
    out: Path,
    duration: float,
    video_dir: Path,
    aspect: str,
    overlay: Path | None = None,
    overlay_opacity: float = 0.22,
    burn_subtitles: bool = True,
) -> None:
    ffmpeg = require_ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        ass_rel = ass_path.resolve().relative_to(video_dir.resolve()).as_posix()
    except ValueError:
        ass_rel = ass_path.resolve().as_posix()
    tail = [
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{duration:.3f}", "-movflags", "+faststart",
        str(out.resolve().as_posix()),
    ]
    if overlay is None:
        args = [
            ffmpeg, "-y",
            "-i", str(concat_video.resolve().as_posix()),
            "-i", str(audio_input.resolve().as_posix()),
        ]
        if burn_subtitles:
            args += ["-vf", f"ass={ass_rel}:fontsdir=fonts"]
        args += tail
    else:
        width, height = SIZES[aspect]
        opacity = min(1.0, max(0.0, float(overlay_opacity)))
        to_yuv = ("format=rgb24,scale=in_range=full:out_range=limited:"
                  "in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p")
        if burn_subtitles:
            tail_filter = f"[bl]{to_yuv},ass={ass_rel}:fontsdir=fonts[vout]"
        else:
            tail_filter = f"[bl]{to_yuv}[vout]"
        filter_complex = (
            f"[2:v]scale={width}:{height}:flags=lanczos,format=rgb24[ov];"
            f"[0:v]format=rgb24[base];"
            f"[base][ov]blend=all_mode=screen:all_opacity={opacity:.2f}[bl];"
            f"{tail_filter}"
        )
        args = [
            ffmpeg, "-y",
            "-i", str(concat_video.resolve().as_posix()),
            "-i", str(audio_input.resolve().as_posix()),
            "-stream_loop", "-1", "-i", str(overlay.resolve().as_posix()),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "1:a:0",
        ] + tail
    _run(args, cwd=video_dir)


def _thumbnail(video: Path, out: Path, duration: float) -> None:
    ffmpeg = require_ffmpeg()
    seek = min(1.0, max(0.1, duration / 3))
    _run([ffmpeg, "-y", "-ss", f"{seek:.3f}", "-i", str(video), "-frames:v", "1",
          "-q:v", "2", str(out)])


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _manifest(loaded: dict, outputs: dict, mode: str, preview: int) -> None:
    video_dir = loaded["video"]
    inputs = {}
    for name in ("audio", "srt", "script"):
        path = loaded.get(name)
        if path:
            inputs[str(path)] = _sha256(path)
    for name in ("video_plan.json", "sentences.json"):
        path = video_dir / name
        inputs[name] = _sha256(path)
    cards = {
        path.name: _sha256(path)
        for path in sorted((video_dir / "cards").glob("*.png"))
    }
    covers = {
        path.name: _sha256(path)
        for path in sorted((video_dir / "out").glob("cover_*.png"))
    }
    data = {
        "template_version": TEMPLATE_VERSION,
        "episode": loaded["meta"].get("episode") or loaded["dir"].name,
        "mode": mode,
        "preview_seconds": preview,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fonts": {"subtitle": _ass_font_name()},
        "cards": cards,
        "covers": covers,
        "inputs": inputs,
        "outputs": outputs,
        "ffmpeg_commands": _COMMANDS,
    }
    filename = "render_manifest.json" if mode == "full" else "preview_manifest.json"
    write_json(video_dir / filename, data)


# ---------------------------- 入口 ----------------------------


def render(
    episode_path: str | Path,
    aspects: str = "both",
    preview: int = 0,
    force: bool = False,
) -> int:
    """渲染成片，返回生成的 MP4 数量。"""
    _COMMANDS.clear()
    loaded = episode(episode_path)
    plan = load_plan(loaded)
    sentences_data = load_sentences(loaded)
    sentences = sentences_data.get("sentences") or []
    if not sentences:
        raise ValueError("sentences.json 没有句子")
    audio = loaded.get("audio")
    if audio is None:
        raise FileNotFoundError("找不到音频文件")
    audio_duration = probe_duration(audio) or float(sentences_data.get("audio_duration") or 0)
    if audio_duration <= 0:
        raise ValueError("读不到音频时长")

    render_cards(loaded["dir"], force=force)
    _setup_fonts(loaded["video"])

    overlay_style = str(loaded["meta"].get("overlay_style") or "none")
    subtitle_mode = str(loaded["meta"].get("subtitle_mode") or "burn")
    burn_subtitles = subtitle_mode != "none"
    try:
        overlay_opacity = float(loaded["meta"].get("overlay_opacity") or 0.22)
    except (TypeError, ValueError):
        overlay_opacity = 0.22

    aspects_list = ["9:16", "16:9"] if aspects == "both" else [aspects]
    for aspect in aspects_list:
        if aspect not in SIZES:
            raise ValueError(f"不支持的画幅：{aspect}")

    render_covers(loaded, plan, aspects_list)

    full_spans = _scene_spans(plan, sentences, audio_duration)
    preview_mode = bool(preview and audio_duration > preview + 0.5)
    spans = _preview_spans(full_spans, int(preview), audio_duration) if preview_mode else full_spans
    mode = "preview" if preview_mode else "full"
    duration = (sum(float(span["end"] - span["start"]) for span in spans)
                if preview_mode else audio_duration)

    video_dir = loaded["video"]
    segs_dir = video_dir / "segs"
    temp_dir = segs_dir / "tmp"
    segs_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    subs_dir = video_dir / "subs"
    subs_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict = {}
    count = 0
    for aspect in aspects_list:
        suffix = ASPECT_SUFFIX[aspect]
        tag = aspect.replace(":", "x")
        overlay = None
        if overlay_style != "none":
            overlay = generate_overlay(loaded["dir"], overlay_style, aspect, force=force)
            print(f"[render] 粒子叠层：{overlay.name}（{overlay_opacity:.0%}）")
        events = _build_events(sentences, ASS[aspect]["max_chars"])
        full_ass = subs_dir / f"subtitles{suffix}.ass"
        _write_ass(events, aspect, full_ass)
        _write_srt(events, aspect, subs_dir / "subtitles.srt")
        out_dir = video_dir / ("preview" if preview_mode else "out")
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_srt(events, aspect, out_dir / "subtitles.srt")

        if preview_mode:
            shifted = _events_for_spans(events, spans)
            ass_path = out_dir / f"preview{suffix}.ass"
            _write_ass(shifted, aspect, ass_path)
            audio_input = segs_dir / f"preview_audio{suffix}.wav"
            _extract_preview_audio(spans, audio, audio_input, video_dir)
        else:
            ass_path = full_ass
            audio_input = audio

        segment_paths: list[Path] = []
        for index, span in enumerate(spans):
            segment = segs_dir / f"{mode}_{tag}_{index:03d}.mp4"
            _render_scene(span, aspect, loaded, segment, temp_dir)
            actual = probe_duration(segment)
            expected = float(span["end"] - span["start"])
            if actual and abs(actual - expected) > 0.25:
                print(f"[render] 警告：{segment.name} 时长 {actual:.2f}s，预期 {expected:.2f}s")
            segment_paths.append(segment)

        concat_video = segs_dir / f"{mode}_{tag}_all.mp4"
        _concat(segment_paths, concat_video, video_dir)
        out = out_dir / (f"preview{suffix}.mp4" if preview_mode else f"video{suffix}.mp4")
        _mux(concat_video, audio_input, ass_path, out, duration, video_dir,
             aspect, overlay, overlay_opacity, burn_subtitles)
        actual = probe_duration(out)
        outputs[out.name] = {
            "path": out.resolve().as_posix(),
            "duration": actual,
            "sha256": _sha256(out),
        }
        print(f"[render] {out.name}  {actual:.2f}s")
        count += 1

    _manifest(loaded, outputs, mode, int(preview) if preview_mode else 0)
    return count
