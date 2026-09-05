# Codex 启动与能力操作指南

本文件供 Codex 或其他代码代理读取。普通用户的完整说明见 `docs/capabilities-and-configuration.md`；机器可读能力清单见 `services/control-plane/app/capability_catalog.json`。

## 不可违反的事实

1. 本地上传、分析、剪辑、字幕、预览、质检和剪映草稿不需要任何云端 Key。
2. 不得为了启动本地模式向用户索取或要求粘贴 Key、Secret、Token、AK/SK、Cookie、验证码或密码。
3. 不得读取剪贴板中的秘密，不得在命令输出、日志、截图、提交或回复中回显秘密。
4. 平台审批、OAuth、组织授权、系统权限、付费开通和首次打开剪映必须由用户完成。
5. 未配置可选服务时必须说明实际降级路径，不能把 `not_configured` 描述为系统不可用。
6. 只把真实验证过的 Mock、草稿生成、文件复制、平台发布分别按其真实边界报告。

## fresh clone 启动顺序

### 1. 只读检查

```bash
git status --short --branch
python3 scripts/doctor.py
```

Windows 没有 `python3` 时用：

```powershell
python scripts/doctor.py
```

不得因为 doctor 报告缺少云端配置而阻止本地启动。

### 2. 平台启动

macOS：

```bash
bash scripts/bootstrap.sh
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

### 3. 健康和首次启动

- 检查 `http://127.0.0.1:8130/health`。
- 打开 `http://127.0.0.1:8130/`；首次访问应返回工作台和非强制引导，不能把用户重定向后困在配置页。
- 用户可以选择“先直接创作”，也可以主动进入 `http://127.0.0.1:8130/setup`。
- 确认 FFmpeg、FFprobe、数据目录和收件箱状态。
- 本地环境就绪后，允许用户点击“使用本地模式进入工作台”；不要等待可选服务全部变绿。

## 能力决策树

```text
用户只要上传/剪辑/字幕/预览/剪映草稿？
  是 → 零 Key 本地模式。
  否 → 继续判断：
       要更高质量云转写？→ BigASR，可选，逐任务云同意。
       要云旁白？→ TTS，可选；失败保留原声。
       要教程/爆款结构分析？→ Dify，可选；失败用本地策略。
       要公共素材？→ Pexels/Pixabay，可选；否则用户上传/本地授权库。
       要生成素材？→ Seedance，可选且可能计费，不得自动触发。
       要抖音搜索/发布？→ 必须应用权限；发布还必须用户 OAuth。
       要钉钉收件？→ 必须组织应用与机器人授权。
       要让服务器按课程自动剪辑？→ 课程入库/处理/自动作业 API；本地基线无需 Key。
       要自动进用户剪映？→ 服务器生成包，本机同步助手领取并导入。
       要远程多人访问？→ 服务器/域名/HTTPS，不影响本地模式。
```

## 配置映射

| 能力 ID | 读取的配置 | 未配置时 |
| --- | --- | --- |
| `local_intake` | 无云端配置；只要求素材权利确认 | 本地上传与收件箱直接可用 |
| `local_analysis` | 无云端配置；依赖 FFmpeg/Whisper/OCR | 正式模型失败时记录原因并降级本地预览模型 |
| `local_editing` | 无云端配置 | 使用内置选段与 9:16 编排策略 |
| `local_audio` | 无云端配置 | 生成本地字幕并保留原始音轨 |
| `quality_and_draft` | 无云端配置；剪映目录自动发现或用户选择 | 未安装剪映仍生成 MP4、报告和草稿 ZIP |
| `volcano_asr` | `VIDEO_WORKBENCH_VOLCANO_ASR_API_KEY` 或 App Key + Access Key | 本地 `large-v3` |
| `volcano_tts` | `VIDEO_WORKBENCH_VOLCANO_TTS_API_KEY`、资源 ID、音色 | 保留原始音轨 |
| `dify` | Base URL、教程 Key、爆款 Key | 本地剪辑策略与候选文案 |
| `public_materials` | Pexels 和/或 Pixabay Key | 用户上传、本地授权素材 |
| `seedance` | 方舟 Key、模型端点 | 不生成新素材 |
| `volcengine_usage` | 本地加密存储中的只读 IAM AK/SK | 仅本地计量 |
| `douyin_search` | Client Key、Client Secret、Device ID、平台权限 | 公开网页证据/人工导入 |
| `douyin_publish` | Open ID、Access Token、发布权限 | MP4、文案和剪映草稿 |
| `dingtalk` | 钉钉 Client ID/Secret、组织授权 | 工作台上传 |
| `course_automation` | 无必需云 Key；要求课程与真实授权状态 | 模拟钉钉事件或工作台入库 |
| `remote_jianying_sync` | HTTPS 地址和设备访问令牌 | 保留服务器草稿包等待设备 |
| `remote_deployment` | 服务器、SSH、域名和 HTTPS | 继续使用 `127.0.0.1` 本机应用 |

完整变量和默认值以 `services/control-plane/app/config.py` 与 `.env.example` 为准；不要在文档中复制任何实际值。

## macOS 与 Windows 的配置差异

- macOS 原生脚本不读取仓库 `.env`。可选配置只能由用户在启动进程的环境中设置；Codex提供变量名和命令骨架，但用户本人粘贴值。
- Windows 当前使用 Docker Compose，读取被 Git 忽略的仓库根 `.env`。
- 本地基线在两个平台都不需要这些可选配置。

## 诊断顺序

1. `GET /health`：服务、数据库和交付目录。
2. `GET /api/local-runtime`：FFmpeg、FFprobe、运行目录和剪映发现。

