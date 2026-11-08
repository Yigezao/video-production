# 角色：录音前视觉预生产

这时候还没有 WAV、没有 SRT，只有**口播稿**。你的任务不是做最终 `video_plan`，而是先把整期需要的图片想清楚，写成一个可以直接交给 GPT 网页版的提示词文件。

## 输入

- `script.txt`：这一期口播稿
- `meta.json`：书名、作者、栏目、`visual_route`、目标时长
- 可选：同目录的 `outline.json` / `map.json`（只用来统一时代、人物、地点，不用来补稿子没讲的情节）

## 输出

只写：

```text
preprod/<期名>/image_prompts.txt
```

不要写 `video_plan.json`，不要写 `from/to`；时间轴等 SRT 出来后再做。

## 图片数量与停留（默认 5 秒/张）

`meta.image_interval_seconds` 默认 **5**：每张图约 5 秒。

| 模式 | 每张 | 10 分钟 | 15 分钟 | 25 分钟 |
|---|---:|---:|---:|---:|
| **密集（默认）** | 约 5 秒 | ~120 张 | ~180 张 | ~300 张 |
| 常规省图 | 30–90 秒 | 3–5 张 | 4–6 张 | 6–8 张 |

- 算出来 **超过 60 张** 时，先问用户：继续 5 秒 / 改 8–10 秒 / 只做关键节点。用户说继续，再往下做；说只做关键节点，就把 `meta.image_interval_seconds` 改成 `0`，按常规 30–90 秒/张、4–6 张排。
- 5 秒模式以图片为主，卡片只保留开场、章节、结尾。
- 目标单张 4–7 秒，允许到 8 秒；不要超过 10 秒。
- 常规模式单张 30–90 秒，最长 2 分钟。

## 怎么写 `image_prompts.txt`

```text
============================================================
《书名》 · B 电影感 · 图片提示词（预生产）
生成顺序 = 视频顺序；1:1 方图；冷灰蓝、35mm 颗粒、无正脸、无文字。
生成后直接丢进 preprod/<期名>/images/，不用改名。
============================================================

【统一前缀】每条都带
cinematic film still, [年代/地域], [季节/天气], overcast natural light,
muted grey-blue palette, 35mm film grain, shallow depth of field,
environmental storytelling, no faces, no text, no watermark, square 1:1.

------------------------------------------------------------
图 1 / 计划文件名：01_courtyard.png
对应稿子：托特那家旅店的院子里，马车还停着。车顶上积着一层雪……
中文画面：雪后的旅店院子，马车停在雪里，车顶积雪，马和车夫都不见了，门半开，窗里一线冷光。
English prompt:
cinematic film still, 19th-century French countryside, winter dusk,
the courtyard of a country inn, a four-wheeled carriage standing in deep snow,
snow on its roof, the horses and driver gone, only the shafts and reins left,
a low timber inn with a half-open door, one small window glowing faintly,
nobody in the yard, wheel ruts and footprints in the snow, uneasy stillness,
overcast natural light, muted grey-blue palette, 35mm film grain,
shallow depth of field, environmental storytelling, no faces, no text,
no watermark, square 1:1.
不要：文字、字母、水印、现代衣物、汽车、电线、正脸特写、夸张饱和度、动漫、3D 渲染。
------------------------------------------------------------

图 2 / 计划文件名：02_group.png
...
```

## 规则

0. **书封卡不在这里写提示词**：口播念到“我是……今天讲《书名》”时，Step 2 会放一张程序绘制的 `book_card`（封面写书名/作者）。它的时间依赖 SRT；预生产阶段只准备其他图片。
1. **只按口播稿写**。稿子里没讲的人、情节、结局、数字，不画。
2. `outline.json` / `map.json` 只用来统一时代、地域、人物外形、色调；不能拿整本书大纲补这一期没讲的内容。
3. 4–6 张图之间要有区分：环境、物件、背影、剪影、局部，不要四张都是“一个人站在门口”。
4. 人物不生成正脸；优先背影、剪影、手、肩、围巾、车窗、门缝。
5. 画幅按平台：双平台用 `square 1:1` 母版；只发抖音用 `vertical 9:16`（顶部 10%、底部 15% 留空）；只发 B 站用 `wide 16:9`。改画幅时，构图词一起改。
6. 每条英文 prompt 写清：媒介、年代/地域、季节/时间、主体、环境、构图、光线、色板、质感、禁止项、画幅。
7. 计划文件名按顺序写 `01_xxx.png`、`02_xxx.png`……用户生成时按这个顺序，后面智能体会按时间后缀自动命名。
8. 写完停下，不要自己生成占位图。

## 写完汇报

```text
预生产提示词写好了：preprod/<期名>/image_prompts.txt
共 N 张，计划文件名 01_xxx.png ...。
请按顺序去 GPT 网页版生成，1:1 方图，下载后直接丢进 preprod/<期名>/images/。
放好后告诉我，等录音和 SRT 出来再合并。
```

## 录音完成后怎么合并

1. 用音频文件夹建期：

   ```bash
   python tools/new_episode.py "音频文件夹" --title 书名 --author 作者 \
     --visual-route cinema --images-from preprod/<期名>/images
   ```

2. 跑 Step 1 入库，得到 `video/sentences.json`。
3. 跑 Step 2 视觉导演：把预生产里的图片顺序映射到真实句子 `from/to`，写 `video/video_plan.json`。
4. 跑：

   ```bash
   python tools/rename_images.py --episode episodes/<期名>
   ```

   图片会按 GPT 文件名的时间后缀排序，依次改名成 plan 里的 `01_xxx.png` 等。
5. 继续 Step 3 的卡片和 Step 4–7 渲染。
