# 渲染引擎实现规格

> **方案原文在 `docs/方案/`，冲突时以原文为准。**
> `cards.py`、`render.py`、`qc.py` 已实现并实测通过；本文件保留为接口说明和改动约束。
> 三个文件的函数签名不要随意改；要改先看 `WORKFLOW.md` 和示例期的验收结果。

## 1. 输入与输出

```text
输入：
  <期>/meta.json
  <期>/audio.wav | audio.mp3 ...
  <期>/video/sentences.json
  <期>/video/video_plan.json
  <期>/video/images/*.png            # V1-lite / V1

输出：
  <期>/video/cards/V01_9x16.png
  <期>/video/cards/V01_16x9.png
  <期>/video/subs/subtitles_9x16.ass
  <期>/video/subs/subtitles_16x9.ass
  <期>/video/subs/subtitles.srt
  <期>/video/segs/V01_9x16.mp4 ...
  <期>/video/preview/preview_9x16.mp4
  <期>/video/out/video_9x16.mp4
  <期>/video/out/video_16x9.mp4
  <期>/video/out/cover_9x16.png
  <期>/video/out/cover_16x9.png
  <期>/video/out/thumb_9x16.png
  <期>/video/out/thumb_16x9.png
  <期>/video/render_manifest.json
  <期>/video/qc_report.json
```

## 2. `cards.py`（Pillow）

已写好 `card_jobs(loaded)`，列出所有需要生成的卡片。

### 2.1 版式

| 类型 | 9:16 | 16:9 | 元素 |
|---|---|---|---|
| `title_card` | 纸底 | 纸底 | 栏目名、书名（宋体 120–150px）、钩子 ≤12 字、折角 |
| `book_card` | AI 书封图 + 压暗 | 同 | `cinema` 用 AI 生成的 `images/book_card.png`（书在中间、封面空白、上下留白）+ 程序标题/作者；`classic/type` 用程序书 fallback。位置由 SRT `from/to` 决定 |
| `section_card` | 纸底/墨底 | 同 | 大号编号 01、章节名 ≤8 字、说明 ≤16 字 |
| `quote_card` | 纸底/墨底 | 同 | 金句 ≤18 字、细线、出处小字、`paraphrase` 标「转述」 |
| `character_card` | 下三分之一 | 同 | ≤4 人，人名 40–48px，身份 28–32px |
| `timeline_card` | 下三分之一/全屏 | 同 | ≤4 节点，label ≤8 字 |
| `end_card` | 墨底 | 墨底 | 品牌、栏目、下期见、互动问题、折角+印章 |
| `background` | 纸底+纸纹 | 同 | 无文字或只放栏目名小字（程序生成，不在这里画） |

- 色板：墨 `#17181C`、纸 `#F5EFE3`、朱砂 `#C84630`（≤5%）、铜 `#B08A57`、灰纸 `#D8CDBC`。
- 字体：`config.font_path("title")` / `config.font_path("body")`。
- 每张卡同时输出 9:16（1080×1920）和 16:9（1920×1080），**不互相裁切**。
- 文字自动换行、自动缩字号，最小 28px；仍溢出就截断并在图上标红（同时打印警告）。
- 卡片元素只允许：栏目名、编号、标题、一句话、折角、印章、细线。不要插画、二维码。

### 2.2 函数

```python
def render_cards(episode_path: str | Path, force: bool = False) -> int:
    ...
```

- 返回生成数量。
- 按内容 hash 缓存，未变化跳过；`force=True` 全量重渲染。
- 背景/插画不需要 PNG 卡片；`background` 由 render 程序生成。
- 保存 PNG 时保留 alpha：`lower_third` 卡是透明底，转 RGB 会把透明区压成黑色。

## 2.3 视频封面（`cover.py`）

- 每期从 `video_plan.json` 的 `cover` 生成两张：`out/cover_9x16.png`（1080×1920）、`out/cover_16x9.png`（1920×1080）。
- 书名最大（9:16 约 150–180px），钩子 ≤14 字，作者/栏目照写。
- 背景优先用 `cover.image` 或第一张插画，压暗后放白字；没有图就用纸底黑字。
- 文字全部程序绘制；不让 AI 生成中文。
- 9:16 底部 260px、右侧 120px 不放关键信息；不剧透、不标题党。
- 同时复制成 `thumb_9x16.png` / `thumb_16x9.png`。

## 3. `render.py`（FFmpeg）

### 3.1 时间

- 每场 `from/to` 用 `sentences.json` 换成秒：`start = sentences[from].start`，`end = sentences[to].end`。
- 相邻场景首尾相接；总长必须 ≥ 音频总长 − 0.2s。
- 卡片只显示 `hold_seconds`；到时切品牌底，场景仍覆盖原句子。
- `lower_third` 是叠加，不切整帧。

### 3.2 分段

