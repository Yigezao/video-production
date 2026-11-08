# 书籍解说视频 · 智能体工作流

> 你是执行这个工作流的智能体。**文件是唯一状态**：每一步只读上一步落盘的文件，不靠聊天记忆。每步结束必须停下汇报，等用户说继续。

## 0. 目标

输入一期已经录好的 **音频 + SRT + 口播稿**，输出：

- 抖音 9:16 MP4
- B站 16:9 MP4
- 外挂 SRT、封面图、渲染清单、质检报告

不重做音频，不做语音识别，不写口播稿。视频引擎只做三件事：**解析 SRT → 设计画面 → 渲染**。

## 1. 输入到底要什么

| 文件 | 必需 | 作用 | 说明 |
|---|---|---|---|
| `audio.wav`（或 mp3/m4a） | **是** | 唯一音频基准 | 不改、不裁、不变速、不重新降噪 |
| `subtitles.srt` | **是** | 唯一时间来源 | 必须和音频同一版；不手动挪时间 |
| `final.txt` | **完整一期强烈建议** | 唯一文字基准 | SRT 若是语音识别，会有同音错字；文字以稿子为准 |
| `map.json` / `outline.json` | 否 | 事实卡、`source_refs` | 没有就少做人物/时间线卡，不要编 |

**回答一个常见问题：只给音频文件夹和 SRT 够不够？**

- 跑通流程：够。没有 `final.txt` 时，`prepare.py` 直接用 SRT 文字，但字幕里的同音错字无法校正。
- 正式一期：**最好三样都给**（`audio` + `.srt` + `final.txt`）。音频是时间，稿子是文字，缺一不可。
- 当前测试段 `D:\my_Software\Audacity\导出音频\羊脂球`（23.5 秒，WAV + SRT + 第一段 txt）**够做冒烟测试**，不够做完整一期。完整一期需要 10–25 分钟音频和对应全文。

## 2. 目录

```text
Video_Production/
  WORKFLOW.md                 给智能体的流程协议（本文件）
  README.md                   给人看的说明
  config.json                 可选：ffmpeg / ffprobe 路径
  prompts/
    00_preproduction.md       录音前：只凭口播稿写 image_prompts.txt
    01_ingest.md              入库检查
    02_director.md            视觉导演 → video_plan.json
    03_assets.md              图片提示词 + 程序卡
    04_render.md              样片 / 全片渲染
    05_qc.md                  质检
    06_publish.md             发布包装
  tools/
    prepare.py                SRT + 音频 + 稿子 → sentences.json（不耗 token）
    check.py                  五个阶段的机械检查
    new_episode.py            建期：拖文件夹 → 复制三件套 → 跑入库
    new_preproduction.py      录音前只凭口播稿建图片预生产目录
    rename_images.py          按 GPT 图片时间后缀自动命名（所有期通用）
    doctor.py                 环境自检
  video_engine/               渲染 CLI：卡片 / 渲染 / 质检（已实现）
  docs/
    方案/                     原视频方案（00–03 + 示例 JSON）
    ENGINE_SPEC.md            渲染引擎接口说明
  episodes/
    _模板/                    输入说明
    <书名-日期>/               每期的输入和产物
  preprod/
    <书名-日期>/               录音前的口播稿 + 图片提示词 + GPT 图
  series/
    <书名>/                   长篇系列：series.json + asset_manifest.json + assets/reusable/
```

一期的目录：

