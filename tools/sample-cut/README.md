# 样片标准剪辑（sample-cut）

把一批商品拍摄素材剪成约 24 秒的带货竖屏短视频，节奏、推近、调色、动作原声、字幕和 BGM 都按老师样片实测的标准来。

- 这套脚本由 Codex 或 Claude Code 按步骤调用，不依赖工作台网页服务。
- 支持 macOS 和 Windows。
- 已在 Windows 上做完两条成片（绿豆沙、一茶）。macOS 版已在 GitHub 的 Mac 云电脑（macOS 15，M1）上从零跑通全流程（`.github/workflows/mac-acceptance.yml`）；Mac 剪映打开草稿还没验证。见文末“平台差异”。

## 全自动（推荐）

对 Codex 说一句"用 <素材文件夹> 做视频"，Codex 按 [`AUTOPILOT.md`](AUTOPILOT.md) 从头做到尾，中途不提问：

1. 给素材编号、做拼板（`scan_materials.py`）
2. 判断每条素材的镜头类型、挑镜头（Codex 看图，类型见 `taxonomy.json`）
3. 读包装上的字（`ocr_text.py`，Codex 再看清晰帧确认）
4. 写文案并过检查（`copy_check.py`）
5. 生成剪辑参数（`make_spec.py`）
6. 一条命令完成剩下的（`produce.py`）：配音、出片、3 版 BGM、质检（`qa.py`）、封面、手机预览、交付文件夹和报告

第一次使用前运行一次 `autopilot_setup.py`：下载字体和 BGM 曲库、写默认设置、报告还缺什么。

- **配音**：有百炼 Key 时用云端音色（默认龙小淳），配音时间用语音识别逐字对齐。
- **自己的声音**：先装 CosyVoice，再运行 `autopilot_setup.py --own-voice 我的录音.wav --own-voice-text "录音原话"`，之后都用自己的声音。
- **没有 Key 也没有 CosyVoice**：无法配音，`autopilot_setup.py` 会直接说明缺什么。

下面是手动一步步的用法，适合想自己控制每一步的时候。

## 字幕样式

`styles.json` 里有 10 套样式。每条视频按商品自动挑一套：先看商品名和文案属于哪类（茶、饮品、甜品、零食……），同类候选里再按商品名固定挑一个。所以不同商品样式不同，同一商品重做时样式不变。

| 样式 | 字体（SIL OFL 免费商用） | 特点 |
|---|---|---|
| 经典带货 | 思源黑体 Black | 白字黑边，黄色关键词放大，弹入 |
| 得意黑活力 | 得意黑 | 斜体，橙色关键词，上滑 |
| 快乐体可爱 | 站酷快乐体 | 粉色描边，弹入 |
| 黄油大字报 | 站酷庆科黄油体 | 黄字双描边，红色关键词 |
| 清爽底框 | 思源黑体 Bold | 半透明圆角底框，薄荷绿关键词，淡入 |
| 文楷温柔 | 霞鹜文楷 | 暖色关键词，柔和阴影，淡入 |
| 小薇雅致 | 站酷小薇体 | 金色关键词，上滑 |
| 综艺双描边 | 思源黑体 Black | 黑+黄双描边，青色关键词 |
| 高亮底条 | 思源黑体 | 关键词加黄色底条 |
| 极简白字 | 思源黑体 Bold | 接近老师样片：白字、柔和阴影 |

- **关键词**：每句挑 1–2 个高亮，优先数字+单位、商品名、口感词。也可以在 `copy.json` 每句写 `emphasis` 指定。
- **指定样式**：在 `copy.json` 写 `"style": "得意黑活力"`，或设环境变量 `CAPTION_STYLE`。
- **预览全部样式**：`sc captions.py preview all "零糖零脂的茉莉白牡丹" 样式.png`
- **剪映草稿**：用剪映自带的同款字体（得意黑、快乐体、黄油体、小薇体、思源黑体）和剪映自己的入场动画，关键词同样变色。
- **字体来源**：`fonts_download.py` 从各字体的官方仓库下载，每款都附原版授权文件。不从剪映里拷字体、花字或模板到成片里，那些授权只限在剪映里用。

