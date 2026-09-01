# 剪辑能力与配置完整指南

## 先说结论：本地剪辑不需要 Key

别人 clone 仓库后，不填写 `.env`，也不申请火山引擎、Dify、抖音、钉钉、Pexels、Pixabay 或 Seedance，就可以完成这条本地主链：

```text
上传已授权视频
  → 本地媒体分析、场景/静音/关键帧/OCR
  → 本地 Whisper 转写
  → 自动选高光、钩子和镜头节奏
  → 9:16 排版、字幕、原声/混音判断
  → FFmpeg 渲染、封面和质量门禁
  → MP4 + 字幕 + 时间线 + 质检报告 + 剪映草稿 ZIP
```

云端 Key 的作用是增强某个环节，或者连接外部平台；它们不是“让剪辑引擎启动”的许可证。

## clone 后如何开始

### Apple Silicon Mac（首选路径）

```bash
git clone https://github.com/BreetyGreen/video-workbench.git
cd video-workbench
bash scripts/bootstrap.sh
```

脚本会安装固定版本的 Python/uv，检查并安装 FFmpeg，创建用户目录，启动仅监听 `127.0.0.1:8130` 的本地应用。首次转写会下载 Whisper 模型，首次 OCR 会下载或初始化 OCR 模型，因此第一次比后续慢。

首次打开工作台会出现一次可跳过的引导。选择“先直接创作”会记住本地模式并关闭引导；选择“打开配置助手”才进入完整检测和外部服务连接页。两种选择都不会强制用户填写 Key，配置助手之后仍可随时重放。

macOS 运行数据不写进仓库：

- 状态：`~/Library/Application Support/VideoWorkbench`
- 模型缓存：`~/Library/Caches/VideoWorkbench`
- 监听收件箱：`~/Movies/VideoWorkbench Inbox`

### Windows 兼容路径

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

当前 Windows 路径会调用 Docker Compose。需要 Docker Desktop；本地运行配置位于被 Git 忽略的 `.env`。

### 让 Codex 启动

在仓库目录告诉 Codex：

> 按照 AGENTS.md 和 docs/codex-operator-guide.md 启动并验证本地模式，不要向我索取任何云端 Key。

## 三类能力怎么区分

| 分类 | 含义 | clone 后状态 |
| --- | --- | --- |
| 无需 Key | 完全在本机完成的剪辑主链 | 依赖和模型就绪后直接使用 |
| 可选增强 | 有 Key 时提升质量、增加素材或显示成本 | 不配置会使用明确的本地降级路径 |
| 外部授权 | 依赖平台审批、OAuth、组织权限或服务器 | 代码不能替账号本人完成 |

机器可读的同一份事实位于 `services/control-plane/app/capability_catalog.json`，运行后也可以通过 `GET /api/setup/status` 的 `capabilities` 字段读取。

## 无需 Key 的本地能力

### local-intake：素材接收与授权登记

- 支持：一次上传多个视频、记录来源和授权状态、本地去重、收件箱监听。
- 需要：用户拥有或已经取得素材使用权。
- 不会做：不会把抖音/小红书公开视频自动视为可剪辑素材。
- 数据：视频保存到本机运行目录。

### local-analysis：本地视频理解

- FFprobe：时长、尺寸、帧率、音视频流。
- FFmpeg：场景变化、静音区间、关键帧和截图。
- RapidOCR：识别画面已有文字，为字幕冲突和参考结构提供证据。
- faster-whisper：本地语音转写、分段和词级时间戳。
- `fast_preview` 使用 `small`；`production`/`local_privacy` 优先 `large-v3`。
- 如果正式模型失败，会把原因写入任务清单，再降级预览模型；不会偷偷把本地隐私任务发到云端。

### local-editing：本地智能剪辑

- 根据人声置信度、画面清晰度、对比度、曝光和场景变化生成候选片段。
- 从开头钩子窗口优先选择首镜头，避免重复使用同一来源区间。
- 多素材时尽量交替来源，按目标时长生成连续时间线。
- 画布为 1080×1920；横屏素材使用模糊背景和居中前景适配竖屏。
- 每段保留来源、时间码、评分和入选原因，写入 `edit-timeline.json`。

没有 Dify 时，时间线引擎标记为 `local_intelligent`；配置 Dify 教程工作流后可以标记为 `dify_enhanced`。两者都会生成真实时间线，不是演示页面。

