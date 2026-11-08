"""录音前预生产：只有口播稿，也能先建图片提示词目录。

用法：
    python tools/new_preproduction.py "D:\\书\\羊脂球第一段.txt" \
        --title 羊脂球 --author 莫泊桑 --target-minutes 15
    python tools/new_preproduction.py "某段口播稿.txt" --yes

产出：
    preprod/<书名-日期>/
      script.txt
      meta.json
      images/            # GPT 生成的图先丢这里
      image_prompts.txt  # 智能体写
"""

from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from common import ROOT, safe_name, unique_dir, write_json

PREPROD = ROOT / "preprod"
SKIP = ("readme", "说明", "meta", "publish", "image_prompts", "requirements")


def pick_script(raw: str, auto: bool) -> Path | None:
    path = Path(raw).expanduser().resolve()
    if path.is_file() and path.suffix.lower() == ".txt":
        return path
    folder = path if path.is_dir() else path.parent
    candidates = [
        item for item in folder.iterdir()
        if item.is_file() and item.suffix.lower() == ".txt"
        and not any(word in item.name.lower() for word in SKIP)
    ]
    if not candidates:
        return None
    for name in ("final.txt", "script.txt", "口播稿.txt"):
        for item in candidates:
            if item.name.lower() == name.lower():
                return item
    if len(candidates) > 1 and not auto:
        print(f"\n找到 {len(candidates)} 个 txt：")
        for index, item in enumerate(candidates, start=1):
            print(f"  {index}. {item.name}")
        while True:
            value = input(f"选第几个 [1]：").strip() or "1"
            if value.isdigit() and 1 <= int(value) <= len(candidates):
                return candidates[int(value) - 1]
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="录音前预生产：口播稿 → 图片提示词目录")
    parser.add_argument("script", nargs="?", default="", help="口播稿 txt，或包含 txt 的文件夹")
    parser.add_argument("--yes", action="store_true", help="全部用默认值")
    parser.add_argument("--name", default="", help="预生产目录名，默认 <书名>-<日期>")
    parser.add_argument("--title", default="", help="书名")
    parser.add_argument("--author", default="未标注")
    parser.add_argument("--column", default="听故事", choices=("读懂", "听故事"))
    parser.add_argument("--visual-route", default="cinema", choices=("cinema", "classic", "type"))
    parser.add_argument("--target-minutes", type=float, default=0)
    parser.add_argument("--image-interval", type=float, default=5,
                        help="每张图大约多少秒；5=密集模式，0=常规 30–90 秒")
    args = parser.parse_args()

    raw = args.script.strip().strip('"')
    if not raw and not args.yes:
        raw = input("把口播稿 txt（或文件夹）拖进来：").strip().strip('"')
    if not raw:
        print("没有输入口播稿。")
        return 2
    script = pick_script(raw, args.yes)
    if script is None or not script.is_file():
        print(f"找不到口播稿 txt：{raw}")
        return 2

    text = script.read_text(encoding="utf-8-sig", errors="replace")
    chars = sum(1 for char in text if not char.isspace())
    title = args.title.strip() or script.stem
    if not args.yes and not args.title:
        title = input(f"书名 [{title}]：").strip() or title
    author = args.author
    if not args.yes and args.author == "未标注":
        author = input("作者 [未标注]：").strip() or author
    minutes = args.target_minutes or max(1, round(chars / 250))
    route = args.visual_route
    preset = "v0" if route == "type" else "v1lite"

    name = args.name.strip() or f"{safe_name(title)}-{date.today().isoformat()}"
    target = unique_dir(PREPROD, safe_name(name))
    (target / "images").mkdir(parents=True)
    shutil.copy2(script, target / "script.txt")
    for optional in ("outline.json", "map.json"):
        candidate = script.parent / optional
        if candidate.is_file():
            shutil.copy2(candidate, target / optional)
    write_json(target / "meta.json", {
        "episode": target.name,
        "book_title": title,
        "author": author,
        "column": args.column,
        "visual_route": route,
        "preset": preset,
        "image_interval_seconds": args.image_interval,
        "target_minutes": minutes,
        "status": "preproduction",
        "script_file": "script.txt",
        "created": date.today().isoformat(),
    })

    route_name = {"cinema": "B 电影感", "classic": "A 公版画", "type": "C 纯排版"}.get(route, route)
    print(f"\n预生产目录：{target}")
    print(f"  口播稿：{script.name}（{chars} 字，约 {minutes} 分钟）")
    print(f"  视觉路线：{route_name}；图片间隔：约 {args.image_interval:g} 秒/张")
    print(f"  图片先放：{target / 'images'}")
    print("\n下一步，把这句话发给图片智能体：\n")
    print(f"  读 WORKFLOW.md 和 prompts/00_preproduction.md，输入目录是 {target.relative_to(ROOT)}。先写 image_prompts.txt，写完停下。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
