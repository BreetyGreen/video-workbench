# 全自动视频工作台

## GitHub 克隆后直接启动

这个项目首先面向 Apple Silicon Mac。把仓库交给 Codex 后，它会读取 `AGENTS.md`，自动检查依赖、创建本地目录、发现剪映并启动工作台；本地基线不需要填写 .env，也不要求 Docker。

> **最重要的结论：剪辑本身不需要 Key。** 本地上传、视频理解、自动选镜头、9:16 排版、字幕、预览、质量门禁和剪映草稿都能零 Key 运行。Key 只用于云端质量增强、外部素材、热点/发布、钉钉入口和官方用量查询。

```bash
git clone https://github.com/BreetyGreen/video-workbench.git
cd video-workbench
bash scripts/bootstrap.sh
```

如果你使用 Codex，只需要在克隆后的目录里说“按照 AGENTS.md 启动项目”。脚本会把运行数据放在 `~/Library/Application Support/VideoWorkbench`，把待导入素材放在 `~/Movies/VideoWorkbench Inbox`，仓库本身保持可删除、可重新克隆。

启动后浏览器进入 <http://127.0.0.1:8130/>。首次访问会显示可跳过的使用引导：可以点“先直接创作”立即使用零 Key 本地剪辑，也可以点“打开配置助手”检查 FFmpeg、本地目录、剪映位置并按需连接云服务。配置助手地址是 <http://127.0.0.1:8130/setup>，以后也始终可以从侧栏重新打开。

| 能力 | 新用户是否需要配置 | 未配置时 |
| --- | --- | --- |
| 上传、分析、剪辑、字幕、预览、剪映草稿 | 不需要 | 直接使用本地模式 |
| 火山方舟、ASR/TTS、用量查询 | 按需 | 本地 Whisper、本地剪辑和本地计量 |
| Dify 教程/爆款分析 | 按需 | 本地剪辑策略和候选文案 |
| Pexels/Pixabay 公共素材 | 按需 | 上传自有视频或使用本地授权素材 |
| 抖音官方热点与发布 | 需要平台审批和账号授权 | 公开热点证据与剪映本地草稿 |
| 钉钉素材入口 | 需要组织应用授权 | 工作台直接上传 |

公开仓库不会附带维护者的账号凭据。每位用户只需为自己真正使用的外部服务完成一次授权；申请入口、所需字段、本地替代方案和当前连接状态都在配置助手中展示。

开始前建议先看：

- [普通用户：剪辑能力与配置完整指南](docs/capabilities-and-configuration.md)
- [Codex：启动、诊断与配置决策指南](docs/codex-operator-guide.md)
- [只有账号本人能完成的授权清单](docs/user-required-actions.md)
- 机器可读事实源：`services/control-plane/app/capability_catalog.json`

Windows 仍保留兼容启动入口：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

macOS 详细说明与故障定位见 [macOS 本地运行手册](docs/runbooks/macos-local.md)。云端模型、钉钉和抖音开放平台都是后续可选能力，不会阻塞本地上传、分析、剪辑、预览和剪映草稿生成。

> 2026-08-21 收口入口：当前状态见 `docs/progress.md`，生产部署见 `docs/deployment.md`，必须由账号本人完成的购买与授权见 `docs/user-required-actions.md`。

这是一个本地、可审计、带界面的短视频生产底座：ArcReel 负责素材和项目工作台，FastAPI 控制面负责本地视频理解、智能剪辑、预览、剪映草稿、审核与连接器，Dify 负责可选的教程拆解和趋势分析，钉钉 Stream 负责可选的素材入口。

剪辑引擎会对全部视频素材执行转写、静音/场景/关键帧/OCR 分析，自动选择高光并交替素材，输出 1080×1920 成片、ASS/SRT 字幕、-14 LUFS 音轨、竖屏封面和可编辑剪映草稿。MP4 与草稿共用一份 `edit-timeline.json`，审核页会展示每个选段的来源、评分和入选原因。

任务可选择三档制作质量：生产档在获得逐任务云端同意且配置火山引擎凭据时优先使用豆包录音文件识别极速版，未授权或云端失败时使用本地 Whisper `large-v3`；本地隐私档固定使用 `large-v3`；快速预览档使用 `small`。因此小模型只负责预览与故障兜底，不再承担正式成片的默认理解工作。

可额外上传一条参考爆款视频。系统只提取钩子窗口、剪切密度、镜头长度、字幕/OCR 和节奏结构来指导自有素材编排，不会把参考视频画面复制进成片。每次渲染后还会自动检查画布、音视频流、时长、时间线连续性、首帧钩子、黑帧、长静音和字幕，阻断项未通过时审核页不能批准。