- 每场一段 MP4：图片/卡片 + 缓慢运动（`zoompan` / `crop`），30fps，1080p，`libx264`，`-preset veryfast -crf 22`，`yuv420p`。
- 运动幅度 2–6%；只用一种运动；转场 `fade` 0.3s。
- **慢速运动必须超采样**：`zoompan` 的 x/y 是整数像素，直接 1080p 输出会 1px/2px 阶梯抖动。当前实现是 4x 输入 → 2x zoompan 输出 → Lanczos 下采样到目标分辨率；不要改回 1x。
- 每个场景只做一个方向，推近/拉远/平移单调；1 秒内不反向、不来回。
- 每段渲染后探测时长，差 >0.1s 重渲染。
- 所有分段同分辨率、同 fps、同 pix_fmt、同编码后再 concat。
- 缺图：用程序生成的品牌底兜底，记日志，不失败。

### 3.3 合成

```text
1) 算 segs 总长，与音频比
2) 视频短了：延长最后一段到 audio_duration + 0.2s
3) 视频长了：合成时 -t audio_duration 截视频（不截音频）
ffmpeg -f concat -safe 0 -i segs/list_9x16.txt -i audio.wav \
  -vf "ass=subs/subtitles_9x16.ass:fontsdir=fonts" \
  -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 192k -ar 48000 -t <audio_duration> out/video_9x16.mp4
```

**不要无条件用 `-shortest`。**

### 3.4 样片

- `--preview N`：只渲染开头 N 秒 + 一个章节 + 结尾，双比例。
- 音频短于 N 时自动改全片。
- 输出 `video/preview/preview_9x16.mp4`、`preview_16x9.mp4`。

### 3.5 字幕

| 项 | 9:16 | 16:9 |
|---|---|---|
| PlayRes | 1080×1920 | 1920×1080 |
| Fontsize | 64 | 64 |
| MarginV | 260 | 120 |
| MarginL/R | 80 | 120 |
| Outline | 2 | 2 |
| Alignment | 2 | 2 |

- 字体：Noto Sans SC Medium；白字 + 2px 墨色描边。
- 不做逐字动画、花字、emoji。
- 同时导出 `out/subtitles.srt`。

### 3.6 函数

```python
def render(episode_path, aspects="both", preview=0, force=False) -> int:
    ...
```

- `aspects`：`both` / `9:16` / `16:9`。
- 返回生成的 MP4 数量。

## 4. `qc.py`

```python
def run_qc(episode_path) -> dict:
    ...
```

至少检查并写 `video/qc_report.json`：

- 成片时长与音频差（<0.5s 通过，<0.2s 更好）。
- 没有黑帧、静音尾巴、图片提前结束。
- 音频与原始音频同一版（时长、采样率、响度粗略对比）。
- 9:16 / 16:9 分辨率正确；抽帧看字幕在安全区。
- 首尾 3 秒不空。
- 卡片人名、书名、数字与稿子一致（能自动比对的自动比对，其余列人工项）。

## 5. `render_manifest.json`

```json
{
  "template_version": "0.1",
  "fonts": {"NotoSansSC": "sha256:..."},
  "cards": {"V01_9x16": "sha256:..."},
  "inputs": {"audio.wav": "sha256:...", "subtitles.srt": "sha256:...", "final.txt": "sha256:..."},
  "outputs": {"video_9x16": {"duration": 912.4, "sha256": "..."}},
  "ffmpeg_commands": ["..."]
}
```

用途：同一输入同一输出；改一张卡只重渲染相关段；出问题能复现。

## 6. 本机环境

- Python 3.12.10，Pillow 12.3.0。
- FFmpeg 7.1：`D:\ffmpeg\bin\ffmpeg.exe`（含 libass/libx264/AAC）。
- **没有 ffprobe**：`tools/common.py` 已用 `ffmpeg -i` 兜底；补 ffprobe 更好。
- 字体：`C:\Windows\Fonts\NotoSansSC-VF.ttf`、`NotoSerifSC-VF.ttf`。
- `config.json` 可写 `{"ffmpeg": "...", "ffprobe": "..."}` 覆盖探测。

## 7. 验收

- `python -m video_engine cards --episode episodes/羊脂球-第一段` 能出卡（该期没有卡片场景，返回 0 也算通过）。
- `python -m video_engine render --episode episodes/羊脂球-第一段 --aspect both` 能出两个 23.5 秒 MP4，时长与音频差 <0.2s。
- `python -m video_engine qc --episode ...` 写报告。
- `python tools/check.py --episode ... --stage all` 没有 fail。
- 一条命令能重渲染；缺图不整期失败。

## 8. 已实现清单

- [x] `cards.py::render_cards`：纸底/墨底模板、七类卡片、双比例、自动换行、alpha、hash 缓存。
- [x] `render.py::render`：分段、运动、concat、ASS、音频、样片、缩略图、manifest。
- [x] `qc.py::run_qc`：时长、分辨率、黑帧、静音、响度、首尾亮度、字幕烧录抽检、报告。
- [ ] 可选：补充 `fonts/`（随程序打包，避免换电脑缺字体）。
- [ ] 可选：补 `ffprobe.exe`。

> 不要改 `tools/prepare.py` 的时间规则，也不要改 `video_plan.json` 的语义；引擎只消费，不创作。