## 样片标准（`examples/spec.json` 的 `targets`）

| 项 | 标准 |
|---|---|
| 时长 | 20–26 秒 |
| 镜头 | 18–26 个，平均 0.95–1.25 秒，单个 0.6–1.9 秒 |
| 语速 | 6.6–7.4 字/秒，气口剪掉 |
| 推近 | 每个镜头 1.10–1.25 倍。动作镜头（倒水、搅拌）推得更多 |
| 调色 | 亮度 / 对比 / 饱和度各 +2，光感 +8，锐化 40，清晰 30，不加滤镜 |
| 字幕 | 白字黑边粗体，放在画面上方约 20% 处，每条最多 15 字 |
| 声音 | 人声 -16 LUFS，动作镜头保留原声，其他镜头静音。说话时 BGM 在手机能放出的频段比人声低约 8–10 dB（低音先切掉、只选手机放得出的曲子；音量可调，见下方 BGM 一节）。成片 -14 LUFS，真峰值 ≤ -1.5 dBTP |
| 开头 | 倒饮料进冰杯，约 1.3–1.4 秒 |

## 一次性准备

```bash
bash scripts/bootstrap.sh                 # macOS：装 uv、ffmpeg 等（Windows 用 scripts/bootstrap.ps1）
uv sync --project tools/sample-cut        # 本工具的 Python 依赖
```

- macOS 的 bootstrap 不会自动安装 Homebrew。找不到 ffmpeg 时，先按 https://brew.sh 的命令自己装 Homebrew（要输入开机密码），再重新运行。
- uv 装在 `~/.local/bin`。提示找不到 `uv` 时，先执行 `export PATH="$HOME/.local/bin:$PATH"`。
- `bootstrap.sh` 最后会启动工作台网页（`http://127.0.0.1:8130`）。只用本工具的话，可以用 `bash scripts/stop-local.sh` 关掉。

下面的 `sc <脚本> 参数…` 是 `uv run --project <仓库>/tools/sample-cut python <仓库>/tools/sample-cut/<脚本> 参数…` 的简写。在仓库根目录执行一次下面的命令（macOS 的 zsh 和 bash 都可以），就能直接用 `sc`：

```bash
REPO="$PWD"; sc() { uv run --project "$REPO/tools/sample-cut" python "$REPO/tools/sample-cut/$1" "${@:2}"; }
```

- 每个脚本都在“项目工作目录”里运行，也可以用环境变量 `SAMPLE_CUT_WORK` 指定工作目录。

## 项目目录（每个商品一个，放在仓库外面）

```
<项目>/work/
  spec.json                    从 examples/spec.json 复制，改镜头文件夹名
  copy.json                    文案：每句配哪些镜头文件夹
  takes/selected-takes.json    每个文件夹选好的镜头片段
  voice/<音色>/narration.json + narration.wav
  renders/<版本>/<版本>.mp4
```

- macOS 建议放在 `~/Movies/VideoWorkbench Projects/<商品>/work`。
- Windows 建议放在 `<仓库>/data/deliveries/<日期>/<商品>/work`（`data/` 不会进 git）。
- 素材文件夹需要按编号命名，比如 `13.倒水`、`5.配料表`、`18.展示一杯`，里面放 .mov 或 .mp4。

## 步骤

### 1. 看素材，选镜头

```bash
cd "<项目>/work"
sc make_sheets.py "<素材根目录>"
```

- 每个文件夹会生成若干张缩略图拼板（`takes/sheets/*.jpg`），每条素材取 5 帧并标上时间。
- 看拼板（Codex 可以直接看图），把每个文件夹最好的 1–3 条写进 `takes/selected-takes.json`：

```json
{"13.倒水": [{"file": "<素材绝对路径>", "rank": 1, "in": 1.1, "out": 2.5,
              "subject_center": [0.5, 0.45], "suggest_zoom": 1.1, "why": "水柱连续、标签清楚"}]}
```

