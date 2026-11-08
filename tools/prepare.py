"""入库检查：把 audio + SRT + 口播稿变成 video/sentences.json 和检查报告。

用法：
    python tools/prepare.py --episode episodes/羊脂球-2026-10-25

产出：
    video/sentences.json     每句 id / start / end / text（后面所有步骤的唯一时间依据）
    video/check_report.json  五项检查结果（机器读）
    video/ingest_report.md   给人看的入库报告

原则：
    - SRT 只提供时间；文字以 final.txt 为准。
    - 音频不动；SRT 缺失就停，不猜时间。
    - 对齐用全局单调匹配（difflib），不逐条模糊替换。
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

try:  # 直接脚本运行 / 作为 tools.prepare 导入
    from .common import (
        load_episode,
        norm,
        probe_duration,
        read_text,
        write_json,
    )
except ImportError:  # pragma: no cover
    from common import (
        load_episode,
        norm,
        probe_duration,
        read_text,
        write_json,
    )

SENT_END = set("。！？!?…")
CLOSE_QUOTES = set("”’」』）〉】")
TIME_RE = re.compile(
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


# ----------------------------- SRT -----------------------------


def to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")[:3]) / 1000


def needs_space(left: str, right: str) -> bool:
    def is_cjk(char: str) -> bool:
        return bool(char) and (
            "一" <= char <= "鿿"
            or "㐀" <= char <= "䶿"
            or char in "，。！？；：、“”‘’（）《》【】…—"
        )

    return not (is_cjk(left) or is_cjk(right))


def join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text and needs_space(text[-1], line[0]):
            text += " "
        text += line
    return text


def parse_srt(text: str) -> tuple[list[dict], list[str]]:
    cues: list[dict] = []
    errors: list[str] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block_index, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if time_at < 0:
            errors.append(f"第 {block_index} 块没有时间行")
            continue
        match = TIME_RE.search(lines[time_at])
        if not match:
            errors.append(f"第 {block_index} 块时间格式不对：{lines[time_at][:60]}")
            continue
        raw_index = None
        if time_at > 0 and lines[time_at - 1].strip().isdigit():
            raw_index = int(lines[time_at - 1].strip())
        body_lines = lines[time_at + 1:]
        if not body_lines:
            errors.append(f"第 {block_index} 块没有文字")
            continue
        start = to_seconds(*match.groups()[:4])
        end = to_seconds(*match.groups()[4:])
        cues.append({
            "index": raw_index or block_index,
            "order": len(cues) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": join_lines(body_lines),
            "line_count": len(body_lines),
        })
    return cues, errors


# ---------------------------- 文本 ----------------------------


def split_sentences(text: str) -> list[dict]:
    """按中文句末标点切句，保留原文字符区间（用于对齐）。"""
    result: list[dict] = []
    start = 0
    i = 0
    size = len(text)
    while i < size:
        char = text[i]
        if char == "\n":
            piece = text[start:i].strip()
            if piece:
                lead = len(text[start:i]) - len(text[start:i].lstrip())
                result.append({"text": piece, "start": start + lead, "end": i})
            i += 1
            start = i
            continue
        if char in SENT_END:
            j = i
            while j < size and text[j] in SENT_END:
                j += 1
            while j < size and text[j] in CLOSE_QUOTES:
                j += 1
            piece = text[start:j].strip()
            if piece:
                lead = len(text[start:j]) - len(text[start:j].lstrip())
                result.append({"text": piece, "start": start + lead, "end": j})
            i = j
            start = j
            continue
        i += 1
    piece = text[start:size].strip()
    if piece:
        lead = len(text[start:size]) - len(text[start:size].lstrip())
        result.append({"text": piece, "start": start + lead, "end": size})
    return result


def norm_chars(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        for normalized in unicodedata.normalize("NFKC", char):
            if normalized.isspace():
                continue
            category = unicodedata.category(normalized)
            if category.startswith(("P", "S")):
                continue
            chars.append(normalized.lower())
            index.append(position)
    return "".join(chars), index


# ---------------------------- 对齐 ----------------------------


def cue_only_sentences(cues: list[dict], review: bool) -> list[dict]:
    sentences = []
    for number, cue in enumerate(cues, start=1):
        sentences.append({
            "id": f"S{number:03d}",
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
            "srt_index": [cue["index"]],
            "needs_review": review,
        })
    return sentences


def align(final_text: str, cues: list[dict]) -> dict:
    """把 SRT 的时间映射到 final.txt 的句子上。返回 sentences + 对齐诊断。"""
    final_sentences = split_sentences(final_text)
    final_norm, final_map = norm_chars(final_text)

    srt_parts: list[str] = []
    srt_map: list[int] = []
    for cue_index, cue in enumerate(cues):
        normalized, _ = norm_chars(cue["text"])
        srt_parts.append(normalized)
        srt_map.extend([cue_index] * len(normalized))
    srt_norm = "".join(srt_parts)

    if not final_norm or not srt_norm:
        return {
            "sentences": cue_only_sentences(cues, review=True),
            "ratio": 0.0,
            "unmatched_cues": [cue["index"] for cue in cues],
            "unmatched_sentences": [],
            "used_final_text": False,
        }

    matcher = SequenceMatcher(None, final_norm, srt_norm, autojunk=False)
    blocks = matcher.get_matching_blocks()
    matched = sum(block.size for block in blocks)
    ratio = 2 * matched / (len(final_norm) + len(srt_norm))

    cue_positions: dict[int, list[int]] = defaultdict(list)
    cue_matched_chars: dict[int, int] = defaultdict(int)
    for block in blocks:
        for offset in range(block.size):
            final_position = final_map[block.a + offset]
            cue_index = srt_map[block.b + offset]
            cue_positions[cue_index].append(final_position)
            cue_matched_chars[cue_index] += 1

    # 单条 SRT 只有一小部分能对上稿子：可能是字幕多了话，标出来
    low_coverage_cues = []
    for cue_index, cue in enumerate(cues):
        cue_length = len(norm_chars(cue["text"])[0])
        if cue_length and cue_matched_chars.get(cue_index, 0) / cue_length < 0.7:
            low_coverage_cues.append(cue["index"])

    allocations: dict[int, list[tuple[float, float]]] = defaultdict(list)
    unmatched_cues: list[int] = []
    for cue_index, cue in enumerate(cues):
        positions = cue_positions.get(cue_index)
        if not positions:
            unmatched_cues.append(cue["index"])
            continue
        low = min(positions)
        high = max(positions) + 1
        overlaps = []
        for sentence_index, sentence in enumerate(final_sentences):
            overlap = max(0, min(high, sentence["end"]) - max(low, sentence["start"]))
            if overlap:
                overlaps.append((sentence_index, overlap))
        if not overlaps:
            unmatched_cues.append(cue["index"])
            continue
        total_weight = sum(weight for _, weight in overlaps)
        cursor = cue["start"]
        duration = max(0.0, cue["end"] - cue["start"])
        for sentence_index, weight in overlaps:
            portion = duration * weight / total_weight
            allocations[sentence_index].append((cursor, cursor + portion))
            cursor += portion

    sentences: list[dict] = []
    output_by_sentence: dict[int, dict] = {}
    unmatched_sentences: list[str] = []
    previous_end = 0.0
    for sentence_index, sentence in enumerate(final_sentences):
        pieces = allocations.get(sentence_index)
        if not pieces:
            unmatched_sentences.append(sentence["text"][:30])
            continue
        start = min(piece[0] for piece in pieces)
        end = max(piece[1] for piece in pieces)
        if start < previous_end - 0.001:
            start = previous_end
        if end <= start:
            end = start + 0.5
        output = {
            "id": "",
            "start": round(start, 3),
            "end": round(end, 3),
            "text": sentence["text"],
            "srt_index": [],
            "needs_review": False,
        }
        sentences.append(output)
        output_by_sentence[sentence_index] = output
        previous_end = end

    # 回填每个句子覆盖到的 SRT 序号
    for cue_index, cue in enumerate(cues):
        positions = cue_positions.get(cue_index)
        if not positions:
            continue
        low, high = min(positions), max(positions) + 1
        for sentence_index, sentence in enumerate(final_sentences):
            output = output_by_sentence.get(sentence_index)
            if output is None:
                continue
            if max(0, min(high, sentence["end"]) - max(low, sentence["start"])):
                if cue["index"] not in output["srt_index"]:
                    output["srt_index"].append(cue["index"])

    # 统一编号
    for number, sentence in enumerate(sentences, start=1):
        sentence["id"] = f"S{number:03d}"
        sentence["srt_index"] = sorted(set(sentence["srt_index"]))

    return {
        "sentences": sentences,
        "ratio": round(ratio, 3),
        "unmatched_cues": sorted(set(unmatched_cues) | set(low_coverage_cues)),
        "unmatched_sentences": unmatched_sentences,
        "used_final_text": True,
    }


# ---------------------------- 报告 ----------------------------


def item(name: str, level: str, summary: str, issues: list[dict] | None = None) -> dict:
    return {"name": name, "level": level, "summary": summary, "issues": issues or []}


def issue(message: str, detail: str = "") -> dict:
    return {"message": message, "detail": detail[:200]}


def build_checks(
    cues: list[dict],
    errors: list[str],
    audio_duration: float,
    alignment: dict,
    sentences: list[dict],
    srt_encoding: str,
    has_script: bool,
) -> list[dict]:
    checks: list[dict] = []

    checks.append(item("SRT 格式", "pass" if not errors else "fail",
                       f"{len(cues)} 条字幕，{len(errors)} 个解析错误",
                       [issue(message) for message in errors]))

    if cues and audio_duration:
        delta = cues[-1]["end"] - audio_duration
        level = "pass" if abs(delta) <= 2 else "fail"
        if 0.5 < abs(delta) <= 2:
            level = "warn"
        checks.append(item("总时长", level,
                           f"WAV {audio_duration:.3f}s，SRT 末条 {cues[-1]['end']:.3f}s，差 {delta:+.3f}s"))

    overlaps = []
    short = []
    long = []
    single = []
    multiline = []
    previous_end = -1.0
    for cue in cues:
        if cue["start"] < previous_end - 0.001:
            overlaps.append(issue(f"第 {cue['index']} 条与上一条重叠", f"{cue['start']} < {previous_end}"))
        previous_end = max(previous_end, cue["end"])
        duration = cue["end"] - cue["start"]
        if duration <= 0:
            overlaps.append(issue(f"第 {cue['index']} 条时长为 0 或负数"))
        elif duration < 0.8:
            short.append(issue(f"第 {cue['index']} 条只有 {duration:.2f}s", cue["text"]))
        elif duration > 6:
            long.append(issue(f"第 {cue['index']} 条有 {duration:.2f}s", cue["text"]))
        if len(norm(cue["text"])) == 1:
            single.append(issue(f"第 {cue['index']} 条只有 1 个字", cue["text"]))
        if cue["line_count"] > 2:
            multiline.append(issue(f"第 {cue['index']} 条有 {cue['line_count']} 行", cue["text"]))

    structure_level = "fail" if overlaps else ("warn" if (short or long or single or multiline) else "pass")
    structure_issues = overlaps + short + long + single + multiline
    checks.append(item("结构", structure_level,
                       f"重叠 {len(overlaps)}，<0.8s {len(short)}，>6s {len(long)}，单字 {len(single)}，>2 行 {len(multiline)}",
                       structure_issues[:20]))

    if not has_script:
        checks.append(item("文字对齐", "warn", "没有 final.txt，字幕文字直接取自 SRT；同音错字无法校正"))
    else:
        ratio = alignment.get("ratio", 0)
        level = "pass"
        summary = f"与 final.txt 匹配率 {ratio:.1%}"
        if ratio < 0.70:
            level = "fail"
            summary += "，低于 70%，已停止自动替换；请确认 SRT 和稿子是不是同一版"
        elif ratio < 0.95:
            level = "warn"
            summary += "，建议人工抽查"
        alignment_issues = [
            issue(f"SRT 第 {index} 条没有匹配到稿子") for index in alignment.get("unmatched_cues", [])
        ] + [
            issue(f"稿子里的句子没有在音频里找到：{text}") for text in alignment.get("unmatched_sentences", [])
        ]
        checks.append(item("文字对齐", level, summary, alignment_issues[:20]))

    zero = [issue(f"{sentence['id']} 时长异常", f"{sentence['start']}–{sentence['end']}")
            for sentence in sentences if sentence["end"] <= sentence["start"]]
    checks.append(item("句子表", "pass" if sentences and not zero else "fail",
                       f"{len(sentences)} 句", zero))

    if srt_encoding.lower().startswith("gb"):
        checks.append(item("SRT 编码", "warn", f"检测到 {srt_encoding}，已按 UTF-8 输出句子表"))
    return checks


def write_markdown(path: Path, data: dict) -> None:
    lines = [
        f"# 入库检查 · {data['episode']}",
        "",
        f"- 音频：`{data['audio']['path']}`（{data['audio']['duration']:.3f}s，{data['audio']['format']}）",
        f"- SRT：`{data['srt']['path']}`（{data['srt']['cues']} 条，编码 {data['srt']['encoding']}）",
        f"- 稿子：`{data['script']['path']}`" if data["script"]["path"] else "- 稿子：没有 final.txt，文字以 SRT 为准",
        f"- 句子表：{data['sentences']} 句，文字来源：{data['sentences_source']}",
        f"- 结论：{'通过' if data['ok'] else '有 fail，先修再往下走'}",
        "",
        "| 检查 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for check in data["checks"]:
        lines.append(f"| {check['name']} | {check['level']} | {check['summary']} |")
    problems = [issue for check in data["checks"] for issue in check["issues"]]
    if problems:
        lines += ["", "## 问题", ""]
        for problem in problems[:30]:
            detail = f"：{problem['detail']}" if problem.get("detail") else ""
            lines.append(f"- {problem['message']}{detail}")
    lines += [
        "",
        "## 人工只看三件事",
        "",
        "- [ ] 最后一条字幕结束时间 ≈ 音频总时长（差 ≤2 秒）。",
        "- [ ] 抽 5 条字幕，人名/书名/数字对得上稿子。",
        "- [ ] 没有单字行、没有超过 6 秒的长条。",
        "",
        "> SRT 只提供时间；文字以 final.txt 为准。音频不动。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="视频一期入库检查")
    parser.add_argument("--episode", required=True, help="期目录，如 episodes/羊脂球-2026-10-25")
    args = parser.parse_args()

    episode = (Path.cwd() / args.episode).resolve() if not Path(args.episode).is_absolute() else Path(args.episode)
    if not episode.is_dir():
        print(f"找不到期目录：{episode}")
        return 2

    loaded = load_episode(episode)
    meta = loaded["meta"]
    audio = loaded["audio"]
    srt = loaded["srt"]
    script = loaded["script"]

    if audio is None:
        print("缺少音频：episode 根目录下应有 audio.wav / audio.mp3 或 meta.audio_file。")
        return 2
    if srt is None:
        print("缺少 SRT：episode 根目录下应有 subtitles.srt。没有 SRT 不要猜时间。")
        return 2

    audio_duration = probe_duration(audio)
    srt_text, srt_encoding = read_text(srt)
    cues, errors = parse_srt(srt_text)

    has_script = script is not None
    final_text = ""
    if has_script:
        final_text, _ = read_text(script)

    if has_script:
        alignment = align(final_text, cues)
        ratio = alignment["ratio"]
        if ratio < 0.70:
            # 全局匹配率过低：停止自动替换，改用 SRT 原文并标 review
            sentences = cue_only_sentences(cues, review=True)
            sentences_source = "subtitles.srt（对齐失败，待人工确认）"
        else:
            sentences = alignment["sentences"]
            sentences_source = "final.txt"
    else:
        alignment = {
            "ratio": 0,
            "unmatched_cues": [],
            "unmatched_sentences": [],
            "used_final_text": False,
        }
        sentences = cue_only_sentences(cues, review=False)
        sentences_source = "subtitles.srt"

    checks = build_checks(cues, errors, audio_duration, alignment, sentences, srt_encoding, has_script)
    # 稿子存在但与 SRT 对不上时，文字对齐项已经给出 fail；这里再保证句子表不为空
    ok = all(check["level"] != "fail" for check in checks) and bool(sentences)

    report = {
        "stage": "ingest",
        "episode": meta.get("episode") or episode.name,
        "audio": {"path": str(audio), "duration": audio_duration, "format": audio.suffix.lstrip(".").lower()},
        "srt": {
            "path": str(srt),
            "cues": len(cues),
            "encoding": srt_encoding,
            "first_start": cues[0]["start"] if cues else 0,
            "last_end": cues[-1]["end"] if cues else 0,
        },
        "script": {"path": str(script) if script else "", "sentences": len(sentences)},
        "alignment": alignment,
        "sentences_source": sentences_source,
        "checks": checks,
        "sentences": len(sentences),
        "ok": ok,
    }

    video_dir = episode / "video"
    write_json(video_dir / "sentences.json", {
        "episode": report["episode"],
        "audio_duration": audio_duration,
        "audio_file": str(audio.relative_to(episode)).replace("\\", "/"),
        "srt_file": str(srt.relative_to(episode)).replace("\\", "/"),
        "text_source": sentences_source,
        "alignment_ratio": alignment.get("ratio", 0),
        "sentences": sentences,
    })
    write_json(video_dir / "check_report.json", report)
    write_markdown(video_dir / "ingest_report.md", report)

    print(f"入库完成：{report['episode']}")
    print(f"  音频 {audio_duration:.3f}s，SRT {len(cues)} 条，句子 {len(sentences)} 句")
    print(f"  文字来源：{sentences_source}")
    print(f"  对齐匹配率：{alignment.get('ratio', 0):.1%}" if has_script else "  没有 final.txt")
    for check in checks:
        if check["level"] != "pass":
            print(f"  [{check['level']}] {check['name']}：{check['summary']}")
            for problem in check["issues"][:5]:
                print(f"      - {problem['message']}")
    print(f"  结果：{'通过' if ok else '有 fail，先修再往下走'}")
    print(f"  报告：{video_dir / 'ingest_report.md'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