### local-audio：字幕与音频路由

- 有足够原始人声：保留原声。
- 有少量人声且属于讲解/商品/教程：计划使用混合旁白。
- 没有有效人声：计划使用完整旁白。
- TTS 未配置或调用失败：回到原始音轨继续生成，并留下警告，不会只合成第一段后假装完成。
- 输出 ASS 和 SRT；旁白存在时，字幕按旁白全文重新分段并覆盖整条旁白。
- 渲染阶段做音量、混音、背景音乐 ducking 和目标响度标准化。

### quality-and-draft：交付物、质检和剪映草稿

每个完成任务至少包含：

- `preview.mp4`：H.264/AAC、faststart 的预览成片。
- `captions.ass`、`captions.srt`：烧录和可编辑字幕。
- `cover.jpg`：竖屏封面。
- `edit-timeline.json`：镜头、字幕、音频和封面计划。
- `render-report.json`：渲染引擎、画布、音频路由和警告。
- `quality-report.json`：质量门禁证据。
- `draft.zip`：可编辑剪映草稿。

质量门禁检查交付物完整性、视频/音频流、画布、时长漂移、时间线连续性、首帧钩子、黑场、长静音、字幕、旁白时长和字幕覆盖。阻断项失败时不能批准。

未安装剪映也能生成 `draft.zip`。安装并至少打开一次剪映后，Windows/macOS 启动器会写入本机运行清单；审核页的“导入剪映并打开”会校验 ZIP、质量门禁和媒体路径，只创建新工程、不覆盖已有草稿，然后请求本机助手唤起客户端。`draft.zip` 只作为恢复下载包。生成并导入草稿不等于在所有剪映版本上自动导出成片。

## 可选增强：什么时候才需要 Key

### volcano-asr：火山引擎 BigASR

用途：生产档的云端中文转写。

需要以下任一种凭据组合：

- `VIDEO_WORKBENCH_VOLCANO_ASR_API_KEY`；或
- `VIDEO_WORKBENCH_VOLCANO_ASR_APP_KEY` + `VIDEO_WORKBENCH_VOLCANO_ASR_ACCESS_KEY`。

同时必须在具体任务中允许云端处理。未配置、未同意或接口失败时，自动使用本地 Whisper `large-v3`；所以它不阻塞剪辑。

数据边界：启用后，任务音频会发送到配置的火山语音识别端点。

### volcano-tts：火山引擎豆包 TTS

用途：为商品介绍、教程和讲解视频生成旁白。

主要配置：

- `VIDEO_WORKBENCH_VOLCANO_TTS_API_KEY`
- `VIDEO_WORKBENCH_VOLCANO_TTS_RESOURCE_ID`
- `VIDEO_WORKBENCH_VOLCANO_TTS_VOICE_TYPE`
- `VIDEO_WORKBENCH_VOLCANO_TTS_ENDPOINT`

如果单独的 TTS Key 留空，当前代码会尝试复用 ASR API Key；是否可用仍取决于该 Key 是否拥有 TTS 服务权限。旁白不可用时回到原声，不阻断输出。

数据边界：旁白文本会发送到火山语音合成接口。

### dify：教程与爆款分析工作流

Dify 不是剪辑器。它只给本地剪辑引擎提供结构化建议：

- 教程工作流：把教程、用户要求和媒体摘要转换为剪辑配方。
- 爆款工作流：结合趋势证据生成结构分析、标题、文案和话题候选。

配置：

- `VIDEO_WORKBENCH_DIFY_BASE_URL`
- `VIDEO_WORKBENCH_DIFY_TUTORIAL_API_KEY`
- `VIDEO_WORKBENCH_DIFY_VIRAL_API_KEY`

没有 Dify 时，本地策略仍会选段、剪辑并生成候选文案。只有地址和两个工作流 Key 都齐全时才算完整连接；只有一个 Key 时显示部分连接。

### public-materials：Pexels / Pixabay

用途：从官方搜索接口找带来源记录的公开视频候选。

- Pexels：`VIDEO_WORKBENCH_PEXELS_API_KEY`
- Pixabay：`VIDEO_WORKBENCH_PIXABAY_API_KEY`

至少配置一个即可增强素材搜索。系统会记录作者、原页面和许可链接，但使用者仍需遵守具体素材许可和平台规则。没有 Key 时使用上传视频和本地授权素材。