- `in` 和 `out` 是动作最好看的那一段（秒）。`subject_center` 是主体在画面中的位置（0–1），推近时会对准这里。
- 背景有杂物时，把 `suggest_zoom` 调大来裁掉。
- 不选：看不到标签的镜头、手抖的镜头、背景有电脑屏幕或歌词的镜头。

### 2. 写文案 `copy.json`

格式见 `examples/copy.json`：

- `product`：商品名。
- `facts_from_package`：瓶身或包装上实际印着的信息，逐条抄下来。
- `not_claimed`：明确不写的内容。
- `sentences`：每句的 `part`、`text`、`shots`（配哪些镜头文件夹）。

规则：

- 文案只用包装上印着的事实。不写价格、库存、功效（减肥、降火、抗氧化等），不跟其他品牌比。
- 约 140–150 字，12 句左右。按 7 字/秒算，大约 21 秒。
- 第一句配倒水镜头，最后一句是行动号召（比如“点左下角”）。

### 3. 配音（三选一）

**A. 云端音色**（需要自己的百炼 Key）：

```bash
export VIDEO_WORKBENCH_DASHSCOPE_API_KEY=你自己的Key
sc voice_build.py longxiaochun_v2 1.3       # 逐句合成后拼接 → voice/longxiaochun_v2_r1.3/
```

**B. 本机克隆自己的声音**（语气最自然）：

1. 先装一次 CosyVoice：macOS 运行 `bash tools/cosyvoice/install.sh`，Windows 运行 `tools/cosyvoice/install.ps1`，需要约 8 GB 空间。
   - macOS 默认装到 `~/Library/Application Support/VideoWorkbench/CosyVoice`，Windows 默认装到 `<仓库>/data/CosyVoice`。
   - 下面命令里的 `$COSYVOICE_HOME` 就是安装目录，没有设置的话先 `export COSYVOICE_HOME=<安装目录>`。
2. 录 3–10 秒自己的声音，记下原话。
3. 整段生成，再剪气口、调语速、对齐时间：

```bash
"$COSYVOICE_HOME/.venv/bin/python" tools/cosyvoice/clone_tts.py --prompt 我的录音.wav \
    --prompt-text "录音里的原话" --text-file copy.json --out voice/me/whole.wav
sc narration_from_whole.py voice/me/whole.wav voice/me     # 剪气口、加速到 6.8 字/秒、逐字对齐
```

第二条命令要用百炼的语音识别来对齐时间，所以也需要 Key。

**C. 只演示**：用 CosyVoice 自带的示例音色（`asset/zero_shot_prompt.wav`）。

**无论哪种，都只能用自己的声音，或者有书面授权的声音。** 不要从视频里扒别人的声音来克隆。

### 4. 出片

```bash
sc render.py voice/me v1
```

- 输出 `renders/v1/v1.mp4`，同时生成 `edit-plan.json`、`captions.srt` 和剪映草稿要用的音频。
- 输出结果里应该写着 `"true_peak"` ≤ -1.5。

### 5. 加 BGM（可商用，需署名）

```bash
sc bgm_pick.py 30 && sc bgm_download.py           # 第一次：从 incompetech.com 下载 30 首轻快纯音乐（约 200 MB）
sc add_bgm.py renders/v1/v1.mp4 Carefree renders/v1/v1-BGM-Carefree.mp4
```

- 每首都会生成一个 `.credit.txt`。**发布时把里面那一行英文原样贴进作品简介**，这是 CC BY 4.0 协议的署名要求。
- **音量**：默认 -20，说话时 BGM 只轻微压低约 3 dB。先切掉手机放不出来的 180 Hz 以下低音，并跳过以低音为主的曲子（`bgm_analyze.py` 打分），所以手机外放听得清楚。想调音量有两种方式：
  - `sc add_bgm.py <成片> <曲名> <输出> -20`：数值越大，音乐越大，-18 更大、-23 更小。
  - `produce.py --bgm-lufs -18`，或在 `sample-cut.json` 里改 `bgm_lufs`，以后每条都按这个音量。
- 不要下载抖音曲库的音乐来自己混。抖音曲库的音乐只在剪映或抖音里面添加。