```text
episodes/<书名-日期>/
  meta.json                  书名、作者、栏目、visual_route、preset、场景数、剧透、来源级别
  audio.wav                  音频（只读）
  subtitles.srt              SRT（只读）
  final.txt                  口播稿（只读；没有则文字以 SRT 为准）
  map.json / outline.json    可选
  publish.md                 ⑦ 发布信息
  video/
    sentences.json           ① 句子表：id + start/end + 稿子文本
    check_report.json        ① 入库检查
    ingest_report.md         ① 入库报告（给人看）
    video_plan.json          ② 视觉导演输出
    image_prompts.txt        ③ 图片提示词（GPT 网页版交接）
    images/                  ③ 插画（V1-lite/V1）
    overlays/                ④ 粒子叠层（dust/snow/embers，程序生成）
    cards/                   ③ 程序排版卡 PNG
    subs/                    ③ ASS + 外挂 SRT
    segs/                    ④ 分段 MP4（可断点重渲染）
    preview/                 ④ 30 秒样片
    out/                     ⑤ 成片、缩略图、外挂字幕
    qa.json                  ⑥ 各阶段机械检查汇总
    qc_report.json           ⑥ 质检
    render_manifest.json     ⑤ 可复现清单
```

## 3. 铁律（全程有效）

1. **音频不动。** 不裁、不加速、不变调、不改响度。视频时长服从音频。
2. **SRT 只提供时间，文字以 `final.txt` 为准。** 不手动挪时间；不逐条模糊替换。
3. **不改输入文件**：`audio.*`、`subtitles.srt`、`final.txt`、`map.json`、`outline.json` 只读。
4. **不改 `tools/`、`prompts/`、`docs/`**；只写本步骤要求写的文件。
5. **不许跳步**：入库 → 策划 → 素材 → 样片 → 全片 → 质检 → 发布。每步产物必须落盘。
6. **每步跑检查**；有 `fail` 就修，不要假装通过。
7. **卡片文字程序绘制**，不让绘图 AI 生成中文；不让 AI 生成原书封面、剧照、明星脸。
8. 每步结束汇报：写到哪个文件、检查结果、下一步是什么；然后停下等用户。

## 4. 先判断走哪条路

### 4.1 视觉路线（Step 2 开始前问一次，默认 B）

先问用户一句：

> 这期画面走哪条？
> A 公版画（真实、零生成费）
> B 电影感 AI 静帧（默认）
> C 纯排版（最快最稳）

用户不选、说“默认/随便/你定” → **B `cinema`**。把答案写进 `meta.json` 的 `visual_route`：

| `visual_route` | 画面 | 说明 |
|---|---|---|
| `cinema`（默认） | 4–6 张 AI 电影感静帧 + 程序卡 | 冷灰蓝、35mm 颗粒、无正脸、环境叙事 |
| `classic` | 4–6 张公版画/版画 + 程序卡 | 纸色、低饱和、出处写进 `image_prompts.txt` |
| `type` | 0 张图 | 标题/章节/金句/人物/时间线/尾卡 |

只问一次，不要反复问。`meta.json` 没有 `visual_route` 时按 `cinema` 处理。

**图片命名规则（所有期通用）：** 用户从 GPT 网页版下载的图片会带时间后缀，例如 `ChatGPT Image 2026年10月25日 16_08_12.png`。用户不需要改名，直接把图丢进该期 `video/images/`；智能体统一跑 `python tools/rename_images.py --episode <期目录>`，按时间升序对应 `video_plan.json` 的场景顺序。不要要求用户手动命名，也不要按文件大小/内容猜顺序。

### 4.2 图片数量与停留（默认 5 秒/张）

`meta.image_interval_seconds` 默认 **5**，即每张图约 5 秒。GPT 生图免费，图多观感更好，但会花更多生成时间。

| 模式 | 每张 | 10 分钟 | 15 分钟 | 25 分钟 |
|---|---:|---:|---:|---:|
| **密集（默认）** | 约 5 秒 | ~120 张 | ~180 张 | ~300 张 |
| 常规省图 | 30–90 秒 | 3–5 张 | 4–6 张 | 6–8 张 |

