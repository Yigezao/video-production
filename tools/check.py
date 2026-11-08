"""机械检查：入库 / 策划 / 素材 / 渲染 / 发布五个阶段。

用法：
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage ingest
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage plan
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage assets
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage render
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage publish
    python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage all

退出码：0 = 没有 fail；1 = 有 fail；2 = 期目录/文件有问题。
结果同时写进 video/qa.json。
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from PIL import Image

try:  # 直接脚本运行 / 作为 tools.check 导入
    from .common import (
        ROOT,
        load_episode,
        norm,
        probe_duration,
        read_json,
        read_text,
        write_json,
    )
except ImportError:  # pragma: no cover
    from common import (
        ROOT,
        load_episode,
        norm,
        probe_duration,
        read_json,
        read_text,
        write_json,
    )

STAGES = ("ingest", "plan", "assets", "render", "publish")
TYPE_NAMES = {
    "title_card", "book_card", "section_card", "quote_card", "character_card",
    "timeline_card", "background", "illustration", "end_card",
}
CARD_TYPES = {"title_card", "book_card", "section_card", "quote_card",
              "character_card", "timeline_card", "end_card"}
MOTIONS = {"fade", "slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right", "none"}
TRANSITIONS = {"fade", "none"}
ASPECT_KEYS = {"9:16": "_9x16", "16:9": "_16x9"}
FACT_CARD_TYPES = {"character_card", "timeline_card", "quote_card"}
CN_NUM = "一二三四五六七八九十"


def issue(message: str, detail: str = "", level: str = "fail") -> dict:
    return {"level": level, "message": message, "detail": str(detail)[:300]}


def item(name: str, level: str, summary: str, issues: list[dict] | None = None) -> dict:
    return {"name": name, "level": level, "summary": summary, "issues": issues or []}


def aggregate(name: str, entries: list[dict]) -> dict:
    if not entries:
        return item(name, "pass", "OK")
    levels = {entry["level"] for entry in entries}
    level = "fail" if "fail" in levels else ("warn" if "warn" in levels else "pass")
    return item(name, level, f"{len(entries)} 个问题", entries)


def image_exists(episode: Path, image: str) -> bool:
    path = Path(str(image))
    if path.is_absolute():
        return path.is_file()
    return ((episode / "video" / path).is_file()
            or (episode / path).is_file()
            or (ROOT / path).is_file())


def load_sentences(episode: Path) -> tuple[dict | None, list[dict], list[dict]]:
    path = episode / "video" / "sentences.json"
    if not path.is_file():
        return None, [], [issue("缺少 video/sentences.json，先跑 tools/prepare.py")]
    try:
        data = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return None, [], [issue("sentences.json 读不了", str(exc))]
    sentences = data.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        return data, [], [issue("sentences.json 里没有句子")]
    problems = []
    for index, sentence in enumerate(sentences, start=1):
        expected = f"S{index:03d}"
        if sentence.get("id") != expected:
            problems.append(issue(f"第 {index} 句 id 应为 {expected}", sentence.get("id", ""), "warn"))
        if not str(sentence.get("text") or "").strip():
            problems.append(issue(f"{expected} 没有 text"))
        try:
            start = float(sentence["start"])
            end = float(sentence["end"])
        except (KeyError, TypeError, ValueError):
            problems.append(issue(f"{expected} 时间字段不对"))
            continue
        if end <= start:
            problems.append(issue(f"{expected} end <= start", f"{start}–{end}"))
    return data, sentences, problems


def check_ingest(episode: Path, loaded: dict) -> list[dict]:
    checks: list[dict] = []
    data, sentences, problems = load_sentences(episode)
    checks.append(aggregate("句子表", problems))

    audio = loaded["audio"]
    srt = loaded["srt"]
    if audio is None:
        checks.append(item("输入文件", "fail", "缺少音频"))
        return checks
    if srt is None:
        checks.append(item("输入文件", "fail", "缺少 SRT"))
        return checks

    duration = probe_duration(audio)
    if not sentences:
        checks.append(item("总时长", "fail", "没有句子，无法比较"))
        return checks

    last_end = float(sentences[-1]["end"])
    delta = last_end - duration
    level = "pass"
    if abs(delta) > 2:
        level = "fail"
    elif abs(delta) > 0.5:
        level = "warn"
    checks.append(item("总时长", level, f"音频 {duration:.3f}s，末句 {last_end:.3f}s，差 {delta:+.3f}s"))

    if data is not None:
        recorded = float(data.get("audio_duration") or 0)
        if recorded and abs(recorded - duration) > 0.1:
            checks.append(item("音频版本", "warn",
                               f"sentences.json 记的是 {recorded:.3f}s，实际 {duration:.3f}s，建议重跑 prepare"))

    review = [issue(f"{sentence['id']} 需要人工确认", sentence.get("text", "")[:60], "warn")
              for sentence in sentences if sentence.get("needs_review")]
    checks.append(aggregate("人工确认", review))

    report_path = episode / "video" / "check_report.json"
    if report_path.is_file():
        try:
            report = read_json(report_path)
            fails = [check for check in report.get("checks", []) if check.get("level") == "fail"]
            entries = [issue(f"{check['name']}：{check.get('summary', '')}") for check in fails]
            checks.append(aggregate("入库报告", entries))
        except Exception as exc:  # noqa: BLE001
            checks.append(aggregate("入库报告", [issue("check_report.json 读不了", str(exc), "warn")]))
    else:
        checks.append(aggregate("入库报告", [issue("缺少 check_report.json，先跑 tools/prepare.py", "", "warn")]))

    # 文字必须来自 final.txt
    script = loaded["script"]
    if script is not None and data is not None and data.get("text_source") == "final.txt":
        final_text, _ = read_text(script)
        final_norm = norm(final_text)
        missing = [issue(f"{sentence['id']} 的文字不在 final.txt 里", sentence.get("text", "")[:60])
                   for sentence in sentences if norm(sentence.get("text", "")) not in final_norm]
        checks.append(aggregate("文字来源", missing))
    return checks


def scene_span(scene: dict, index: dict[str, int], sentences: list[dict]) -> tuple[float, float, float]:
    start_id = str(scene.get("from") or "")
    end_id = str(scene.get("to") or "")
    if start_id not in index or end_id not in index:
        return 0.0, 0.0, 0.0
    start = float(sentences[index[start_id]]["start"])
    end = float(sentences[index[end_id]]["end"])
    return start, end, max(0.0, end - start)


def text_len(value: str) -> int:
    return len(re.sub(r"[《》〈〉\s]", "", str(value or "")))


def check_plan(episode: Path, loaded: dict) -> list[dict]:
    path = episode / "video" / "video_plan.json"
    if not path.is_file():
        return [item("计划文件", "fail", "缺少 video/video_plan.json")]
    try:
        plan = read_json(path)
    except Exception as exc:  # noqa: BLE001
        return [item("计划文件", "fail", f"video_plan.json 读不了：{exc}")]

    meta = loaded["meta"]
    data, sentences, sentence_problems = load_sentences(episode)
    if sentence_problems:
        return [item("句子表", "fail", "句子表有问题，先修 sentences.json", sentence_problems)]

    index = {sentence["id"]: position for position, sentence in enumerate(sentences)}
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return [item("计划字段", "fail", "scenes 缺失或为空")]

    buckets: dict[str, list[dict]] = {
        name: [] for name in ("计划字段", "场景覆盖", "场景编号", "场景数量", "场景时长",
                              "卡片时长", "版式/运动", "卡片文字", "图片", "引文出处")
    }

    for key in ("version", "episode", "style", "aspects", "scenes"):
        if key not in plan:
            buckets["计划字段"].append(issue(f"缺少字段 {key}"))
    if plan.get("version") != 1:
        buckets["计划字段"].append(issue("version 应为 1", plan.get("version", "")))
    if meta.get("episode") and plan.get("episode") != meta.get("episode"):
        buckets["计划字段"].append(issue("episode 与 meta.json 不一致",
                                         f"{plan.get('episode')} != {meta.get('episode')}", "warn"))
    if meta.get("brand") and plan.get("brand") not in (None, "", meta.get("brand")):
        buckets["计划字段"].append(issue("brand 与 meta.json 不一致", plan.get("brand", ""), "warn"))

    cover = plan.get("cover") if isinstance(plan.get("cover"), dict) else None
    if cover is None:
        buckets["计划字段"].append(issue("缺少 cover（视频封面）", "", "warn"))
    else:
        if not str(cover.get("title") or "").strip():
            buckets["计划字段"].append(issue("cover 缺少 title"))
        if text_len(cover.get("line")) > 14:
            buckets["计划字段"].append(issue("cover.line 超过 14 字", cover.get("line"), "warn"))
        if text_len(cover.get("title")) > 20:
            buckets["计划字段"].append(issue("cover.title 太长", cover.get("title"), "warn"))
        image = str(cover.get("image") or "").strip()
        if image and not image_exists(episode, image):
            buckets["计划字段"].append(issue("cover.image 不存在，将用第一张插画/纸底", image, "warn"))

    # 覆盖
    expected = 0
    previous_end = -1.0
    for number, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            buckets["计划字段"].append(issue(f"第 {number} 个场景不是对象"))
            continue
        start_id = str(scene.get("from") or "")
        end_id = str(scene.get("to") or "")
        if start_id not in index:
            buckets["场景覆盖"].append(issue(f"{scene.get('id')} from 不是有效句子 id", start_id))
            continue
        if end_id not in index:
            buckets["场景覆盖"].append(issue(f"{scene.get('id')} to 不是有效句子 id", end_id))
            continue
        start_index = index[start_id]
        end_index = index[end_id]
        if end_index < start_index:
            buckets["场景覆盖"].append(issue(f"{scene.get('id')} to 在 from 之前"))
            continue
        if start_index != expected:
            buckets["场景覆盖"].append(issue(
                f"{scene.get('id')} 没有接上：应从 {sentences[expected]['id']} 开始，实际 {start_id}"))
        expected = end_index + 1
        start, end, _ = scene_span(scene, index, sentences)
        if start < previous_end - 0.01:
            buckets["场景覆盖"].append(issue(f"{scene.get('id')} 与上一场时间重叠"))
        previous_end = max(previous_end, end)
    if expected != len(sentences):
        buckets["场景覆盖"].append(issue(
            f"句子没有覆盖完：最后到 {sentences[expected]['id'] if expected < len(sentences) else '末尾'}"))

    # 编号
    for number, scene in enumerate(scenes, start=1):
        expected_id = f"V{number:02d}"
        if scene.get("id") != expected_id:
            buckets["场景编号"].append(issue(f"第 {number} 个场景 id 应为 {expected_id}", scene.get("id", "")))

    # 数量
    audio_duration = float(data.get("audio_duration") or 0) if data else 0
    route = str(meta.get("visual_route") or "cinema")
    preset = str(meta.get("preset") or ("v0" if route == "type" else "v1lite"))
    test_segment = bool(meta.get("test_segment")) or (audio_duration and audio_duration < 180)
    try:
        interval = float(meta.get("image_interval_seconds") or 0)
    except (TypeError, ValueError):
        interval = 0.0
    configured = meta.get("scene_range")
    if route != "type" and interval and interval <= 10 and audio_duration:
        expected_scenes = max(2, int((audio_duration + interval - 1) // interval))
        low, high = max(2, expected_scenes - 2), expected_scenes + 12
    elif isinstance(configured, list) and len(configured) == 2:
        low, high = int(configured[0]), int(configured[1])
    elif audio_duration and audio_duration < 180:
        low, high = 2, 8
    elif audio_duration < 1200:
        low, high = 7, 10
    elif audio_duration < 1560:
        low, high = 11, 13
    else:
        low, high = 10, 16
    if not low <= len(scenes) <= high:
        buckets["场景数量"].append(issue(f"{len(scenes)} 个场景，建议 {low}–{high} 个", "", "warn"))

    image_prompts = 0
    if route == "type" and preset != "v0":
        buckets["计划字段"].append(issue("视觉路线 type 应配 preset=v0", preset, "warn"))
    if route in ("cinema", "classic") and preset == "v0":
        buckets["计划字段"].append(issue(f"视觉路线 {route} 需要图片，preset 不应是 v0", preset, "warn"))

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = scene.get("id", "?")
        scene_type = scene.get("type")
        if scene_type not in TYPE_NAMES:
            buckets["计划字段"].append(issue(f"{scene_id} type 不合法", scene_type))
            continue

        start, end, duration = scene_span(scene, index, sentences)
        if duration <= 0:
            buckets["场景时长"].append(issue(f"{scene_id} 时长为 0"))
        elif scene_type not in ("title_card", "section_card", "end_card") and duration < 2:
            buckets["场景时长"].append(issue(f"{scene_id} 只有 {duration:.2f}s", "建议至少 2s", "warn"))
        if scene_type == "illustration":
            if duration > 240:
                buckets["场景时长"].append(issue(
                    f"{scene_id} 图片停留 {duration:.1f}s", "图片最长 2 分钟，超过 4 分钟必须拆", "fail"))
            elif duration > 120:
                buckets["场景时长"].append(issue(
                    f"{scene_id} 图片停留 {duration:.1f}s", "建议 30–90 秒，最长 2 分钟", "warn"))
            elif interval and duration > max(interval * 1.8, interval + 2):
                buckets["场景时长"].append(issue(
                    f"{scene_id} 图片停留 {duration:.1f}s", f"设定约 {interval:g}s/张，建议拆图", "warn"))
        elif duration > 240:
            buckets["场景时长"].append(issue(f"{scene_id} 有 {duration:.1f}s", "建议不超过 4 分钟", "warn"))

        hold = scene.get("hold_seconds")
        try:
            hold = float(hold)
        except (TypeError, ValueError):
            buckets["卡片时长"].append(issue(f"{scene_id} hold_seconds 不是数字", hold))
            hold = 0.0
        if scene_type in CARD_TYPES and hold <= 0:
            buckets["卡片时长"].append(issue(f"{scene_id} 是卡片，hold_seconds 必须 > 0"))
        if scene_type in ("background", "illustration") and hold <= 0:
            pass
        elif hold > duration + 0.05 and duration > 0:
            buckets["卡片时长"].append(issue(f"{scene_id} hold {hold}s 超过场景 {duration:.1f}s", "", "warn"))
        expected_hold = {
            "title_card": (3, 5), "book_card": (3, 5), "section_card": (2, 3),
            "quote_card": (4, 6), "character_card": (5, 10),
            "timeline_card": (6, 10), "end_card": (4, 6),
        }.get(scene_type)
        if expected_hold and hold > 0 and not expected_hold[0] <= hold <= expected_hold[1]:
            buckets["卡片时长"].append(issue(
                f"{scene_id} hold {hold}s，建议 {expected_hold[0]}–{expected_hold[1]}s", "", "warn"))

        layout = scene.get("layout")
        if layout not in ("full", "lower_third"):
            buckets["版式/运动"].append(issue(f"{scene_id} layout 不合法", layout))
        if scene_type in ("title_card", "book_card", "section_card", "end_card") and layout != "full":
            buckets["版式/运动"].append(issue(f"{scene_id} 必须是 full", layout))
        if scene.get("motion") not in MOTIONS:
            buckets["版式/运动"].append(issue(f"{scene_id} motion 不合法", scene.get("motion")))
        if scene.get("transition") not in TRANSITIONS:
            buckets["版式/运动"].append(issue(f"{scene_id} transition 不合法", scene.get("transition")))

        if scene_type == "book_card":
            if not str(scene.get("title") or meta.get("book_title") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 书封卡缺少 title"))
            if not str(scene.get("author") or meta.get("author") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 书封卡缺少 author"))
            if text_len(scene.get("title")) > 20:
                buckets["卡片文字"].append(issue(f"{scene_id} 书名太长", scene.get("title"), "warn"))
            background_image = str(scene.get("image") or "").strip()
            ai_book = bool(scene.get("book_image"))
            if ai_book:
                if not background_image:
                    buckets["图片"].append(issue(f"{scene_id} book_image=true 但没写 image", "", "warn"))
                elif not image_exists(episode, background_image):
                    buckets["图片"].append(issue(f"{scene_id} AI 书封图还没生成", background_image, "warn"))
            elif background_image:
                if not image_exists(episode, background_image):
                    buckets["图片"].append(issue(f"{scene_id} 书封卡背景不存在", background_image, "warn"))
                if str(meta.get("visual_route") or "cinema") == "cinema":
                    buckets["图片"].append(issue(
                        f"{scene_id} cinema 书封卡建议 book_image=true，用 AI 书封图，不要程序画书",
                        "", "warn"))
            elif str(meta.get("visual_route") or "cinema") == "cinema":
                buckets["图片"].append(issue(
                    f"{scene_id} 书封卡没指定 AI 书封图，会退回程序画书/深色底",
                    "", "warn"))
        elif scene_type == "title_card":
            if not str(scene.get("title") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 title"))
            if not str(scene.get("line") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 line（钩子）"))
            if text_len(scene.get("title")) > 16:
                buckets["卡片文字"].append(issue(f"{scene_id} title 太长", scene.get("title"), "warn"))
            if text_len(scene.get("line")) > 12:
                buckets["卡片文字"].append(issue(f"{scene_id} line 超过 12 字", scene.get("line"), "warn"))
        elif scene_type == "section_card":
            if not str(scene.get("name") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 name"))
            if text_len(scene.get("name")) > 8:
                buckets["卡片文字"].append(issue(f"{scene_id} 章节名超过 8 字", scene.get("name")))
            if text_len(scene.get("line")) > 16:
                buckets["卡片文字"].append(issue(f"{scene_id} 说明超过 16 字", scene.get("line"), "warn"))
        elif scene_type == "quote_card":
            quote = str(scene.get("quote") or "")
            if not quote.strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 quote"))
            if text_len(quote) > 18:
                buckets["卡片文字"].append(issue(f"{scene_id} 金句超过 18 字", quote, "warn"))
            quote_type = scene.get("quote_type")
            if quote_type not in ("direct", "paraphrase"):
                buckets["引文出处"].append(issue(f"{scene_id} quote_type 应为 direct / paraphrase", quote_type))
            if quote_type == "direct" and not str(scene.get("source") or "").strip():
                buckets["引文出处"].append(issue(f"{scene_id} 直引必须写 source（观众能看懂的出处）"))
            if quote_type == "direct" and str(meta.get("source_level") or "C") == "C":
                buckets["引文出处"].append(issue(f"{scene_id} 来源 C 级不能直引，请改成 paraphrase"))
        elif scene_type == "character_card":
            characters = scene.get("characters")
            if not isinstance(characters, list) or not characters:
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 characters"))
            elif len(characters) > 4:
                buckets["卡片文字"].append(issue(f"{scene_id} 人物超过 4 个"))
            else:
                for person in characters:
                    if not str(person.get("name") or "").strip():
                        buckets["卡片文字"].append(issue(f"{scene_id} 人物缺少 name"))
        elif scene_type == "timeline_card":
            nodes = scene.get("nodes")
            if not isinstance(nodes, list) or not nodes:
                buckets["卡片文字"].append(issue(f"{scene_id} 缺少 nodes"))
            elif len(nodes) > 4:
                buckets["卡片文字"].append(issue(f"{scene_id} 节点超过 4 个"))
            else:
                for node in nodes:
                    if not str(node.get("label") or "").strip():
                        buckets["卡片文字"].append(issue(f"{scene_id} 节点缺少 label"))
                    if text_len(node.get("label")) > 8:
                        buckets["卡片文字"].append(issue(f"{scene_id} 节点 label 超过 8 字", node.get("label"), "warn"))
        elif scene_type == "end_card":
            if not str(scene.get("title") or "").strip():
                buckets["卡片文字"].append(issue(f"{scene_id} 尾卡缺少 title"))
            if text_len(scene.get("line")) > 16:
                buckets["卡片文字"].append(issue(f"{scene_id} 尾卡 line 超过 16 字", scene.get("line"), "warn"))

        if scene_type in FACT_CARD_TYPES and not scene.get("source_refs"):
            buckets["引文出处"].append(issue(f"{scene_id} 事实卡没有 source_refs", "没有大纲/地图时可用背景兜底", "warn"))

        image = scene.get("image")
        if scene_type == "illustration":
            if not str(image or "").strip():
                buckets["图片"].append(issue(f"{scene_id} illustration 缺少 image"))
            else:
                if not image_exists(episode, str(image)):
                    buckets["图片"].append(issue(f"{scene_id} 图片不存在", image, "warn"))
            prompt = str(scene.get("image_prompt") or "").strip()
            if prompt:
                image_prompts += 1
                if route == "cinema" and not test_segment:
                    lowered = prompt.lower()
                    missing = [word for word in ("cinematic", "no faces", "grain") if word not in lowered]
                    if missing:
                        buckets["图片"].append(issue(
                            f"{scene_id} 电影感提示词缺少 {', '.join(missing)}", prompt[:80], "warn"))
        elif image:
            if not image_exists(episode, str(image)):
                buckets["图片"].append(issue(f"{scene_id} 图片不存在，将用品牌底兜底", image, "warn"))
            if preset == "v0":
                buckets["图片"].append(issue(f"{scene_id} v0 不应带图片", image, "warn"))

        asset_id = str(scene.get("asset_id") or "").strip()
        if asset_id:
            series_name = str(meta.get("series") or "").strip()
            series_episode = meta.get("series_episode")
            manifest_path = ROOT / "series" / series_name / "asset_manifest.json" if series_name else None
            if manifest_path is None or not manifest_path.is_file():
                buckets["图片"].append(issue(f"{scene_id} 用了 asset_id，但找不到 series/<书名>/asset_manifest.json",
                                            asset_id, "warn"))
            else:
                try:
                    manifest = read_json(manifest_path)
                    assets = {str(item.get("id")): item for item in manifest.get("assets", [])
                              if isinstance(item, dict)}
                except Exception as exc:  # noqa: BLE001
                    assets = {}
                    buckets["图片"].append(issue(f"{scene_id} asset_manifest 读不了", str(exc), "warn"))
                asset = assets.get(asset_id)
                if asset is None:
                    buckets["图片"].append(issue(f"{scene_id} asset_id 不在 manifest 里", asset_id, "fail"))
                else:
                    asset_file = manifest_path.parent / str(asset.get("file") or "")
                    if not asset_file.is_file():
                        buckets["图片"].append(issue(f"{scene_id} 复用图文件不存在", str(asset_file), "fail"))
                    allowed = asset.get("allowed_episodes") or []
                    try:
                        episode_no = int(series_episode) if series_episode is not None else None
                    except (TypeError, ValueError):
                        episode_no = None
                    if allowed and episode_no is not None and episode_no not in [int(x) for x in allowed]:
                        buckets["图片"].append(issue(
                            f"{scene_id} 这张复用图不允许第 {series_episode} 期用", asset_id, "fail"))
                    if str(asset.get("reuse") or "") == "restricted" and not allowed:
                        buckets["图片"].append(issue(f"{scene_id} restricted 复用图没有 allowed_episodes", asset_id, "warn"))

    if route == "type":
        if image_prompts:
            buckets["图片"].append(issue(f"纯排版路线不应有插画，实际 {image_prompts} 张", "", "warn"))
    elif preset == "v1lite":
        limit = 4 if test_segment else 6
        if interval and audio_duration:
            limit = max(limit, int((audio_duration + interval - 1) // interval) + 4)
        if image_prompts > limit:
            buckets["图片"].append(issue(
                f"{image_prompts} 张图，按 {interval:g}s/张 预算最多 {limit} 张", "", "warn"))
    elif preset == "v1":
        limit = 8
        if interval and audio_duration:
            limit = max(limit, int((audio_duration + interval - 1) // interval) + 4)
        if image_prompts > limit:
            buckets["图片"].append(issue(f"{image_prompts} 张图，按 {interval:g}s/张 预算最多 {limit} 张", "", "warn"))

    if not test_segment:
        if scenes[0].get("type") != "title_card":
            buckets["计划字段"].append(issue("完整一期第一场应为 title_card", scenes[0].get("type"), "warn"))
        if scenes[-1].get("type") != "end_card":
            buckets["计划字段"].append(issue("完整一期最后一场应为 end_card", scenes[-1].get("type"), "warn"))
        if not any(isinstance(scene, dict) and scene.get("type") == "book_card" for scene in scenes):
            buckets["计划字段"].append(issue("完整一期没有 book_card（念到‘今天讲《书名》’时的书封卡）", "", "warn"))

    return [aggregate(name, entries) for name, entries in buckets.items()]


def check_assets(episode: Path, loaded: dict) -> list[dict]:
    checks: list[dict] = []
    plan_path = episode / "video" / "video_plan.json"
    if not plan_path.is_file():
        return [item("素材", "fail", "缺少 video/video_plan.json，先做 Step 2")]
    try:
        plan = read_json(plan_path)
    except Exception as exc:  # noqa: BLE001
        return [item("素材", "fail", f"video_plan.json 读不了：{exc}")]

    meta = loaded["meta"]
    aspects = meta.get("aspects") or ["9:16", "16:9"]
    scenes = [scene for scene in plan.get("scenes", []) if isinstance(scene, dict)]

    missing_cards = []
    for scene in scenes:
        if scene.get("type") not in CARD_TYPES:
            continue
        for aspect in aspects:
            suffix = ASPECT_KEYS.get(aspect, "_9x16")
            path = episode / "video" / "cards" / f"{scene.get('id')}{suffix}.png"
            if not path.is_file():
                missing_cards.append(issue(f"{scene.get('id')} {aspect} 卡片没渲染", path.name))
    checks.append(aggregate("卡片", missing_cards))

    missing_subs = []
    for aspect in aspects:
        suffix = ASPECT_KEYS.get(aspect, "_9x16")
        path = episode / "video" / "subs" / f"subtitles{suffix}.ass"
        if not path.is_file():
            missing_subs.append(issue(f"{aspect} ASS 字幕还没生成", path.name, "warn"))
    if not (episode / "video" / "subs" / "subtitles.srt").is_file():
        missing_subs.append(issue("外挂 SRT 还没生成", "subtitles.srt", "warn"))
    checks.append(aggregate("字幕", missing_subs))

    image_issues = []
    for scene in scenes:
        if scene.get("type") != "illustration" or not scene.get("image"):
            continue
        path = episode / "video" / str(scene["image"])
        if not path.is_file():
            path = episode / str(scene["image"])
        if not path.is_file():
            image_issues.append(issue(f"{scene.get('id')} 图片不存在，渲染时用品牌底兜底", scene.get("image"), "warn"))
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                if min(width, height) < 800:
                    image_issues.append(issue(
                        f"{scene.get('id')} 图片只有 {width}x{height}", "建议至少 1024x1024", "warn"))
                if abs(width / max(1, height) - 1) > 0.12:
                    image_issues.append(issue(
                        f"{scene.get('id')} 图片不是 1:1（{width}x{height}）", "渲染会裁切，建议重生成方图", "warn"))
        except Exception as exc:  # noqa: BLE001
            image_issues.append(issue(f"{scene.get('id')} 图片读不了", str(exc), "warn"))
    images_dir = episode / "video" / "images"
    expected_names = {Path(str(scene["image"])).name for scene in scenes
                      if scene.get("type") == "illustration" and scene.get("image")}
    if images_dir.is_dir():
        extra_images = [
            path for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
            and path.name not in expected_names
        ]
        if extra_images:
            image_issues.append(issue(
                f"images/ 里有 {len(extra_images)} 张未命名图片",
                "先跑 python tools/rename_images.py --episode <期> 自动排序命名",
                "warn"))
    checks.append(aggregate("图片", image_issues))

    prompts = episode / "video" / "image_prompts.txt"
    legacy_prompts = episode / "video" / "image_prompts.md"
    if meta.get("preset") in ("v1lite", "v1") and not prompts.is_file() and not legacy_prompts.is_file():
        checks.append(aggregate("图片提示词", [issue("缺少 video/image_prompts.txt", "", "warn")]))
    else:
        checks.append(aggregate("图片提示词", []))

    subtitle_mode = str(meta.get("subtitle_mode") or "burn")
    if subtitle_mode not in ("burn", "none"):
        checks.append(aggregate("字幕模式", [issue(f"未知 subtitle_mode：{subtitle_mode}", "用 burn/none", "warn")]))
    else:
        checks.append(aggregate("字幕模式", []))

    overlay_style = str(meta.get("overlay_style") or "none")
    overlay_issues = []
    if overlay_style not in ("none", "dust", "snow", "embers"):
        overlay_issues.append(issue(f"未知粒子样式：{overlay_style}", "用 none/dust/snow/embers", "warn"))
    elif overlay_style != "none":
        for aspect in meta.get("aspects") or ["9:16", "16:9"]:
            suffix = ASPECT_KEYS.get(aspect, "_9x16")
            path = episode / "video" / "overlays" / f"{overlay_style}{suffix}.mp4"
            if not path.is_file():
                overlay_issues.append(issue(f"{aspect} 粒子叠层还没生成", "render 时会自动生成", "warn"))
    checks.append(aggregate("粒子叠层", overlay_issues))

    font_paths = [
        ROOT / "fonts" / "NotoSansSC-Medium.otf",
        ROOT / "fonts" / "NotoSerifSC-SemiBold.otf",
        Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"),
        Path(r"C:\Windows\Fonts\NotoSerifSC-VF.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    if not any(path.is_file() for path in font_paths):
        checks.append(aggregate("字体", [issue("找不到可用的中文字体", "建议放 fonts/NotoSansSC-Medium.otf", "warn")]))
    else:
        checks.append(aggregate("字体", []))
    return checks


def check_render(episode: Path, loaded: dict) -> list[dict]:
    checks: list[dict] = []
    audio = loaded["audio"]
    meta = loaded["meta"]
    aspects = meta.get("aspects") or ["9:16", "16:9"]
    if audio is None:
        return [item("渲染输出", "fail", "缺少音频")]
    audio_duration = probe_duration(audio)

    missing = []
    for aspect in aspects:
        suffix = ASPECT_KEYS.get(aspect, "_9x16")
        path = episode / "video" / "out" / f"video{suffix}.mp4"
        if not path.is_file():
            missing.append(issue(f"{aspect} 成片不存在", path.name))
            continue
        video_duration = probe_duration(path)
        delta = video_duration - audio_duration
        if abs(delta) > 0.5:
            missing.append(issue(f"{aspect} 成片时长 {video_duration:.2f}s，音频 {audio_duration:.2f}s，差 {delta:+.2f}s"))
    checks.append(aggregate("成片", missing))

    extras = []
    for aspect in aspects:
        suffix = ASPECT_KEYS.get(aspect, "_9x16")
        if not (episode / "video" / "out" / f"cover{suffix}.png").is_file():
            extras.append(issue(f"{aspect} 视频封面缺失", f"cover{suffix}.png", "fail"))
        if not (episode / "video" / "out" / f"thumb{suffix}.png").is_file():
            extras.append(issue(f"{aspect} 缩略图缺失", "", "warn"))
    if not (episode / "video" / "out" / "subtitles.srt").is_file():
        extras.append(issue("out/subtitles.srt 缺失", "", "warn"))
    if not (episode / "video" / "qc_report.json").is_file():
        extras.append(issue("qc_report.json 缺失，还没跑 qc", "", "warn"))
    if not (episode / "video" / "render_manifest.json").is_file():
        extras.append(issue("render_manifest.json 缺失", "", "warn"))
    checks.append(aggregate("交付物", extras))
    return checks


def check_publish(episode: Path, loaded: dict) -> list[dict]:
    checks: list[dict] = []
    path = episode / "publish.md"
    if not path.is_file():
        return [item("发布信息", "fail", "缺少 publish.md")]
    text, _ = read_text(path)
    entries = []
    if len(re.findall(r"^\s*[123][.、]", text, re.M)) < 3:
        entries.append(issue("标题不足 3 个", "", "warn"))
    if "AI" not in text and "人工智能" not in text:
        entries.append(issue("简介缺少 AI 辅助生成声明", "", "warn"))
    if "标签" not in text:
        entries.append(issue("缺少标签段", "", "warn"))
    if str(loaded["meta"].get("spoiler_policy") or "") == "no_ending" and re.search(r"大结局|结局是|最后.+死了", text):
        entries.append(issue("no_ending 期可能泄露结局", "", "warn"))
    checks.append(aggregate("发布信息", entries))
    return checks


def run_stage(stage: str, episode: Path, loaded: dict) -> list[dict]:
    if stage == "ingest":
        return check_ingest(episode, loaded)
    if stage == "plan":
        return check_plan(episode, loaded)
    if stage == "assets":
        return check_assets(episode, loaded)
    if stage == "render":
        return check_render(episode, loaded)
    if stage == "publish":
        return check_publish(episode, loaded)
    return [item("阶段", "fail", f"未知阶段 {stage}")]


def save_qa(episode: Path, stage: str, checks: list[dict]) -> None:
    path = episode / "video" / "qa.json"
    data = {"episode": episode.name, "updated": datetime.now().isoformat(timespec="seconds"), "stages": {}}
    if path.is_file():
        try:
            old = read_json(path)
            data["stages"] = old.get("stages", {})
        except Exception:  # noqa: BLE001
            pass
    data["stages"][stage] = {
        "ok": all(check["level"] != "fail" for check in checks),
        "checks": checks,
    }
    write_json(path, data)


def print_checks(stage: str, checks: list[dict]) -> bool:
    ok = True
    print(f"\n[{stage}]")
    for check in checks:
        level = check["level"]
        if level != "pass":
            ok = ok and level != "fail"
        mark = {"pass": "OK", "warn": "WARN", "fail": "FAIL", "hint": "HINT"}.get(level, level)
        print(f"  {mark:4} {check['name']}：{check['summary']}")
        if level != "pass":
            for entry in check["issues"][:8]:
                suffix = f"（{entry['detail']}）" if entry.get("detail") else ""
                print(f"         - {entry['message']}{suffix}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="视频流水线机械检查")
    parser.add_argument("--episode", required=True)
    parser.add_argument("--stage", default="ingest",
                        choices=STAGES + ("all",))
    args = parser.parse_args()

    episode = Path(args.episode)
    if not episode.is_absolute():
        episode = (Path.cwd() / episode).resolve()
    if not episode.is_dir():
        print(f"找不到期目录：{episode}")
        return 2

    loaded = load_episode(episode)
    stages = STAGES if args.stage == "all" else (args.stage,)
    all_ok = True
    any_fail = False
    for stage in stages:
        try:
            checks = run_stage(stage, episode, loaded)
        except Exception as exc:  # noqa: BLE001
            checks = [item(stage, "fail", f"检查脚本出错：{exc}")]
        save_qa(episode, stage, checks)
        ok = print_checks(stage, checks)
        all_ok = all_ok and ok
        any_fail = any_fail or any(check["level"] == "fail" for check in checks)

    print(f"\n结果：{'没有 fail' if not any_fail else '有 fail，先修再往下走'}")
    print(f"报告：{episode / 'video' / 'qa.json'}")
    return 0 if not any_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
