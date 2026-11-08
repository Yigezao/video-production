"""按时间顺序把 GPT 生成的图片重命名成 video_plan 要的文件名。

GPT 网页版下载的图片常叫：
    ChatGPT Image 2026年10月25日 16_08_12.png
时间后缀就是生成顺序，也就是视频场景顺序。这个脚本：
    1. 读 video_plan.json 里 illustration 场景的顺序；
    2. 找 video/images/ 里还没命名的图片；
    3. 按文件名时间（没有就按文件修改时间）排序；
    4. 依次改名成 01_xxx.png、02_xxx.png ...
    5. 写 video/image_map.json 留底。

用法：
    python tools/rename_images.py --episode episodes/羊脂球-第一段-试跑 --dry-run
    python tools/rename_images.py --episode episodes/羊脂球-第一段-试跑
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_datetime(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def parse_timestamp(name: str) -> datetime | None:
    stem = Path(name).stem
    # 2026年10月25日 16_08_12 / 2026年10月25日 16:08:12
    match = re.search(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})[_\-. :](\d{2})[_\-. :](\d{2})",
        stem,
    )
    if match:
        return _make_datetime(*map(int, match.groups()))
    # 2026-10-25 16_08_12 / 2026_10_25_16_08_12
    match = re.search(
        r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})[ _T-]+(\d{1,2})[-_.:](\d{2})[-_.:](\d{2})",
        stem,
    )
    if match:
        return _make_datetime(*map(int, match.groups()))
    # ChatGPT Image Oct 25, 2026, 04_08_12 PM
    match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})"
        r"[,\s]+(\d{1,2})[_:](\d{2})[_:](\d{2})",
        stem,
        re.I,
    )
    if match:
        month_name, day, year, hour, minute, second = match.groups()
        return _make_datetime(int(year), MONTHS[month_name[:3].lower()], int(day),
                              int(hour), int(minute), int(second))
    return None


def sort_key(path: Path) -> float:
    parsed = parse_timestamp(path.name)
    if parsed is not None:
        return parsed.timestamp()
    return path.stat().st_mtime


def main() -> int:
    parser = argparse.ArgumentParser(description="按时间顺序重命名 GPT 生成的图片")
    parser.add_argument("--episode", required=True)
    parser.add_argument("--dry-run", action="store_true", help="只打印映射，不改名")
    parser.add_argument("--force", action="store_true", help="目标文件已存在时覆盖")
    args = parser.parse_args()

    episode = Path(args.episode)
    if not episode.is_absolute():
        episode = (Path.cwd() / episode).resolve()
    plan_path = episode / "video" / "video_plan.json"
    if not plan_path.is_file():
        print(f"缺少 video_plan.json：{plan_path}")
        return 2
    plan = read_json(plan_path)
    expected = [
        scene for scene in plan.get("scenes", [])
        if isinstance(scene, dict) and scene.get("type") == "illustration" and scene.get("image")
    ]
    if not expected:
        print("这一期没有 illustration 场景，不需要重命名。")
        return 0

    images_dir = episode / "video" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {Path(str(scene["image"])).name for scene in expected}
    candidates = sorted(
        [
            path for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS and path.name not in expected_names
        ],
        key=sort_key,
    )

    if not candidates:
        missing = [Path(str(scene["image"])).name for scene in expected
                   if not (episode / "video" / str(scene["image"])).is_file()]
        if not missing:
            print("图片已经是目标文件名，不需要处理。")
            return 0
        print("没有找到待命名的图片；缺少：")
        for name in missing:
            print(f"  - {name}")
        return 1

    if len(candidates) != len(expected):
        print(f"待命名图片 {len(candidates)} 张，plan 需要 {len(expected)} 张，数量对不上，先别改名。")
        print("待命名：")
        for path in candidates:
            print(f"  - {path.name}")
        print("plan 需要：")
        for scene in expected:
            print(f"  - {scene.get('id')}: {scene.get('image')}")
        return 1

    mapping = []
    for index, (scene, source) in enumerate(zip(expected, candidates), start=1):
        target = episode / "video" / str(scene["image"])
        target.parent.mkdir(parents=True, exist_ok=True)
        mapping.append({
            "order": index,
            "scene_id": scene.get("id"),
            "from": scene.get("from"),
            "to": scene.get("to"),
            "original": source.name,
            "target": str(Path(str(scene["image"])).as_posix()),
            "timestamp": parse_timestamp(source.name).isoformat(sep=" ")
            if parse_timestamp(source.name) else datetime.fromtimestamp(source.stat().st_mtime).isoformat(sep=" "),
        })
        print(f"{index}. {source.name}  ->  {scene.get('image')}")

    if args.dry_run:
        print("\n[dry-run] 没有改名。确认顺序后去掉 --dry-run 再跑。")
        return 0

    for item, source in zip(mapping, candidates):
        target = episode / "video" / item["target"]
        if target.exists():
            if not args.force:
                print(f"目标已存在：{target}；加 --force 覆盖，或先移走旧图。")
                return 1
            target.unlink()
        shutil.move(str(source), str(target))

    write_json(episode / "video" / "image_map.json", {
        "episode": plan.get("episode") or episode.name,
        "order": "按文件名时间（没有则按文件修改时间）升序",
        "mapping": mapping,
    })
    print(f"\n已重命名 {len(mapping)} 张；映射写到 video/image_map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