- **算出来超过 60 张时先问用户**：继续 5 秒（很多图）/ 改成 8–10 秒 / 只做关键节点。不要闷头生成 180 张。只做关键节点就把 `image_interval_seconds` 改成 `0`，按 30–90 秒/张、4–6 张排。
- 5 秒模式以图片为主；卡片只保留开场、章节、结尾，不要每段插卡。
- 目标单张 4–7 秒，允许到 8 秒；不要超过 10 秒。
- 常规模式单张 30–90 秒，最长 2 分钟。
- **运镜不能抖**：一个场景只做一个方向，推近/拉远/平移必须单调；1 秒内不许反向、来回、左右乱晃；不要“呼吸缩放”和手持感。
- **平台比例**：抖音/视频号/Reels 用 9:16（1080×1920）；B站/YouTube 用 16:9（1920×1080）。只发抖音就把 `meta.aspects` 改成 `["9:16"]`，图片提示词写 `vertical 9:16`；双平台用 1:1 母版，各裁一版。
- `visual_route=type` → `preset=v0`；`cinema/classic` → `preset=v1lite`。
- `preset=v1`：常规模式下 6–8 张，3 期稳定后再用。
- `test_segment=true` 或音频 <3 分钟：场景数 2–8，不要求 title/end 卡；按 5 秒算图数（23 秒约 5 张）。

没时间就退 `v0`，不要卡住。

### 4.3 录音前预生产（Step -1，可选）

WAV 和 SRT 还没出来时，可以先做图片：

```bash
python tools/new_preproduction.py "口播稿.txt" --title 书名 --author 作者
```

它建：

```text
preprod/<书名-日期>/
  script.txt
  meta.json
  images/            # GPT 图先丢这里
  image_prompts.txt  # 智能体写
```

流程：

1. 让智能体读 `prompts/00_preproduction.md`，只按 **口播稿** 写 `image_prompts.txt`（4–6 张，计划文件名 `01_xxx.png`……），写完停下。
2. 用户按顺序去 GPT 网页版生成 1:1 方图，直接丢进 `preprod/<期名>/images/`，不用改名。
3. 录完音、导出 WAV + SRT 后建期，把预生产图一起带进来：

   ```bash
   python tools/new_episode.py "音频文件夹" --title 书名 --author 作者 \
     --visual-route cinema --images-from preprod/<期名>/images
   ```

4. 跑 Step 1 入库、Step 2 把图片顺序映射到真实句子 `from/to`。
5. 跑 `python tools/rename_images.py --episode episodes/<期名>` 自动命名，再继续 Step 3–7。

注意：预生产阶段不写 `from/to`、不算时长；这些必须等 SRT。图片顺序先定，后面挂句子。

### 4.4 长篇系列 / 复用图（28 期这类）

长篇书不要每期从零生图。先建一个系列图库：

```text
series/<书名>/
  series.json                 28 期怎么分
  asset_manifest.json         每张复用图的身份、适用范围
  assets/reusable/            用户生成一次的复用图（智能体只读）
```

规则：

- 用户生成复用图一次，放进 `assets/reusable/`；智能体**不重做、不覆盖、不重新生成**。
- 每张图必须在 `asset_manifest.json` 登记：`id`、`file`、`kind`、`subject`、`reuse`、`allowed_episodes`、`avoid`、`rights`。
- **能跨期复用**：环境、建筑、天气、地图、物件、群体剪影。
- **不能随便复用**：具体人物正脸/特写、具体事件画面、和旁白季节/地点/身份矛盾的图。
- 具体事件图只能在本期或 `allowed_episodes` 里用；`reuse=restricted` 必须写允许期数。
- 做 Step 2 前先读 `asset_manifest.json` 和 `series.json`；复用场景写 `asset_id` 和 `image` 路径。
- 图不对/缺图就停下问用户，不要拿“差不多的图”顶。
- 长篇系列不碰 5 秒/张：每期 4–6 张唯一图，30–90 秒/张，配卡片和推拉平移。
- 模板在 `series/_模板/`。

## 5. Step 0：建期（程序）

用户把音频文件夹（里面有 wav + srt + 可选 txt）拖给你，或直接说路径：

```bash
python tools/new_episode.py "D:\my_Software\Audacity\导出音频\羊脂球" \
  --title 羊脂球 --author 莫泊桑 --column 听故事
```

