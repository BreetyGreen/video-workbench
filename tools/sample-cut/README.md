# 样片标准剪辑（sample-cut）

把一批商品拍摄素材剪成约 24 秒的带货竖屏短视频，节奏、推近、调色、动作原声、字幕和 BGM 都按老师样片实测的标准来。

- 这套脚本由 Codex 或 Claude Code 按步骤调用，不依赖工作台网页服务。
- 支持 macOS 和 Windows。
- 已在 Windows 上做完两条成片（绿豆沙、一茶）。macOS 版尚未在真机上跑过，见文末“平台差异”。

## 样片标准（`examples/spec.json` 的 `targets`）

| 项 | 标准 |
|---|---|
| 时长 | 20–26 秒 |
| 镜头 | 18–26 个，平均 0.95–1.25 秒，单个 0.6–1.9 秒 |
| 语速 | 6.6–7.4 字/秒，气口剪掉 |
| 推近 | 每个镜头 1.10–1.25 倍。动作镜头（倒水、搅拌）推得更多 |
| 调色 | 亮度 / 对比 / 饱和度各 +2，光感 +8，锐化 40，清晰 30，不加滤镜 |
| 字幕 | 白字黑边粗体，放在画面上方约 20% 处，每条最多 15 字 |
| 声音 | 人声 -16 LUFS，动作镜头保留原声，其他镜头静音。BGM 比人声低约 19 dB（相当于剪映音量 10% 左右）。成片 -14 LUFS，真峰值 ≤ -1.5 dBTP |
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

## 平台差异

| 项 | Windows（已验证） | macOS（未在真机验证） |
|---|---|---|
| AAC 编码 | `aac_mf`，自带 `aac` 兜底 | `aac_at`，自带 `aac` 兜底 |
| 字幕字体 | Microsoft YaHei，从 `C:\Windows\Fonts` 读取 | 自动换成 PingFang SC，由 libass 通过 CoreText 查找 |
| 剪映草稿目录 | `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft` | `~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft` |
| 数据目录（BGM、CosyVoice） | `<仓库>/data/` | `~/Library/Application Support/VideoWorkbench/` |
| CosyVoice | CPU，约 13 倍实时（2.6 秒音频算 35 秒） | Apple Silicon CPU，速度未实测 |

ffmpeg 自带的 `aac` 编码器遇到明亮的 BGM 时，真峰值会冲到 +3 dBTP，所以优先用系统编码器。

- 每次编码后都会重新测真峰值，超过 -1 dBTP 就换下一个编码器。都不行就报错，不会交出破音的文件。
- 在 Mac 上第一次运行时，请确认输出里的 `"encoder"` 是 `aac_at`，并听一遍成片。

`pyJianYingDraft` 生成的草稿只在 Windows 剪映上打开过。Mac 版剪映能不能打开，要在 Mac 上实际导入一次确认。