## 快速启动

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

启动后：

- ArcReel：<http://127.0.0.1:1241>
- 视频生产控制台：<http://127.0.0.1:8130>
- 官方音色中心：<http://127.0.0.1:8130/voices>
- 热点证据中心：<http://127.0.0.1:8130/trends>
- 授权素材中心：<http://127.0.0.1:8130/materials>
- 用量与成本：<http://127.0.0.1:8130/settings/cloud-usage>
- 控制面 API 文档：<http://127.0.0.1:8130/docs>
- 任务审核页：验证脚本完成后会输出具体 URL
- 每日自动化：默认每天北京时间 08:30 执行；可通过 API 或 `.env` 修改关键词与时间

日常操作优先使用视频生产控制台：可以上传素材和教程、配置每日关键词、立即运行流程、查看任务队列与热点证据，并进入人工审核页。ArcReel 保留为更细的视频项目与素材工作区。

首页“云端余量”会展示火山引擎官方账户余额、方舟聚合用量，以及本机逐任务记录的 ASR 秒数、TTS 字符和 Dify Token。只有需要官方余额时才按 `docs/runbooks/cloud-usage.md` 配置专用只读 AK/SK；密钥加密保存在本地，页面只显示掩码。未配置不影响剪辑。

Windows/Docker 首次启动会从 `.env.example` 创建未跟踪的 `.env`，并自动生成 ArcReel 本地密码与令牌密钥。脚本不会打印这些值。macOS 原生脚本不会主动读取仓库 `.env`；需要可选云能力时由用户在启动进程的环境中设置对应变量。Whisper 与 OCR 模型首次使用时下载并缓存，后续启动复用。

如果 Windows/Hyper-V 把 `8130` 放进系统保留端口段，启动器会从 `8130` 起自动选择下一个可用的本机端口，并在启动结果中显示实际地址。检测到旧容器时会继续使用它原来的任务数据目录，不会因为仓库换目录而显示成空工作台。

## 可选接入

- Dify：按 `docs/runbooks/dify.md` 导入两份 DSL，并在 `.env` 填写两套应用 API Key。
- 云端用量：按 `docs/runbooks/cloud-usage.md` 配置专用只读 IAM 凭证和额度预警线。
- 火山引擎豆包 ASR：按 `docs/runbooks/volcano-bigasr.md` 配置；只有任务勾选云端处理同意时才发送音频。
- 钉钉：按 `docs/runbooks/dingtalk.md` 创建 Stream 机器人，配置凭据后使用 `start.ps1 -EnableDingTalk`。
- 抖音热点：只接抖音开放平台官方视频搜索接口；填写 Client Key、Client Secret、Device ID 并为应用申请 `aweme.dy.video_search` 能力。
- 素材库：默认把任务中已勾选“拥有使用权”的视频去重登记到本地授权目录；可选填写 Pexels/Pixabay API Key，从官方视频搜索接口获取竖屏素材并保留作者、原页和许可链接，详见 `docs/runbooks/materials.md`。
- 剪映：草稿 ZIP 可在未安装剪映时生成；安装后运行 `scripts/detect-jianying.ps1` 并人工打开样例，才可把兼容性状态改为已验证。

安装并至少打开一次剪映后，可把审核页对应草稿安全导入本机草稿目录。脚本会优先识别本机 B 盘的 `B:\JianyingData\Drafts\JianyingPro Drafts`，也可显式传入其他目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\import-jianying-draft.ps1 -TaskId <任务 UUID>
```

脚本只创建新的草稿目录，遇到同名目录会停止，不会覆盖已有剪映工程。导入时会把容器内 `/data/...` 素材路径自动重写为 B 盘草稿内 `assets` 的绝对路径，并逐条验证媒体文件存在。

每日流程会依次完成：获取官方热点证据（已配置抖音时）→ 同步已确认版权素材 → 优先调用 Pexels 官方接口或回退本地授权目录 → 按关键词创建当日唯一任务 → 自动剪辑、旁白、字幕、封面、文案和剪映草稿 → 等待人工审核。相同日期与关键词不会重复建任务；一个关键词已完成后会继续尝试列表中的下一个关键词。

## 安全边界

- 不使用浏览器 Cookie 自动发布抖音。
- 未确认版权、缺少预览/草稿/清单、清单无效或成片质量门禁失败时不能批准。
- Dify 和钉钉未配置时明确显示 `not_configured`，本地视频理解、智能剪辑、预览与剪映草稿仍可运行。
- 所有状态和素材默认保存在 `data/`，该目录不提交 Git。

完整的启动、备份、升级和排障步骤见 [运行手册](docs/runbook.md)。