### 6. 剪映草稿（可选，想手动微调时用）

```bash
sc make_draft.py v1 一茶茉莉白牡丹 --bgm "<曲库>/tracks/Carefree.mp3" --dry-run   # 先试运行，只检查不写入
sc make_draft.py v1 一茶茉莉白牡丹 --bgm "<曲库>/tracks/Carefree.mp3"             # 关掉剪映后再运行
```

- 草稿总是新建，不会覆盖已有草稿。写入前会备份剪映的草稿索引。
- 剪映草稿目录不在默认位置时，设置 `JIANYING_DRAFT_ROOT` 和 `JIANYING_DRAFT_INDEX`。

### 7. 质检

```bash
ffmpeg -hide_banner -i renders/v1/v1.mp4 -af ebur128=peak=true:framelog=quiet -f null - 2>&1 | tail -12   # 约 -14 LUFS，真峰值 ≤ -1.5
sc prosody.py me=voice/me/narration.wav               # 语调起伏：老师样片约 17.6 半音，低于 12 听起来就平
sc asr_check.py voice/me/narration.wav                # 识别回来的文字是否和文案一致
```

- 每 2 秒抽一帧检查：有没有黑场，字幕有没有挡住标签，背景有没有电脑屏幕。
- 把发现的问题写进交付目录的 `先看这里.md`。

### 8. 发布

- 发布由人在抖音 App 或网页（creator.douyin.com）上自己完成，最后的“发布”按钮由本人点。
- 文案里要带上 BGM 署名。

## 冒烟测试

```bash
uv run --project tools/sample-cut python tools/sample-cut/smoke_test.py
```

不需要真实素材、Key 和网络。脚本会用合成画面和声音把整条流程跑一遍：

- 依次运行选镜头拼板、出片、加 BGM、剪映草稿试运行。
- 检查编码器、真峰值、响度、时长，以及字幕有没有烧进画面。
- 输出一帧 `smoke-frame.png`，可以肉眼看中文字幕有没有显示正常。

GitHub 的 macOS CI 每次都会跑这个测试。

## 平台差异

| 项 | Windows（已验证） | macOS（GitHub Mac 云电脑已验证） |
|---|---|---|
| AAC 编码 | `aac_mf`，自带 `aac` 兜底 | `aac_at`，自带 `aac` 兜底 |
| 字幕字体 | `styles.json` 里的 OFL 字体（`fonts_download.py` 下载）；缺字体时用 Microsoft YaHei | 同左；缺字体时用系统黑体（苹方或冬青黑体里最粗的一档） |
| 字幕烧录 | 两边都用 Pillow 把字幕画成透明 PNG 再叠加，不依赖 libass | 同左（Homebrew 默认的 `ffmpeg` 没有 libass 也没关系） |
| 剪映草稿目录 | `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft` | `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft` |
| 数据目录（BGM、CosyVoice） | `<仓库>/data/` | `~/Library/Application Support/VideoWorkbench/` |
| CosyVoice | CPU，约 13 倍实时（2.6 秒音频算 35 秒） | GitHub 的 M1 虚拟机约 40 倍实时（2.5 秒音频算 100 秒）；真 M 芯片应更快 |

ffmpeg 自带的 `aac` 编码器遇到明亮的 BGM 时，真峰值会冲到 +3 dBTP，所以优先用系统编码器。

- 每次编码后都会重新测真峰值，超过 -1 dBTP 就换下一个编码器。都不行就报错，不会交出破音的文件。
- 在 Mac 上第一次运行时，请确认输出里的 `"encoder"` 是 `aac_at`，并听一遍成片。

`pyJianYingDraft` 生成的草稿只在 Windows 剪映上打开过。Mac 版剪映能不能打开，要在 Mac 上实际导入一次确认（云电脑装不了剪映）。

Mac 全流程验收：`.github/workflows/mac-acceptance.yml` 在全新 Mac 上安装 CosyVoice，然后用合成画面做一条完整视频，并把交付文件夹上传为 artifact `mac-acceptance-delivery`。改到配音相关代码时自动运行，也可以在 Actions 页面手动运行。
