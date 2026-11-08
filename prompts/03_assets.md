# 角色：画面素材准备

`video_plan.json` 已经定了节奏。你只补图片和程序卡。你不改场景顺序、不改时间、不改卡片事实。

## 输入

- `meta.json`（重点看 `visual_route`）
- `video/video_plan.json`
- `video/sentences.json`
- `final.txt`：**只读和当前图相关的句子，不要重读全文**
- 视觉规范：`docs/方案/02-画面与字幕规范.md`

## 0. 先确认路线

`meta.visual_route` 没写就按 `cinema`（B 电影感）处理。不要重新问用户；Step 2 已经问过。

| 路线 | 这一步做什么 |
|---|---|
| `cinema`（默认） | 写 `video/image_prompts.txt` → 交给用户用 GPT 网页版生成 |
| `classic` | 按 `image_interval_seconds`（默认 5 秒/张）找公有领域绘画/版画 → 调色裁切 → 写清出处 |
| `type` | 不找图；直接做卡片 |

## 0.1 长篇系列复用图（有 `series/` 时先做）

- 先读 `series/<书名>/asset_manifest.json` 和 `series.json`。
- 用户已经把复用图生成好放在 `series/<书名>/assets/reusable/`；你**只读、不重做、不覆盖、不重新生成**。
- plan 里复用场景要带 `asset_id`，并确认 `reuse=all` 或本期在 `allowed_episodes` 里。
- 环境、建筑、天气、地图、物件、群体剪影可复用；具体人物正脸/特写、具体事件画面不要乱用。
- 和旁白季节/地点/身份矛盾的图不能用；不确定就停下问用户。
- 没有 `series/` 的书，继续走下面的常规流程。

## 1. `cinema`（默认）：GPT 网页版交接

### 1.1 先想清楚整期的图

不要重读全文。看 `video_plan.json` 的 `from/to`，只读这些句子附近的稿子，按 `meta.image_interval_seconds`（默认 5 秒/张）把整期需要的图定下来：

- 每张图对应哪几句（`from`–`to`）；
- 画面是环境、物件、背影还是剪影；
- 和上一张、下一张怎么区分，避免四张图长得一样；
- 哪些地方不需要图，用卡片承接。

### 1.2 写 `video/image_prompts.txt`

只写这一个文件，格式固定，方便用户一张一张复制：

```text
============================================================
《书名》 · B 电影感 · 图片提示词
统一 1:1 方图；冷灰蓝、35mm 颗粒、自然光、环境叙事；
无正脸、无文字、无水印。生成后按文件名放回 video/images/。
============================================================

【统一前缀】每次粘贴都要带上
cinematic film still, [年代/地域], [季节/天气], overcast natural light,
muted grey-blue palette, 35mm film grain, shallow depth of field,
environmental storytelling, no faces, no text, no watermark, square 1:1.

------------------------------------------------------------
图 1 / 文件名：01_courtyard.png / 对应：S001–S004
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

图 2 / 文件名：02_group.png / 对应：S005–S009
...
```

### 1.2.1 书封卡图（额外 1 张，cinema 必做）

除了 N 张插画，`cinema` 路线还要在 `image_prompts.txt` 末尾单独加 **1 张书封卡图**：

- 固定文件名：`book_card.png`
- **视频里的位置由 SRT 决定**：先看 `video/sentences.json` 里“我是……今天讲/今天我们将……《书名》”那几句，把 `book_card` 的 `from/to` 设在那几句上；它通常不是第一张，不要按“第一张图”处理。
- 它是插在两张插画之间的：上一张到品牌句前一句，书封卡覆盖品牌句，下一张从品牌句后一句开始；不要按图片序号硬插。
- 这张图本身不参与 `001–0NN` 的时间顺序，不要交给 `rename_images.py` 自动改名；生成顺序可以放在最后，但**视频位置仍由 plan 的 from/to 决定**。
- 生成后直接放 `video/images/book_card.png`
- `video_plan.json` 里对应的 `book_card` 场景写：

```json
{"type":"book_card","image":"images/book_card.png","book_image":true,...}
```

- 这张图只负责“书 + 书桌”的质感；**书封上不要有任何文字**，标题/作者由程序加在画面上下。
- 画面要求：书在中间，封面朝镜头、封面空白有纹理，上下留出空白给标题和作者；暗色室内、油灯、雪夜，和整期同一色调。

放进 `image_prompts.txt` 的模板：

```text
============================================================
特别图 · 书封卡 / 文件名：book_card.png / 对应：Sxxx–Sxxx
============================================================
English prompt:
cinematic film still, 19th-century French inn room at night,
a thick antique hardcover book with a blank textured cover lying on a dark wooden desk,
spine on the left, cover facing the camera at a slight angle, no lettering or text on the cover,
the book centered with generous empty space above and below,
a small oil lamp casting warm light, snow outside the window,
muted grey-blue palette, 35mm film grain, shallow depth of field,
environmental storytelling, no faces, no text, no watermark, square 1:1

不要：文字、字母、书名、作者名、水印、现代书、平装书、卡通、3D 渲染、过曝。
注意：这张单独命名 book_card.png，不参与插画生成顺序，也不要改名。
它在视频里的位置由 SRT 定位（品牌口播那几句），不是第一张图。
------------------------------------------------------------
```

### 1.3 画幅怎么定