### seedance：生成 9:16 素材

配置：

- `VIDEO_WORKBENCH_SEEDANCE_API_KEY`
- `VIDEO_WORKBENCH_SEEDANCE_MODEL`
- 可选 `VIDEO_WORKBENCH_SEEDANCE_BASE_URL`

当前能力是创建 5 秒、9:16 的生成任务并查询状态。系统不会因为账户可能有赠送额度就自动发起付费任务；未配置时使用已有素材。

### volcengine-usage：只读用量与成本

这组凭据只负责查询官方余额/用量，不负责模型推理：

- 在 `/settings/cloud-usage` 中配置专用 IAM 用户的只读 AK/SK。
- 密钥加密保存在本机，页面只显示掩码。
- 未配置时仍展示本地记录的 ASR 秒数、TTS 字符和 Dify Token。
- 官方余额显示为 0 不等于所有赠送资源都耗尽；不同产品的资源包可能没有统一余额接口。

它完全不影响视频能否生成。

## 外部授权能力

### course-automation：课程理解与自动成片

课程文件可以来自钉钉，也可以直接调用课程入库接口。服务器会保存教程、案例和素材的角色与 SHA-256，教程规则保留来源页码或时间码，视频素材做镜头切分和检索。创建商用作业时只复制明确标记为 `commercial_authorized` 的视频；只有个人学习权利或未知权利的素材不会进入商用成片。

```text
课程入库 → 教程规则抽取 → 素材镜头索引 → POST /api/course-edit-jobs
→ 多素材 9:16 自动剪辑 → 质量门禁 → 等待本机设备或直接导入剪映
```

该主链复用本地 FFmpeg、字幕、音频路由和草稿生成器，不要求云端 Key。质量门禁通过后不再强制人工点击“批准”；阻断项失败时仍会停止交付并保留证据。

### douyin-search：抖音官方视频搜索

需要：

- `VIDEO_WORKBENCH_DOUYIN_CLIENT_KEY`
- `VIDEO_WORKBENCH_DOUYIN_CLIENT_SECRET`
- `VIDEO_WORKBENCH_DOUYIN_DEVICE_ID`
- 应用获批的视频搜索能力。

搜索结果用于热点和结构证据，不自动获得对应视频的剪辑版权。未获批前可以使用公开网页证据或人工导入趋势数据；项目不会绕过登录、破解签名或规避风控。

### douyin-publish：抖音官方发布

除了应用权限，还需要发布账号本人 OAuth：

- `VIDEO_WORKBENCH_DOUYIN_OPEN_ID`
- `VIDEO_WORKBENCH_DOUYIN_ACCESS_TOKEN`

未授权时系统仍生成 MP4、发布文案、话题和剪映草稿，由用户在客户端完成最终发布。官方“仅自己可见”也是已创建视频，不是剪映式草稿箱。

### dingtalk：钉钉素材入口

需要企业内部应用、Stream 机器人和组织管理员授权。Windows/Docker 连接器读取：

- `DINGTALK_CLIENT_ID`
- `DINGTALK_CLIENT_SECRET`
- 可选 `DINGTALK_ROBOT_CODE`

未配置时直接在工作台上传。钉钉入口只接收组织已授权文件，不把一个 Webhook 当成完整文件下载授权。

### remote-jianying-sync：服务器成片自动进入本机剪映

剪映运行在用户的 Windows/Mac 上，Linux 服务器不能直接写它的草稿目录。因此服务器把通过质量门禁的作业放进 `awaiting_device` 队列，本机轻量同步助手负责下载 `quality-report.json` 和 `draft.zip`、再次校验 ZIP 与媒体路径、只创建新草稿、启动剪映并向服务器回报结果。

