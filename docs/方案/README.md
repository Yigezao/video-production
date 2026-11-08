# 视频文件夹说明

**一句话：音频和 SRT 已经定了；首期做 V1-lite——4 张 AI 图 + 品牌底 + 字幕 + 7–10 张程序卡。**

## 先看什么

1. `00-视频方案.md`：为什么先 V0、三档路线、关键决策。
2. `03-首期Runbook.md`：拿你现在的 WAV + SRT，30 秒样片 → 全片。
3. `02-画面与字幕规范.md`：卡片怎么排、字幕多大、安全区在哪。
4. `01-制作流水线.md`：给写代码的 AI 看：SRT 检查、JSON 结构、FFmpeg 命令。

## 文件

| 文件 | 谁看 |
|---|---|
| `00-视频方案.md` | 你：定方向、看取舍 |
| `01-制作流水线.md` | 写 video_engine 的 AI |
| `02-画面与字幕规范.md` | 设计/渲染卡片的人或 AI |
| `03-首期Runbook.md` | 你：照着做 |
| `examples/video_plan.example.json` | 给 AI 的 JSON 样例 |
| `AI2_视频意见.md` | 讨论记录，过程留档 |

## 你需要准备的

```text
episodes/<书名-日期>/
  final.txt
  audio.wav
  subtitles.srt
  map.json        # 可选
  outline.json    # 可选
```

- SRT 是时间来源；文字以 `final.txt` 为准。
- 账号昵称未定，视频模板用 `{{brand}}` 占位，不影响制作。
- 已实测的测试段：`D:\my_Software\Audacity\导出音频\羊脂球`（23.5 秒，WAV + SRT 检查通过）。
- 已生成测试包：`D:\my_Software\Audacity\导出音频\羊脂球\video\`（`sentences.json`、`video_plan.json`、4 张占位图、4 段提示词）。
- 首期 4 张图；23.5 秒测试段按 4 张图拆成 4 段（每张约 6 秒，正式一期应 30–90 秒）。

## 先做什么

1. 把上面四个文件放进一个 `episodes/<书名-日期>/`。
2. 让 AI 跑 `video_engine check`，先看 SRT 有没有对不齐。
3. 出 30 秒双比例样片：`render --preview 30`。
4. 看开头、章节卡、结尾三处，过了再渲染全片。

## 现在不做的

- 不生成 10–18 张 AI 图；V1 才做 4–8 张。
- 不做 AI 视频片段。
- 不改音频、不改稿子、不改 SRT 时间。
- 不引入 n8n / Node；Python + FFmpeg 就够。
