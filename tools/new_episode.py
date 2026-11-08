"""新建一期：从一个文件夹里找 音频 + SRT + 口播稿，复制进 episodes/<期名>/ 并跑入库检查。

用法：
    python tools/new_episode.py "D:\\my_Software\\Audacity\\导出音频\\羊脂球"
    python tools/new_episode.py "D:\\...\\羊脂球" --yes --title 羊脂球 --author 莫泊桑

目录里只要有一个音频和一个 SRT 就能建期；没有 final.txt 会警告（文字将以 SRT 为准）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

try:  # 直接脚本运行 / 作为 tools.new_episode 导入
    from .common import (
        AUDIO_EXTS,
        EPISODES,
        ROOT,
        SKIP_TXT,
        probe_duration,
        safe_name,
        unique_dir,
        write_json,
    )
except ImportError:  # pragma: no cover
    from common import (
        AUDIO_EXTS,
        EPISODES,
        ROOT,
        SKIP_TXT,
        probe_duration,
        safe_name,
        unique_dir,
        write_json,
    )

PREPARE = ROOT / "tools" / "prepare.py"


def ask(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]：").strip()
    return value or default


def ask_choice(prompt: str, choices: dict[str, str], default: str) -> str:
    while True:
        value = input(f"{prompt} [{default}]：").strip() or default
        if value in choices:
            return choices[value]
        print("输入不对，请重来。")


def ask_yes(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]：").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "是", "1")


def pick_one(items: list[Path], label: str, auto: bool, preferred: list[str] | None = None) -> Path | None:
    if not items:
        return None
    if preferred:
        for name in preferred:
            for item in items:
                if item.name.lower() == name.lower():
                    return item
    if len(items) == 1 or auto:
        return items[0]
    print(f"\n找到 {len(items)} 个{label}：")
    for index, item in enumerate(items, start=1):
        print(f"  {index}. {item.name}")
    while True:
        value = input(f"选第几个 [{1}]：").strip() or "1"
        if value.isdigit() and 1 <= int(value) <= len(items):
            return items[int(value) - 1]
        print("输入不对，请重来。")


def main() -> int:
    parser = argparse.ArgumentParser(description="新建一期视频目录")
    parser.add_argument("input", nargs="?", default="", help="音频文件夹，或音频文件")
    parser.add_argument("--yes", action="store_true", help="全部用默认值，不提问")
    parser.add_argument("--name", default="", help="期目录名，默认 <书名>-<日期>")
    parser.add_argument("--title", default="", help="书名")
    parser.add_argument("--author", default="未标注")
    parser.add_argument("--column", default="听故事", choices=("读懂", "听故事"))
    parser.add_argument("--brand", default="{{brand}}")
    parser.add_argument("--mode", default="literary", choices=("literary", "narrative"))
    parser.add_argument("--visual-route", default="cinema", choices=("cinema", "classic", "type"),
                        help="视觉路线：cinema=电影感 AI 静帧（默认）/ classic=公版画 / type=纯排版")
    parser.add_argument("--preset", default="v1lite", choices=("v0", "v1lite", "v1"))
    parser.add_argument("--target-minutes", type=float, default=0)
    parser.add_argument("--spoiler-policy", default="no_ending", choices=("no_ending", "main_ending_ok"))
    parser.add_argument("--source-level", default="C", choices=("A", "B", "C"))
    parser.add_argument("--test-segment", action="store_true", help="测试段：场景数放宽到 2–8")
    parser.add_argument("--images-from", default="", help="预生产图片目录，复制到 video/images/")
    parser.add_argument("--image-interval", type=float, default=5,
                        help="每张图大约多少秒；5=密集模式，0=用常规 30–90 秒")
    parser.add_argument("--overlay-style", default="none", choices=("none", "dust", "snow", "embers"))
    parser.add_argument("--overlay-opacity", type=float, default=0.22)
    parser.add_argument("--subtitle-mode", default="burn", choices=("burn", "none"),
                        help="burn=字幕烧进视频；none=只出视频+音频，字幕后期自己加")
    parser.add_argument("--series", default="", help="长篇系列名，对应 series/<系列>/asset_manifest.json")
    parser.add_argument("--series-episode", type=int, default=0, help="系列第几期，用于复用图权限")
    args = parser.parse_args()

    raw = args.input.strip().strip('"')
    if not raw and not args.yes:
        raw = input("把音频文件夹（或音频文件）拖进来：").strip().strip('"')
    if not raw:
        print("没有输入。")
        return 2

    source = Path(raw).expanduser().resolve()
    if source.is_file():
        if source.suffix.lower() not in AUDIO_EXTS:
            print(f"这不是音频文件：{source}")
            return 2
        folder = source.parent
        audio = source
    elif source.is_dir():
        folder = source
        audios = sorted(item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in AUDIO_EXTS)
        audio = pick_one(audios, "音频", args.yes)
    else:
        print(f"找不到：{source}")
        return 2

    if audio is None:
        print(f"文件夹里没有音频（{'/'.join(AUDIO_EXTS)}）：{folder}")
        return 2

    srts = sorted(item for item in folder.iterdir() if item.is_file() and item.suffix.lower() == ".srt")
    srt = pick_one(srts, "SRT", args.yes, preferred=[f"{audio.stem}.srt", "subtitles.srt"])
    if srt is None:
        print(f"文件夹里没有 SRT：{folder}")
        print("没有 SRT 不要猜时间；先在剪映/Audacity 导出字幕后重跑。")
        return 2

    scripts = sorted(
        item for item in folder.iterdir()
        if item.is_file() and item.suffix.lower() == ".txt"
        and not any(word in item.name.lower() for word in SKIP_TXT)
    )
    script = pick_one(scripts, "口播稿 txt", args.yes,
                      preferred=[f"{audio.stem}.txt", "final.txt", "script.txt"])

    duration = probe_duration(audio)
    test_segment = args.test_segment or duration < 180

    title = args.title.strip() or audio.stem
    if not args.yes and not args.title:
        title = ask("书名", title)
    author = args.author
    if not args.yes and args.author == "未标注":
        author = ask("作者", author)
    column = args.column
    if not args.yes:
        column = ask_choice("栏目 1=听故事 2=读懂", {"1": "听故事", "2": "读懂"}, "1")
    brand = args.brand
    if not args.yes:
        brand = ask("账号名（可先用占位）", brand)
    mode = args.mode
    if not args.yes:
        mode = ask_choice("类型 1=文学 2=网文", {"1": "literary", "2": "narrative"}, "1")
    visual_route = args.visual_route
    if not args.yes:
        visual_route = ask_choice(
            "视觉路线 1=B 电影感（默认） 2=A 公版画 3=C 纯排版",
            {"1": "cinema", "2": "classic", "3": "type"}, "1",
        )
    preset_default = "2" if visual_route == "type" else "1"
    preset = args.preset
    if not args.yes:
        preset = ask_choice("画面上限 1=V1-lite 2=V0 3=V1", {"1": "v1lite", "2": "v0", "3": "v1"}, preset_default)
    elif visual_route == "type":
        preset = "v0"
    if test_segment and not args.yes:
        print(f"\n这段音频只有 {duration:.1f} 秒，按测试段处理（场景数 2–8）。")

    minutes = args.target_minutes or round(duration / 60, 2)
    if test_segment:
        scene_range = [2, 8]
    elif minutes <= 20:
        scene_range = [7, 10]
    elif minutes <= 26:
        scene_range = [11, 13]
    else:
        scene_range = [10, 16]
    if visual_route != "type" and args.image_interval and args.image_interval <= 10:
        total_seconds = duration if test_segment else minutes * 60
        expected = max(2, int((total_seconds + args.image_interval - 1) // args.image_interval))
        scene_range = [max(2, expected - 2), expected + 12]

    name = args.name.strip() or f"{safe_name(title)}-{date.today().isoformat()}"
    target = unique_dir(EPISODES, safe_name(name))
    target.mkdir(parents=True)

    audio_target = target / f"audio{audio.suffix.lower()}"
    shutil.copy2(audio, audio_target)
    shutil.copy2(srt, target / "subtitles.srt")
    final_name = ""
    if script is not None:
        shutil.copy2(script, target / "final.txt")
        final_name = "final.txt"

    for optional in ("map.json", "outline.json"):
        candidate = folder / optional
        if candidate.is_file():
            shutil.copy2(candidate, target / optional)

    meta = {
        "episode": target.name,
        "book_title": title,
        "author": author,
        "column": column,
        "brand": brand,
        "mode": mode,
        "visual_route": visual_route,
        "preset": preset,
        "image_interval_seconds": args.image_interval,
        "overlay_style": args.overlay_style,
        "overlay_opacity": args.overlay_opacity,
        "subtitle_mode": args.subtitle_mode,
        "series": args.series,
        "series_episode": args.series_episode,
        "aspects": ["9:16", "16:9"],
        "target_minutes": minutes,
        "spoiler_policy": args.spoiler_policy,
        "source_level": args.source_level,
        "test_segment": test_segment,
        "scene_range": scene_range,
        "audio_file": audio_target.name,
        "srt_file": "subtitles.srt",
        "final_file": final_name,
        "created": date.today().isoformat(),
    }
    write_json(target / "meta.json", meta)

    if args.images_from and visual_route != "type":
        image_source = Path(args.images_from).expanduser().resolve()
        if image_source.is_dir():
            image_target = target / "video" / "images"
            image_target.mkdir(parents=True, exist_ok=True)
            copied = 0
            for item in sorted(image_source.iterdir()):
                if item.is_file() and item.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    shutil.copy2(item, image_target / item.name)
                    copied += 1
            print(f"  预生产图片：复制 {copied} 张到 video/images/")
        else:
            print(f"  预生产图片目录不存在，跳过：{image_source}")

    print(f"\n已建期：{target}")
    print(f"  音频：{audio.name}（{duration:.3f}s）")
    print(f"  SRT：{srt.name}")
    print(f"  稿子：{script.name if script else '没有（文字将取自 SRT）'}")
    route_name = {"cinema": "B 电影感", "classic": "A 公版画", "type": "C 纯排版"}.get(visual_route, visual_route)
    print(f"  视觉路线：{route_name}；预设：{preset}；场景数：{scene_range[0]}–{scene_range[1]}")
    print(f"  图片间隔：约 {args.image_interval:g} 秒/张；粒子：{args.overlay_style}（{args.overlay_opacity:.0%}）；字幕：{args.subtitle_mode}")

    print("\n开始入库检查…\n")
    result = subprocess.run([sys.executable, str(PREPARE), "--episode", str(target)], cwd=str(ROOT))

    relative = target.relative_to(ROOT)
    print("\n下一步，把这句话发给视频智能体：\n")
    print(f"  读 WORKFLOW.md，输入目录是 {relative}。先做 Step 1，写完停下。")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