普通用户从 [GitHub Releases](https://github.com/BreetyGreen/video-workbench/releases/latest) 下载与系统对应的同步助手。管理员在工作台“配置助手 → 服务器交付”生成十分钟一次性配对码；用户首次安装时输入一次，以后登录系统自动监听，不需要 Codex、Python 或仓库。

开发者调试时也可以直接运行：

```bash
python scripts/sync-jianying-device.py \
  --server-url https://video.example.com \
  --data-dir "$HOME/Library/Application Support/VideoWorkbench Sync"
```

持续监听时追加 `--watch`。首次运行会无回显地要求一次性配对码，成功后只把设备令牌保存到本机运行目录的权限受限文件；也可以从本机环境变量 `VIDEO_WORKBENCH_DEVICE_BEARER_TOKEN` 提供令牌。令牌不会写进命令行和仓库。

当前仓库已经完成单次配对、令牌哈希存储、设备专用队列、下载、导入、剪映启动、结果回报、Windows/macOS 单文件构建和登录自启脚本。Windows 打包产物已在真实机器完成“发现剪映、确认草稿目录可写、请求空队列并正常退出”烟测；macOS 构建由 `macos-14` CI 执行，本机 Windows 无法替代 Mac 做 Gatekeeper 与剪映实机验收。公开分发仍需要维护者提供 Windows 代码签名证书和 Apple Developer ID/公证凭据。

### remote-deployment：服务器、域名和 HTTPS

本机模式不需要服务器。需要多人或跨设备访问时，才购买/分配 Linux 服务器、提供 SSH 权限、配置域名和 HTTPS。服务器上的素材、模型和凭据需要单独备份与访问控制。

## `.env.example` 各组配置说明

| 分组 | 是否阻塞本地剪辑 | 主要用途 |
| --- | --- | --- |
| 本地运行与安全 | 否，启动脚本会给出安全默认值 | 运行目录、数据库、密钥加密主密钥 |
| 本地分析/渲染 | 否 | Whisper 档位、OCR、场景/静音阈值、编码质量 |
| Dify | 否 | 教程拆解、爆款分析、文案候选 |
| 火山 ASR/TTS | 否 | 云转写、云旁白 |
| 抖音 | 否 | 官方搜索和授权发布 |
| Pexels/Pixabay/Seedance | 否 | 公共素材和生成素材 |
| 自动化 | 否 | 每日执行时间、关键词和任务数量 |
| 钉钉连接器 | 否 | 组织文件入口 |

不要把真实值提交到 Git、Issue、截图或聊天。公开仓库只保留空白模板。

## macOS 怎样提供可选凭据

macOS 的本地启动脚本为了避免仓库意外读取秘密，**不会主动读取仓库根目录 `.env`**。需要可选云能力时，由用户在启动该进程的终端中设置对应 `VIDEO_WORKBENCH_*` 环境变量，再运行 `bash scripts/bootstrap.sh`。不要把值发给 Codex；可以让 Codex只给出变量名，由用户在自己的终端粘贴。

Windows/Docker 路径会读取仓库根目录下被 Git 忽略的 `.env`。修改后重新运行启动脚本。

## 四种推荐使用方式

### 方式 1：零 Key 快速剪辑

上传视频 → 选择 `fast_preview` 或 `local_privacy` → 生成 → 查看审核页 → 下载 MP4/草稿。

### 方式 2：本地正式成片

选择 `local_privacy` → 本地 `large-v3` 转写 → 自动剪辑和质检。适合素材不能离开本机的任务。

### 方式 3：云端质量增强

配置 BigASR/TTS；具体任务允许云处理 → 优先云转写和旁白 → 失败自动回退本地并记录原因。

### 方式 4：平台自动化

先完成抖音应用审批和账号 OAuth，或钉钉组织授权 → 配置对应凭据 → 在配置助手确认连接状态 → 再启用搜索、接收或发布。

## 如何判断“已经配置成功”

1. 打开 `/setup`，查看外部服务实时状态。
2. `configured` 表示必要字段存在；`partially_configured` 表示只有一部分增强可用。
3. `oauth_required` 和 `permission_required` 表示代码已就绪，但还需要账号本人或平台处理。
4. “重新检测”只做安全诊断，不回显秘密。
5. 真正验收仍需运行一次最小任务并查看 `edit-timeline.json`、`render-report.json`、`quality-report.json` 和任务清单中的模型路由。

## 当前明确不支持或不承诺的事情

- 不绕过登录、不破解签名、不规避平台风控。
- 不把公开网页视频直接当作已授权素材批量下载剪辑。
- 不承诺所有剪映版本都能自动点击导出；当前可靠边界是草稿生成和安全导入。
- 不把“配置了 Key”当作“平台权限已经审批”或“账号已经 OAuth”。
- 不把官方余额 0 当作所有赠送资源包都为 0。