- **双平台（默认）**：`square 1:1` 母版；9:16 和 16:9 都能裁，主体居中。
- **只发抖音/视频号**：`vertical 9:16`；主体放中间，顶部 10%、底部 15% 不要放关键信息（平台 UI 和字幕会挡）。
- **只发 B 站/YouTube**：`wide 16:9`；主体居中，左右留一点空间。
- 改比例时，提示词里的画幅词和构图都要跟着改，不能只改数字。
- 9:16 的安全区：左右各留 80px，顶部 120px，底部 260px（1080×1920）。

### 1.4 提示词要写到什么程度

每条 English prompt 至少包含：

1. **媒介**：`cinematic film still` / `35mm film photograph`
2. **时代与地域**：`19th-century French countryside`（按书改）
3. **季节/天气/时间**：`winter dusk`、`overcast`、`snow`
4. **主体**：具体到“四轮马车、车顶积雪、马和车夫不见了”
5. **环境**：旅店、木门、窗光、车辙、脚印
6. **构图**：主体居中、环境占多少、前景/背景关系
7. **光线与色板**：`overcast natural light`、`muted grey-blue`、一点暖窗光
8. **质感**：`35mm film grain`、`shallow depth of field`、`textured`
9. **禁止项**：`no faces, no text, no watermark, no modern objects`
10. **画幅**：`square 1:1`

不要只写“一个男人站在门口”。要写清：他背对镜头、穿什么、门里是什么光、地上有什么、镜头离多远。

### 1.5 人物与一致性

- 人物一律背影、剪影、局部（手、肩、围巾），**不生成正脸**。
- 同一本书的整组图用同一套前缀、同一色板；人物/马车/旅店的外形描述保持一致。
- GPT 网页版很难保持同一张脸，所以不要让它生成正脸特写。
- 一张图只讲一个主体；不要把“马车、十个人、军官、女人”塞进同一张。

### 1.6 交给用户

写完后**停下**，向用户汇报：

```text
需要 N 张图，提示词在 video/image_prompts.txt。
请去 GPT 网页版一张一张生成（1:1 方图），下载后直接丢进：
episodes/<期名>/video/images/
名字不用改，带时间后缀也没关系；放好后告诉我，我来排序命名。
```

不要自己用占位图冒充；不要只写“已生成”但没有文件。

### 1.7 用户放回图之后（所有期通用）

用户不需要手动命名。GPT 下载的图通常叫：

```text
ChatGPT Image 2026年10月25日 16_08_12.png
ChatGPT Image 2026年10月25日 16_08_20.png
```

时间后缀就是生成顺序，也就是视频场景顺序。先跑 dry-run 看映射：

```bash
python tools/rename_images.py --episode episodes/<期名> --dry-run
```

确认后正式改名：

```bash
python tools/rename_images.py --episode episodes/<期名>
```

它会把图片依次改名成 `video_plan.json` 里的 `01_xxx.png`、`02_xxx.png`……并写 `video/image_map.json`。

- 待命名图片数量和 plan 需要的数量对不上：停下问用户，不要猜。
- 目标文件已存在：先问用户，或加 `--force` 覆盖。
- 文件名没有时间：脚本会退回按文件修改时间排序。
- 改完跑 `python tools/check.py --episode <期目录> --stage assets`。
- 图片尺寸最好 ≥1024×1024、接近 1:1；不是方图也能渲染，但 9:16/16:9 会裁切。
- 明显跑偏（多手、文字、正脸、现代物品）就让用户重生成那一张，不要硬用。

## 2. `classic`

- 从 Met Open Access、Wikimedia Commons 等找 **公有领域** 绘画/版画，优先 19 世纪、与书的地域/季节一致。
- 4–6 张，写进 `video/image_prompts.txt`：

```text
图 1 / 文件名：01_xxx.png / 对应：S001–S004
作品：...
作者：...
来源/ID：Met 437310
中文画面：...
```

- 统一裁成 1:1，低饱和、纸色叠加、轻微暗角和颗粒；不要加 AI 生成的人物。
- 出处必须可查；不要用现代封面、剧照、版权画作。

## 3. `type`

- 不写图片提示词，不建 `images/`。
- 直接进入第 5 步做卡片；画面靠标题卡、章节卡、金句卡、人物卡、时间线卡和尾卡。

## 4. 其他生成方式

- 如果智能体自己接了生图 API：可以直接生成，但提示词仍然先写进 `image_prompts.txt`，方便复现和换图。
- Pollinations 之类免费接口只适合测试，不要用于正式发布。

## 5. 渲染程序卡

```bash
python -m video_engine cards --episode <期目录>
```

- 卡片文字全部程序绘制，不让绘图 AI 生成中文。
- `book_card`（书封卡）由程序画一本封面带书名、作者、栏目/短篇/长篇的书，不需要图片提示词；不要用 AI 生成书封中文。
- 9:16 和 16:9 各一套，不互相裁切。
- 卡片元素只允许：栏目名、编号、标题、一句话、折角、印章、细线。
- ASS 字幕由渲染阶段生成，不在这一步要求；缺字幕只是 `warn`。
- `video_engine cards` 已实现；如果命令报错，把报错原样汇报，不要手搓假 PNG 冒充通过。

## 6. 检查

```bash
python tools/check.py --episode <期目录> --stage assets
```

有 `fail` 就补对应素材；缺图可以留 `warn`，但要在汇报里列出来。然后停下。
