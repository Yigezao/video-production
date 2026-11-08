"""video_engine CLI。

    python -m video_engine doctor
    python -m video_engine check  --episode episodes/xxx --stage all
    python -m video_engine cards  --episode episodes/xxx
    python -m video_engine render --episode episodes/xxx --aspect both --preview 30
    python -m video_engine qc     --episode episodes/xxx

cards / render / qc 已实现；check / doctor 复用 tools/。
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from .config import ROOT, episode_dir


def run_check(episode: str, stage: str) -> int:
    command = [sys.executable, str(ROOT / "tools" / "check.py"),
               "--episode", str(episode_dir(episode)), "--stage", stage]
    return subprocess.run(command, cwd=str(ROOT)).returncode


def run_doctor() -> int:
    sys.path.insert(0, str(ROOT))
    from tools.doctor import main as doctor_main

    return doctor_main()


def _guard(action: str):
    print(f"{action} 尚未实现。")
    print("实现规格：docs/ENGINE_SPEC.md")
    print("当前可用：python -m video_engine doctor / check")
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="video_engine", description="书籍解说视频引擎")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="环境自检")

    check = sub.add_parser("check", help="机械检查")
    check.add_argument("--episode", required=True)
    check.add_argument("--stage", default="all",
                       choices=("ingest", "plan", "assets", "render", "publish", "all"))

    cards = sub.add_parser("cards", help="渲染程序排版卡（待补）")
    cards.add_argument("--episode", required=True)
    cards.add_argument("--force", action="store_true")

    render = sub.add_parser("render", help="渲染成片（待补）")
    render.add_argument("--episode", required=True)
    render.add_argument("--aspect", default="both", choices=("both", "9:16", "16:9"))
    render.add_argument("--preview", type=int, default=0, help="只渲染开头 N 秒样片")
    render.add_argument("--force", action="store_true")

    qc = sub.add_parser("qc", help="质检（待补）")
    qc.add_argument("--episode", required=True)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor()
    if args.command == "check":
        return run_check(args.episode, args.stage)

    episode = episode_dir(args.episode)
    if args.command == "cards":
        from .cards import render_cards

        try:
            count = render_cards(episode, force=args.force)
        except (NotImplementedError, FileNotFoundError, RuntimeError) as exc:
            print(exc)
            return _guard("cards")
        print(f"生成 {count} 张卡片")
        return 0

    if args.command == "render":
        from .render import render

        try:
            count = render(episode, aspects=args.aspect, preview=args.preview, force=args.force)
        except (NotImplementedError, FileNotFoundError, RuntimeError) as exc:
            print(exc)
            return _guard("render")
        print(f"生成 {count} 个成片")
        return 0

    if args.command == "qc":
        from .qc import run_qc

        try:
            report = run_qc(episode)
        except (NotImplementedError, FileNotFoundError, RuntimeError) as exc:
            print(exc)
            return _guard("qc")
        print(report.get("summary", "质检完成"))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
