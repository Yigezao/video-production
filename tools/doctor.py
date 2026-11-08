"""环境自检：Python / FFmpeg / ffprobe / Pillow / 中文字体。

用法：
    python tools/doctor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:  # 直接脚本运行 / 作为 tools.doctor 导入
    from .common import ROOT, find_ffmpeg, find_ffprobe
except ImportError:  # pragma: no cover
    from common import ROOT, find_ffmpeg, find_ffprobe


def line(name: str, ok: bool, detail: str) -> bool:
    print(f"  {'OK  ' if ok else 'WARN'} {name}：{detail}")
    return ok


def main() -> int:
    print("视频流水线环境自检\n")
    all_ok = True

    all_ok &= line("Python", sys.version_info >= (3, 12),
                   f"{sys.version.split()[0]}（需要 3.12+）")

    ffmpeg = find_ffmpeg()
    all_ok &= line("FFmpeg", bool(ffmpeg), ffmpeg or "没找到；装 FFmpeg 或写 config.json 的 ffmpeg 路径")

    ffprobe = find_ffprobe()
    # 没有 ffprobe 不阻断：probe_duration 会退回 ffmpeg -i
    line("ffprobe", bool(ffprobe),
         ffprobe or "没找到；时长探测会退回 ffmpeg -i（建议补 ffprobe）")

    try:
        import PIL  # noqa: F401

        line("Pillow", True, PIL.__version__)
    except Exception as exc:  # noqa: BLE001
        all_ok = False
        line("Pillow", False, f"没装或坏了：{exc}；需要 pip install pillow")

    fonts = [
        ROOT / "fonts" / "NotoSansSC-Medium.otf",
        ROOT / "fonts" / "NotoSerifSC-SemiBold.otf",
        Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"),
        Path(r"C:\Windows\Fonts\NotoSerifSC-VF.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    found = [path for path in fonts if path.is_file()]
    line("中文字体", bool(found), str(found[0]) if found else "没找到；建议把 Noto Sans/Serif SC 放进 fonts/")

    line("期目录", (ROOT / "episodes").is_dir(), str(ROOT / "episodes"))
    line("输出命令", True,
         "check: python tools/check.py --episode <期> --stage all；"
         "渲染: python -m video_engine render --episode <期> --aspect both")

    if not ffmpeg:
        print("\nFFmpeg 是本机唯一硬缺口：字幕烧录、拼接、导出都要它。")
    if not ffprobe:
        print("\n提示：只装 ffmpeg.exe 也能跑，但建议把 ffprobe.exe 放进同一个 bin 目录。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
