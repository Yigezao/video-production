# 交接说明

> 这个目录是书籍解说视频的智能体流水线。入口是 `WORKFLOW.md`。本文件讲「现在做到哪、怎么验收、还有什么可选改进」。
>
> **视觉路线默认 B `cinema`（电影感 AI 静帧）。** Step 2 只问用户一次；用户不选就按 `cinema`。A=`classic` 公版画，C=`type` 纯排版，三条都已跑通。

## 已完成（可直接跑）

- `tools/prepare.py`：读音频 + SRT + `final.txt`，全局单调对齐，产出 `video/sentences.json`、`check_report.json`、`ingest_report.md`。
- `tools/check.py`：ingest / plan / assets / render / publish 五阶段机械检查，写 `video/qa.json`。
- `tools/new_episode.py`：拖文件夹建期，自动复制三件套、写 `meta.json`、跑入库；支持 `--images-from` 带预生产图。
- `tools/new_preproduction.py`：录音前只有口播稿时先建 `preprod/<期>/`，写图片提示词、收 GPT 图。
- `tools/rename_images.py`：把 GPT 下载的时间后缀图片按顺序改名成 `01_xxx.png` 等；所有期通用。
- `prompts/00_preproduction.md`：录音前只按口播稿写 `image_prompts.txt`，不写 from/to。
- `tools/doctor.py`、`video_engine` CLI / config / doctor / check。
- `prompts/03_assets.md`：B 默认走 GPT 网页版交接——智能体先写 `video/image_prompts.txt`，用户生成后直接丢进 `video/images/`，智能体用 `tools/rename_images.py` 按时间后缀自动命名。所有期通用。
- `video_engine/cards.py`：七类程序卡（含 book_card 书封卡）+ 品牌底，9:16 / 16:9，自动换行、hash 缓存。
- book_card：cinema 用 AI 生成的 `images/book_card.png`（书在中间、封面空白、上下留白）+ 程序文字；位置由 SRT `from/to` 决定，不参与插画时间顺序。
- `video_engine/cover.py`：从 `video_plan.json` 的 `cover` 生成 9:16 / 16:9 平台封面，大字书名 + 钩子 + 作者；文字程序绘制。
- `video_engine/render.py`：分段渲染、缓慢运动、concat、ASS 烧录、AAC 音频、30 秒样片、缩略图、manifest；慢速运动用 4x 超采样防抖。
- `video_engine/overlays.py`：程序生成 dust/snow/embers 粒子叠层，screen 混合；Step 4 问用户加不加。
- 渲染前会问：加不加粒子、字幕烧不烧、先 30 秒试用还是直接全片；试用只影响渲染，不影响已生成的图片。
- 长篇系列：`series/<书名>/asset_manifest.json` 管复用图；plan 用 `asset_id`；`check.py` 校验存在性/允许期数。用户生成一次，智能体只读。
- 字幕 9:16 / 16:9 都是 64px、描边 3px；`subtitle_mode=none` 时只出画面+音频，外挂 SRT 仍导出。
- `video_engine/qc.py`：时长、分辨率、黑帧、静音尾巴、响度、首尾亮度、字幕烧录抽检。

## 验收命令

```bash
python -m video_engine doctor
python tools/check.py --episode episodes/羊脂球-第一段 --stage all
python -m video_engine cards  --episode episodes/羊脂球-第一段
python -m video_engine render --episode episodes/羊脂球-第一段 --aspect both
python -m video_engine qc     --episode episodes/羊脂球-第一段
```

示例期结果：

```text
ingest / plan / assets / render / publish  全部没有 fail
video_9x16.mp4   23.63s  1080x1920
video_16x9.mp4   23.63s  1920x1080
QC               21 项，0 fail，0 warn
```

30 秒样片（音频短于 30 秒时自动全片）：

```bash
python -m video_engine render --episode <期> --aspect both --preview 30
```

输出：

```text
video/preview/preview_9x16.mp4
video/preview/preview_16x9.mp4
```

## 产物位置

```text
episodes/<期>/
  video/sentences.json
  video/video_plan.json
  video/cards/*.png
  video/images/*.png
  video/subs/*.ass / subtitles.srt
  video/preview/*.mp4
  video/out/video_9x16.mp4
  video/out/video_16x9.mp4
  video/out/thumb_9x16.png / thumb_16x9.png
  video/out/subtitles.srt
  video/qc_report.json
  video/render_manifest.json
```

## 本机环境

- Python 3.12.10，Pillow 12.3.0。
- FFmpeg 7.1：`D:\ffmpeg\bin\ffmpeg.exe`（含 libass/libx264/AAC）。
- 没有 `ffprobe`；`tools/common.py` 已用 `ffmpeg -i` 兜底。
- 字体：`C:\Windows\Fonts\NotoSansSC-VF.ttf`、`NotoSerifSC-VF.ttf`。

## 可选改进

- 补 `ffprobe.exe` 到 `D:\ffmpeg\bin`。
- 把 Noto Sans/Serif SC 放进 `fonts/` 随程序打包。
- 卡片版式要更复杂时，再换 HTML/CSS → PNG（Playwright）。
- 需要背景音乐、转场、更多动效时，在 `render.py` 里加，不改 `prepare.py` 和 `check.py` 的时间规则。

## 不要动

- `audio.*`、`subtitles.srt`、`final.txt`、`map.json`、`outline.json`。
- `tools/prepare.py` 的时间规则；SRT 时间不能被手动改。
- `video_plan.json` 的语义；引擎只消费，不创作。
- `prompts/` 的步骤顺序；要改先问用户。