- 不想回答问题就加 `--yes`，默认值见 `new_episode.py`。
- 没有 SRT：停止，让用户先导出字幕；不要用语音识别猜时间。
- 没有 `final.txt`：继续，但报告里必须写明「文字以 SRT 为准，可能有同音错字」。
- 它自动跑 `tools/prepare.py`，并打印下一步发给智能体的话。

## 6. Step 1：入库检查

提示词：`prompts/01_ingest.md`

```bash
python tools/prepare.py --episode episodes/<期名>
```

- 输入：`audio.*`、`subtitles.srt`、`final.txt`
- 输出：`video/sentences.json`、`video/check_report.json`、`video/ingest_report.md`
- 程序做：编码/时间格式/总时长/结构/文字对齐、全局单调对齐、断句、`needs_review` 标记。
- 你只看 `ingest_report.md` 和 `check_report.json`；**不改时间、不改音频**。
- 对齐匹配率 <70%：停止，问用户「SRT 和稿子是不是同一版」。
- 通过后停下，等用户看句子表。

## 7. Step 2：视觉导演

提示词：`prompts/02_director.md`

- 开始前按 4.1 问一次视觉路线，**默认 `cinema`**，写进 `meta.json`。
- 输入：`meta.json`、`video/sentences.json`、`final.txt`、可选 `outline.json` / `map.json`
- 输出：`video/video_plan.json`
- 只做：选场景、定 `from/to`、写卡片文案、给 `hold_seconds`、按路线选图的位置和 `image_prompt`。
- 图片数按 `meta.image_interval_seconds`（默认 5 秒/张）：总时长 ÷ 5；如果算出来 >60 张，先问用户“继续 5 秒 / 改 8–10 秒 / 只做关键节点”。
- 长篇系列先读 `series/<书名>/asset_manifest.json` 和 `series.json`；复用同系列图时写 `asset_id`，并确认本期在 `allowed_episodes` 里；不要重新生成复用图。
- **书封卡 `book_card`**：口播念到“我是……今天讲/今天我们将……《书名》”时，放 1 张 `book_card`。`title` 写《书名》，`author` 写作者，`line` 写“短篇小说/长篇小说”，`image` 选一张符合本期风格的背景图（cinema 用暗色室内/书桌/雪夜，不要白纸板），书封颜色会从背景取色、压成同一色调，`hold_seconds: 4`。它由程序绘制，不让 AI 生成书封中文。`from/to` 必须落在 SRT 里品牌开场/书名那几句上；没有 SRT 不要硬编时间。
- **视频封面 `cover`**：每期必须写一份 `cover`（标题、≤14 字钩子、作者、栏目、可选背景图），渲染时自动出 9:16 和 16:9 两张平台封面。封面文字程序绘制，书名要大；不剧透、不标题党。
- `cinema`：按上面的间隔排 `illustration`，放在开场、转折、至暗、高潮前；英文/中文提示词都要写清“cinematic film still / no faces / 35mm grain / muted grey-blue”。
- `classic`：按上面的间隔排 `illustration`，只选公版画/版画，不生成；`image` 先写占位路径，Step 3 补图。
- `type`：0 张图，全部用 `title_card` / `section_card` / `quote_card` / `character_card` / `timeline_card` / `background` / `end_card`。
- 不写秒数、不写 FFmpeg、不写口播。
- 跑：`python tools/check.py --episode episodes/<期名> --stage plan`
- 通过后停下，等用户确认场景节奏。

## 8. Step 3：素材与卡片

提示词：`prompts/03_assets.md`

