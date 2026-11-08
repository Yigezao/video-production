# 书籍解说视频 · 智能体流水线

不跑平台重管线：**代码做解析/检查/渲染，模型步骤交给智能体。** 智能体读 `WORKFLOW.md` 干活，文件是唯一状态。

## 一句话

音频和 SRT 已经录好、字幕已经对齐；这个流水线只做：**SRT → 句子表 → 视觉导演 → 卡片/图片 → 双比例 MP4 → 质检 → 发布**。

## 视觉路线（默认 B 电影感）

Step 2 智能体会问一次，默认选 B：

| 路线 | `visual_route` | 画面 |
|---|---|---|
| **B 电影感（默认）** | `cinema` | 4–6 张 AI 电影感静帧 + 程序卡；冷灰蓝、35mm 颗粒、无正脸 |
| A 公版画 | `classic` | 4–6 张公有领域绘画/版画 + 程序卡 |
| C 纯排版 | `type` | 0 张图，全靠卡片 |

三条都已跑通，样例在 `episodes/羊脂球-第一段-A/B/C-*/video/out/`；对比看 `episodes/对比-A-B-C.jpg`。

口播念到“我是……今天讲《书名》”时，Step 2 会在这几句上放一张 `book_card`。位置由 SRT/`from/to` 决定，通常不是第一张。

- `cinema`：在 `image_prompts.txt` 末尾额外生成 1 张 `book_card.png`——书在中间、封面空白有纹理、上下留白；AI 不在书封上写字，书名/作者由程序叠在画面上下。
- `classic/type`：可以用公版书/纸底，程序绘制 fallback。
- 书封卡图固定命名 `book_card.png`，不参与 001–0NN 的插画时间顺序；视频位置仍由 plan 的 `from/to` 决定。

B 的图不用智能体自己画：Step 3 它会写 `video/image_prompts.txt`，你复制到 GPT 网页版生成，**直接丢进 `video/images/`，名字不用改**。智能体会跑 `tools/rename_images.py`，按 GPT 文件名里的时间后缀排序，自动命名成 `01_xxx.png`、`02_xxx.png`……所有期通用。

### 图片数量与停留（默认 5 秒/张）

| 模式 | 每张 | 10 分钟 | 15 分钟 | 25 分钟 |
|---|---:|---:|---:|---:|
| **密集（默认）** | 约 5 秒 | ~120 张 | ~180 张 | ~300 张 |
| 常规省图 | 30–90 秒 | 3–5 张 | 4–6 张 | 6–8 张 |

`meta.image_interval_seconds` 默认 5。算出来超过 60 张，智能体会先问：继续 5 秒 / 改 8–10 秒 / 只做关键节点。

### 长篇系列 · 复用图

长篇书拆多期时，先建：

```text
series/<书名>/
  series.json
  asset_manifest.json
  assets/reusable/      # 你生成一次，智能体只读
```

- 能复用：环境、建筑、天气、地图、物件、群体剪影
- 不能乱用：具体人物正脸/特写、具体事件画面、和旁白季节/地点矛盾的图
- 每张图在 `asset_manifest.json` 登记 `id / kind / reuse / allowed_episodes / avoid`
- plan 里复用场景写 `asset_id`
- 智能体不重做、不覆盖复用图；不确定就停下问
- 长篇系列不碰 5 秒/张，每期 4–6 张唯一图，30–90 秒/张

模板在 `series/_模板/`。`check.py` 会检查 `asset_id` 是否存在、文件在不在、本期是否允许。

### 粒子与 30 秒试用

渲染前智能体会问三件事：

1. 加粒子吗？`dust` 灰尘 / `snow` 雪 / `embers` 火星 / 不加（默认不加）
2. 字幕烧进视频，还是只要视频+音频、字幕后期自己加？（默认烧）
3. 先出 30 秒试用，还是直接全片？（默认先试用）

粒子是程序生成的黑色叠层，用 screen 混合，不依赖外部素材；不透明度默认 0.22。试用只渲染开头 30 秒 + 一个中段 + 结尾，只用到一部分图片，不会重新生成图片。

### 字幕

- 9:16 和 16:9 都用 **64px**，描边 3px；比旧版 52/46 明显大，手机上看得清
- 9:16 每行 ≤14 汉字，16:9 每行 ≤20 汉字
- `meta.subtitle_mode=burn`：烧进视频，同时导出 `out/subtitles.srt`
- `meta.subtitle_mode=none`：只出画面+音频，不烧字幕；仍然导出外挂 SRT，后期自己加

### 视频封面

- 9:16 1080×1920（抖音主封面）；16:9 1920×1080（B 站）
- 书名《书名》必须最大，9:16 约 150–180px，最多 2 行
- 钩子 ≤14 字，作者、栏目照写；不剧透、不标题党
- 背景优先用本期第一张插画，压暗后放白字；没有插画就用纸底黑字
- 文字全部程序绘制，不让 AI 生成中文
- 9:16 底部 260px、右侧 120px 不放关键信息
- 输出 `video/out/cover_9x16.png`、`cover_16x9.png`，同时写 `thumb_*.png`
- `publish.md` 的封面大字直接复用 `video_plan.json` 的 `cover.line`
- 示例：`docs/cover.example.9x16.png`、`docs/cover.example.16x9.png`