Windows 默认运行目录位于当前用户的 `%LOCALAPPDATA%\VideoWorkbench`，不会因为机器存在 `B:` 盘就自动改盘。需要使用其他磁盘时，在安装同步助手时显式传入 `-InstallDir` 和 `-DataDir`；macOS 继续使用 `~/Library/Application Support/VideoWorkbench`。
3. `GET /api/setup/status`：静态能力清单和实时服务状态。
4. 任务卡住时看任务状态，再看任务目录中的时间线、渲染和质量报告。
5. 云能力失败时查看模型路由和 `fallback_reason`；不得直接断言 Key 无效。
6. 用量问题区分官方余额、资源包/赠送额度和本地累计调用，三者不能互相替代。

## 验收命令

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
uv run --project services/control-plane --extra test pytest services/control-plane/tests -q
node --check services/control-plane/app/static/setup.js
node --check services/control-plane/app/static/workbench.js
python scripts/verify-fresh-clone.py --dry-run
```

只在看到当前执行的退出码为 0、测试零失败、fresh-clone 返回 `status=ok` 后，才能说仓库已验证可 clone 运行。历史测试数字不是当前证据。

## 需要用户本人做的动作

- 在云厂商或平台创建和付费开通服务。
- 在自己的终端或本地安全界面填写秘密。
- 抖音应用审批、权限申请和发布账号 OAuth。
- 钉钉组织管理员授权。
- macOS 文件/自动化权限弹窗。
- 安装并至少打开一次剪映，必要时选择草稿目录。
- 购买服务器、提供 SSH 目标、配置域名和备案。

## 课程自动剪辑与设备同步

- 用户入口 `/courses`：导入教程视频/TXT与配套视频，选定素材、需求、日程、目标电脑和云处理同意；无需 Codex 常驻执行。
- `POST /api/course-schedules` 保存课程计划；`POST /api/course-schedules/{id}/run` 持久排队并立即返回；`GET /api/course-schedules/{id}/runs` 查询真实阶段、job_id/task_id；`PATCH .../{id}` 仅切换 enabled。
- 计划默认暂停、非商用、不同意云处理；worker 在 `AUTOMATION_SCHEDULER_ENABLED=true` 时随单实例服务启动，不依赖旧关键词日程开关 `AUTOMATION_ENABLED`。旧关键词自动化与课程计划是独立业务，不可混为已连通。
- 一个计划按其时区每天最多一条（手动与定时共用防重）；错过时间只补当前日期、不追补历史。暂停不取消已排队工作。选定素材固定，不保证每日自动换素材；修改配置请新建计划并暂停旧计划。
- 排队时冻结课程/素材/需求/设备配置，执行时再次校验素材权利与设备可用性；缺配方会先学习教程，空规则阻止普通剪辑替代。普通课程作业也输出 `learned-course-recipe.json` 与 `tutorial-segments.json`。
- 选定 device_id 的作业在创建时即绑定，只进入该设备队列。未选目标时保留本地导入/未分配设备认领兼容路径；服务器部署必须指导用户先配对并选择目标。
- 服务重启把仍 running 且无终态作业的记录标为 interrupted，不自动重复渲染。检查关联作业与已产生文件后由管理员决定重试，不删除中断证据。
- 只支持一个 API 进程、一个工作区、SQLite 持久队列；不要用多个 Uvicorn worker 或多个副本运行恢复逻辑。外部服务授权、真正钉钉网盘与 Mac GUI 验收须独立标注，不能由 mock/CI 替代。
- `POST /api/courses/intake` 接收教程、案例和素材；`POST /api/courses/{id}/process` 生成带来源引用的规则并切分素材镜头。
- `POST /api/course-edit-jobs` 使用最新规则和已授权课程视频执行真实剪辑。商用任务只接受 `commercial_authorized` 素材。
- `POST /api/tutorial-learning-demo` 启动可重复的完整验收，`GET /api/tutorial-learning-demo/{run_id}` 读取阶段、错误、任务与证据链接。不要同步阻塞 HTTP 请求等待渲染；轮询到 `completed` 或 `failed`。
- 验收必须检查教程 ASR 提供方、`tutorial-visual-analysis.json`、`tutorial-segments.json`、带时间码规则、`course-rule-trace.json`、`course-comparison.json`、`quality-report.json` 和最终媒体探测；只看到转写文本或一张图片不算通过。
- `tutorial-segments.json` 至少要证明讲解、软件操作和成片示例被分开记录。只有 `lecture` 片段可直接生成规则；`software_operation`、`finished_example` 只能关联规则，不能把其中的示例广告口播直接当作用户剪辑要求。
- 演示的教学画面与被剪素材必须不同；素材账本必须保留来源、许可链接、SHA-256 和下载回退信息。
- 质量门禁通过后任务自动批准；失败仍停在诊断状态，不会交付半成品。
- 服务器没有本机剪映目录时，作业进入 `awaiting_device`。管理员通过 `POST /api/devices/pairing-codes` 生成十分钟有效的一次性码；Mac/Windows 首次运行同步助手时输入一次，之后使用哈希验证的设备令牌领取草稿、新建工程、启动剪映并回报完成。
- 同步助手运行时不需要 Codex；生产服务器必须使用 HTTPS 和访问控制，不能把裸 API 暴露到公网。

把这些动作一次性列在最终交接中，不要在每个实现步骤重复打断用户。

## Git 与交接

- 不提交 `.env`、运行数据、模型、视频、浏览器状态或任何凭据。
- 修改能力边界时同步更新机器清单、人类指南、Codex 指南、配置助手测试和 `docs/progress.md`。
- 报告时分开写：已实现、已验证、需要用户动作、外部平台待审批。
- 用户要求别人 clone 时，必须给出当前分支/提交状态；没有推送到公开默认分支时不能说别人已经能获取最新改动。