- 输入：`video/video_plan.json`、`video/sentences.json`、`final.txt`、`meta.json`
- 输出：`video/image_prompts.txt`、`video/images/*.png`（按路线）、`video/cards/*.png`
- `book_card` 的位置由 SRT 决定：在 `sentences.json` 找“我是……今天讲/今天我们将……《书名》”那几句，`from/to` 设在那几句上；通常不是第一张图。
- `cinema` 的书封卡图单独生成 `images/book_card.png`（书在中间、封面空白、上下留白），不参与插画时间顺序；视频里的位置仍由 plan 的 `from/to` 决定，不是按生成顺序插。
- `cards` 用这张 AI 书封图 + 程序文字；不要让 AI 写书名/作者。
- `cinema`（默认，GPT 网页版交接）：
  1. 先把这一期需要的 **所有** 图片想清楚，写进 `video/image_prompts.txt`：统一风格前缀 + 每张图的完整英文提示词 + 文件名 + 对应句子 + 中文画面说明。
  2. 写完**停下**，告诉用户「去 GPT 网页版生成这 N 张，直接丢进 `video/images/`，名字不用改」，不要自己拿占位图冒充。
  3. 用户说图放好了，**先跑**：

     ```bash
     python tools/rename_images.py --episode episodes/<期名>
     ```

     它会按文件名里的时间后缀（如 `ChatGPT Image 2026年10月25日 16_08_12.png`）升序排序，依次改名成 `01_xxx.png`、`02_xxx.png`……对应 `video_plan.json` 的场景顺序，并写 `video/image_map.json` 留底。**所有期通用**，不要让用户手动一张张命名。
  4. 数量对不上就停下问用户，不要猜；然后跑 `cards`、`check --stage assets`，继续 Step 4。
- `classic`：从公版画/版画里选 4–6 张；在 `image_prompts.txt` 写作品名、作者、来源（Met/Wikimedia 等，必须公有领域）；统一低饱和/纸色/暗角。
- `type`：跳过图片，只做卡片。
- 程序卡：`python -m video_engine cards --episode episodes/<期名>`
- ASS 字幕由渲染阶段生成，不在这一步要求。
- 跑：`python tools/check.py --episode episodes/<期名> --stage assets`
- 缺图允许 `warn`（用品牌底兜底）；缺卡片是 `fail`。
- 通过后停下。

## 9. Step 4：粒子与 30 秒样片

提示词：`prompts/04_render.md`

渲染前先问用户三件事（只问一次）：

1. **加粒子吗？** 不加 / 灰尘 `dust` / 雪 `snow` / 火星 `embers`（默认不加）
2. **字幕怎么处理？** 烧进视频 / 不烧（只要视频+音频，字幕后期自己加）（默认烧）
3. **先出 30 秒试用，还是直接全片？**（默认 30 秒试用）

把答案写进 `meta.json`：

```json
{
  "overlay_style": "none | dust | snow | embers",
  "overlay_opacity": 0.22,
  "subtitle_mode": "burn | none"
}
```

- `burn`：字幕烧进视频，同时导出 `out/subtitles.srt`。
- `none`：成片只有画面+音频，不烧字幕；仍然导出 `out/subtitles.srt`，用户自己后期加。

试用：

```bash
python -m video_engine render --episode episodes/<期名> --aspect both --preview 30
```

- 试用只渲染开头 30 秒 + 一个中段 + 结尾，只用到已生成图片的一部分；**不会重新生成图片，也不影响 Step 3**。
- 音频短于 30 秒时，自动改为全片（23.5 秒测试段就是全片），要告诉用户。
- 看四处：开头 3 秒、字幕字号/安全区、一个章节卡、结尾 5 秒；顺便看粒子是否太抢。
- 用户说“可以”才进 Step 5；说“不用试用”就直接跑全片。
- **样片不过，不渲染全片。**

## 10. Step 5：全片渲染

```bash
python -m video_engine render --episode episodes/<期名> --aspect both
python tools/check.py --episode episodes/<期名> --stage render
```

- 输出 `video/out/video_9x16.mp4`、`video_16x9.mp4`、`subtitles.srt`、`cover_9x16.png`、`cover_16x9.png`、缩略图、`render_manifest.json`。
- 音频不动；视频短了延长最后一段，不用 `-shortest` 截音频。
- 通过后停下。

## 11. Step 6：质检

