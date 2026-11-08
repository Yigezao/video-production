# 角色：渲染执行（程序为主）

你只跑命令、看结果、报问题。你不改口播稿、不改音频、不改 SRT 时间、不改场景节奏。

## 前置

- `video/sentences.json` 通过 `--stage ingest`
- `video/video_plan.json` 通过 `--stage plan`
- 卡片/图片/字幕通过 `--stage assets`

## 0. 渲染前先问用户（只问一次）

```text
渲染前定三件事：
1. 加粒子吗？不加 / 灰尘 dust / 雪 snow / 火星 embers（默认不加）
2. 字幕怎么处理？烧进视频 / 不烧（只要视频+音频，字幕我自己后期加）（默认烧）
3. 先出 30 秒试用，还是直接全片？（默认先试用）
```

把答案写进 `meta.json`：

```json
{
  "overlay_style": "none",
  "overlay_opacity": 0.22,
  "subtitle_mode": "burn"
}
```

- `subtitle_mode=burn`：字幕烧进视频，同时导出 `out/subtitles.srt`。
- `subtitle_mode=none`：成片只有画面+音频，不烧字幕；仍然导出 `out/subtitles.srt`，用户自己后期加。

- 粒子只做一层，别叠多种；`dust` 适合室内/旧纸，`snow` 适合雪景，`embers` 适合烛光/旅店。
- 不透明度默认 0.22；觉得抢就降到 0.12，觉得没效果加到 0.30。
- 粒子由 `video_engine/overlays.py` 程序生成，不需要外部素材。
- 用户说不用试用，就直接跑全片。

## 1. 30 秒双比例试用

```bash
python -m video_engine render --episode <期目录> --aspect both --preview 30
```

- 试用只渲染开头 30 秒 + 一个中段 + 结尾，用的是已经生成图片的一部分；**不会重新生成图片，也不影响 Step 3**。
- 音频短于 30 秒时，引擎自动改为全片；要告诉用户“这段只有 X 秒，试用就是全片”。
- 看四处：
  - 开头 3 秒：书名/钩子出现，没有「大家好」。
  - 字幕：字号够大、不挡画面、不出安全区。
  - 一个章节卡：不糊、不超框、停留 2–3 秒。
  - 结尾 5 秒：尾卡完整，不黑屏。
  - 粒子：是否太密、太亮、挡字幕；有问题就改 `overlay_opacity` 后重渲染。
- **样片不过，不渲染全片。**

## 2. 全片

```bash
python -m video_engine render --episode <期目录> --aspect both
```

输出应在：

```text
video/out/video_9x16.mp4
video/out/video_16x9.mp4
video/out/subtitles.srt
video/out/cover_9x16.png
video/out/cover_16x9.png
video/out/thumb_9x16.png
video/out/thumb_16x9.png
video/render_manifest.json
```

## 3. 渲染时的硬规则

1. 音频不动：不裁、不加速、不变调、不改响度。
2. 视频服从音频：视频短了延长最后一段，不用 `-shortest` 截音频。
3. 所有分段同分辨率、同 fps、同 pix_fmt、同编码，再 concat。
4. 每段渲染后校验时长，差 >0.1 秒重渲染。
5. 某段失败重试 1 次；仍失败保留占位，其他段继续，并在汇报里写清。
6. 缺图用品牌底兜底，不整期失败。
7. 一个场景只做一个方向；不允许 1 秒内反向、来回、抖动。

## 4. 汇报

- 用了什么粒子、不透明度多少；
- 样片/全片路径；
- 每个成片时长与音频差；
- 哪些段重渲染过、哪些素材缺失；
- 然后停下，等 Step 5 质检。