### 平台比例

| 平台 | 比例 | 尺寸 |
|---|---|---|
| 抖音 / 视频号 / Reels | **9:16** | 1080×1920 |
| B站 / YouTube | 16:9 | 1920×1080 |
| 小红书图文/视频 | 3:4 或 4:5 | 1080×1440 / 1080×1350 |

抖音不是 16:9，16:9 是 B 站/YouTube 的。只发抖音就把 `meta.aspects` 改成 `["9:16"]`，图片提示词写竖构图 9:16；要双平台就保持图片 1:1 母版，渲染时各裁一版。

### 录音前就能先做图

WAV / SRT 还没出来时，可以只凭口播稿先写图片提示词：

```bash
python tools/new_preproduction.py "口播稿.txt" --title 书名 --author 作者
```

产物在 `preprod/<书名-日期>/`：`script.txt`、`image_prompts.txt`、`images/`。等录完音、导出 WAV+SRT，用 `new_episode.py --images-from preprod/<期名>/images` 把图带进正式期，再做时间轴。

## 输入要什么

```text
episodes/<书名-日期>/
  audio.wav          必需：已录好的音频
  subtitles.srt      必需：时间来源，必须和音频同一版
  final.txt          强烈建议：口播稿全文，文字基准
  map.json           可选：故事地图/人物表
  outline.json       可选：六段大纲
  meta.json          建期时自动生成
```

**只给音频文件夹 + SRT 够吗？**

- 跑通流程：够。
- 正式一期：最好三样都给。SRT 是时间，`final.txt` 是文字；语音识别生成的 SRT 可能有同音错字，只靠 SRT 字幕会错。
- `D:\my_Software\Audacity\导出音频\羊脂球` 那段 23.5 秒（WAV + SRT + 第一段 txt）**够做冒烟测试，不够做完整一期**。完整一期要 10–25 分钟音频和对应全文。

## 快速开始

### 1. 建期（把音频文件夹拖到 bat 上，或跑命令）

```bash
python tools/new_episode.py "D:\my_Software\Audacity\导出音频\羊脂球" --yes
```

它会找文件夹里的音频、SRT、txt，复制到 `episodes/<书名-日期>/`，写 `meta.json`，并跑入库检查。

### 2. 把这句话发给视频智能体

```text
读 WORKFLOW.md，输入目录是 episodes/羊脂球-2026-10-25。先做 Step 1，写完停下。
```

之后每一步它都会落盘、跑检查、停下汇报；你说「继续」再做下一步。

### 3. 手动检查

```bash
python tools/doctor.py
python tools/check.py --episode episodes/羊脂球-2026-10-25 --stage all
```

## 目录

```text
Video_Production/
  WORKFLOW.md          智能体流程（先读这个）
  README.md            本文件
  prompts/             00 预生产 / 01 入库 / 02 导演 / 03 素材 / 04 渲染 / 05 质检 / 06 发布
  tools/               prepare.py、check.py、new_episode.py、new_preproduction.py、rename_images.py、doctor.py
  video_engine/        CLI：卡片、渲染、质检（已实现）
  docs/                原视频方案 + 引擎实现规格
  episodes/            每期输入和产物
  preprod/             录音前的口播稿 + 图片提示词 + GPT 图
  新建一期.bat          拖文件夹建期
```

## 现在什么能用、什么待补

| 项 | 状态 |
|---|---|
| 入库（SRT 解析、与稿子对齐、句子表、五项检查） | **可用** |
| `check.py` 五阶段机械检查 | **可用** |
| 建期 / 环境自检 | **可用** |
| 程序卡渲染 `video_engine/cards.py` | **可用** |
| 双比例渲染 `video_engine/render.py`（含 30 秒样片） | **可用** |
| 质检 `video_engine/qc.py` | **可用** |

示例期已跑通：9:16 与 16:9 各 23.63 秒，QC 21 项 0 fail；产物在
`episodes/羊脂球-第一段/video/out/`，质检报告在 `video/qc_report.json`。

```bash
python -m video_engine cards  --episode episodes/羊脂球-第一段
python -m video_engine render --episode episodes/羊脂球-第一段 --aspect both
python -m video_engine qc     --episode episodes/羊脂球-第一段
```

本机环境：Python 3.12.10、Pillow 12.3.0、FFmpeg 7.1（`D:\ffmpeg\bin\ffmpeg.exe`）；没有 ffprobe（不阻断，时长探测会退回 `ffmpeg -i`）；中文字体在 `C:\Windows\Fonts`。

## 示例期

`episodes/羊脂球-第一段/` 已经建好：

- 23.5 秒 WAV + 15 条 SRT + 第一段口播稿；
- `video/sentences.json` 13 句；
- `video/video_plan.json` 4 个场景，4 张占位图；
- 这是测试段，不是完整一期；用来验证流程，不用于发布。

## 铁律

- 音频不动：不裁、不加速、不变调、不改响度。
- SRT 只给时间；文字以 `final.txt` 为准。
- 卡片文字程序绘制，不让 AI 生成中文；9:16 和 16:9 两套排版，不互相裁切。
- 每步跑检查，有 fail 先修，不要假装通过。