提示词：`prompts/05_qc.md`

```bash
python -m video_engine qc --episode episodes/<期名>
python tools/check.py --episode episodes/<期名> --stage render
```

- 时长差、黑帧、静音尾巴、字幕偏差、安全区、音频一致性、卡片事实。
- 发现问题只改 `video_plan.json` / 卡片 / 图片；不改音频、不改 SRT 时间。
- 通过后停下。

## 12. Step 7：发布包装

提示词：`prompts/06_publish.md`

- 先一次性问用户 5 件事：账号名、栏目、下期、内容提示、结尾形式。
- 输出 `publish.md`：3 个标题、9:16/16:9 封面字、简介（含 AI 声明）、标签、置顶评论、引文出处。
- 跑：`python tools/check.py --episode episodes/<期名> --stage publish`

## 13. 检查脚本怎么用

```bash
python tools/doctor.py                                          # 环境自检
python tools/prepare.py --episode episodes/<期名>                 # 入库
python tools/check.py --episode episodes/<期名> --stage ingest
python tools/check.py --episode episodes/<期名> --stage plan
python tools/check.py --episode episodes/<期名> --stage assets
python tools/check.py --episode episodes/<期名> --stage render
python tools/check.py --episode episodes/<期名> --stage publish
python tools/check.py --episode episodes/<期名> --stage all
```

- 退出码 0 = 没有 fail；1 = 有 fail；2 = 目录/文件有问题。
- 结果同时写进 `video/qa.json`。
- `warn` 不阻断，但要在汇报里写出来。

## 14. 当前实现状态

**全部可用：**

- `tools/prepare.py`：SRT 解析、音频时长、与 `final.txt` 全局单调对齐、句子表、五项检查。
- `tools/check.py`：ingest / plan / assets / render / publish 五阶段机械检查。
- `tools/new_episode.py`、`tools/rename_images.py`、`tools/doctor.py`。
- `video_engine/cards.py`：七类程序卡 + 品牌底，9:16 / 16:9，自动换行、hash 缓存。
- `video_engine/render.py`：分段渲染、缓慢运动、concat、ASS 烧录、AAC 音频、样片、缩略图、manifest。
- `video_engine/qc.py`：时长、分辨率、黑帧、静音尾巴、响度、首尾亮度、字幕烧录抽检。

**已实测（`episodes/羊脂球-第一段`，23.5 秒）：**

```text
video_9x16.mp4   23.63s  1080x1920
video_16x9.mp4   23.63s  1920x1080
QC               21 项，0 fail，0 warn
```

三条视觉路线都已跑通，默认选 **B `cinema`**：

```text
episodes/羊脂球-第一段-A-公版画/video/out/
episodes/羊脂球-第一段-B-AI电影感/video/out/
episodes/羊脂球-第一段-C-纯排版/video/out/
episodes/对比-A-B-C.jpg
episodes/对比说明.md
```

**可选改进：**

- 把 `ffprobe.exe` 补进 `D:\ffmpeg\bin`（没有也能用，时长探测会退回 `ffmpeg -i`）。
- 把 Noto Sans/Serif SC 放进 `fonts/` 随程序打包，避免换电脑缺字体。
- 之后要更复杂的版式，再换 HTML/CSS → PNG（Playwright）。

实现规格：`docs/ENGINE_SPEC.md` + `docs/方案/01-制作流水线.md`、`02-画面与字幕规范.md`。

## 15. 禁止事项

- 不要把 SRT 当文字基准；不要手动改 SRT 时间。
- 不要为了让画面好看去裁/加速音频。
- 不要每句换画面；15 分钟 7–10 次画面变化足够。
- 不要让 AI 生成中文卡片；不要用原书封面、剧照、明星脸。
- 不要把 9:16 裁成 16:9，或反过来。
- 不要在 `no_ending` 期的标题/封面/简介里泄露结局。
- 不要在检查失败时改 `qa.json` 或跳过检查。
- 不要把占位图/假卡片说成已完成。
