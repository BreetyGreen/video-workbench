# Claude 项目交接：参考驱动的课程自动剪辑

更新时间：2026-09-09（Asia/Tokyo）。本文件是接手检查点；后续结果写回 `docs/progress.md`，不要继续把历史快照当实时状态。

## 1. 用户到底要什么

用户买了网课，提供了剪辑教学视频、配套商品素材及参考成片。需要系统理解教学中的讲解、软件操作和成片示例，提炼有来源的剪辑规则，再根据参考效果选择独立素材，生成高质量商品视频，最后交付可继续编辑的剪映草稿。

当前优先项是**重新生成绿豆沙视频，并优化可复用的正式流程**。用户只想验收，不要每个小步骤都让其确认；可以自行完成代码修复、测试和已授权范围的操作。遇到本人登录、验证码、付费/权限等真正外部边界才交还用户。

长期方向是服务器处理 + Mac/Windows 本机同步助手，普通用户日常不依赖 Codex/Claude 常驻。不应把“源码可启动”“安装包已发布”“Mac 已验证”“真实钉钉网盘已接通”混成一件事；这些需要独立证据。本轮不要无端扩展成部署或全平台发布。

## 2. 先找对目录和分支

| 项目 | 当前值 |
| --- | --- |
| 实际代码工作树 | `B:/xiaozhu/video-workbench/.worktrees/video-workbench-closure` |
| 用户打开的外层资料目录 | `B:/xiaozhu/全自动视频发布`，不是当前应用代码根目录 |
| Git remote | `https://github.com/BreetyGreen/video-workbench.git` |
| 当前分支 | `codex/macos-user-manual` |
| 本次核实的 HEAD | `29adb937a3d1f91791be5a8160e18c8e90bcb603` |
| HEAD 内容 | `docs: add detailed Mac user operation guide` |
| 本地 Python | `services/control-plane/.venv/Scripts/python.exe`（相对实际工作树） |

**重要：最新优化代码尚未提交。** 2026-09-09 检查发现修改文件以及未跟踪的 director、alignment、cache 服务和测试。只 clone GitHub 或 checkout HEAD 不会得到这批改动。直接接管这份本机工作树；另一台电脑接手前必须由用户授权提交/传递全部必要修改，且排除凭据和媒体。本次交接未执行 commit、push、发布或清理。

首先执行：

```powershell
Set-Location 'B:\xiaozhu\video-workbench\.worktrees\video-workbench-closure'
git status --short --branch
git log -1 --oneline
```

阅读顺序：

1. `AGENTS.md`、`CLAUDE.md`、本交接文档。
2. `docs/progress.md` 最新条目。
3. `docs/codex-operator-guide.md`（名称是 Codex，但规则也适用于 Claude）、`services/control-plane/app/capability_catalog.json`、`docs/capabilities-and-configuration.md`。
4. `docs/superpowers/specs/2026-09-08-reference-driven-production-design.md`。
5. `docs/superpowers/plans/2026-09-08-production-closure.md` 和 `2026-09-08-dify-live-verification.md`。

## 3. 已实现，不等于效果已验收

以下为已有本地实现，接手先核查 diff，不要重复开发：

- **统一 DirectorPlan**：`schemas/director.py`、`services/director_service.py`、`services/pipeline_service.py`、`services/timeline_service.py`。分镜和旁白共用计划，校验素材 ID、源时间范围、重叠及顺序；模型不能指定本地路径。无有效计划时明确降级本地预览，不编造产品卖点。
- **角色化视觉输入**：参考片最多 2 帧、既有课程教程分析最多 2 帧、其余为可剪素材，总计最多 8 帧；图像格式、解码、大小、路径边界有校验。参考/教程标记为不可剪素材；不能把示例广告当当前商品事实。只做有界抽样，不能说完整理解所有课程画面。
- **真实图像上传**：`adapters/dify.py` 调用 `files/upload` 后引用 `inputs.visual_frames`；记录 `analysis/visual-input-evidence.json`。任务必须同意云处理。传输成功不证明模型理解正确。
- **旁白与字幕对齐**：`services/narration_alignment_service.py`。最终配音调速后转写一次，完整文本和真实词时间戳满足约束才采用；否则明确保留估算。保留开头位置、强调样式，最终时间线同时用于成片与草稿。
- **精确输入缓存**：`services/director_cache_service.py`。键包含输入/图像内容、顺序、服务与凭证作用域摘要、工作流版本。`VIDEO_WORKBENCH_DIFY_TUTORIAL_WORKFLOW_REVISION` 默认空即禁用；没核实版本不得伪造版本开启缓存。缓存命中或请求前失败不记上一轮用量。
- **证据边界**：`director-plan.json`、`narration-alignment.json`、`narration-transcript.json`、音频路由和 review manifest 表示实际路径。商品事实、语义匹配、风格与客户端播放未验证时仍为 unknown。

未完成：独立商品事实验证、完整语义/风格闭环和自动返工、新版真实绿豆沙成片、双商品效果验收、Windows/macOS 剪映客户端回放。不要因报告无机械错误就自动宣称效果达标。

## 4. 运行环境：今天已发生变化

2026-09-09 本次交接的只读检查：

- `http://127.0.0.1:8330/health`：不可达。
- `http://127.0.0.1:8330/courses`：不可达。
- `http://127.0.0.1:5501/`：HTTP 200（Dify）。

9 月 8 日曾成功启动 8330，不能因此认定现在仍在运行。当前不可达原因未进一步诊断；本次只写文档，没有重启。

恢复顺序：先检查端口及进程，确认没有另一个进程使用同一个 SQLite；备份当前数据库，再以前台单进程启动。既有备份 `.validation/control-plane-before-start-20260908-2.db` 已在上次通过完整性检查，但不是今天数据的备份。使用 SQLite backup 创建新名称，不覆盖旧备份，不用运行中的数据库文件裸复制代替一致性备份。

```powershell
Set-Location 'B:\xiaozhu\video-workbench\.worktrees\video-workbench-closure'
Get-NetTCPConnection -State Listen -LocalPort 8330 -ErrorAction SilentlyContinue
netsh interface ipv4 show excludedportrange protocol=tcp
# 完成数据库与同库进程检查、备份后再启动：
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
$env:VIDEO_WORKBENCH_DIFY_BASE_URL='http://127.0.0.1:5501/v1'
& .\services\control-plane\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/control-plane --env-file .env --host 127.0.0.1 --port 8330
```

另一个终端检查 `/health`、`/`、`/courses` 返回 200，再打开页面。保持 loopback-only、每日调度关闭、单 worker；不要擅自运行历史每日任务。历史 8130 绑定失败来自 Windows 保留范围 8123–8222，使用空闲端口即可，不要改系统保留规则或防火墙。

当前开发工作树默认数据：`data/control-plane/control-plane.db` 与 `data/control-plane/`。已有旧 Docker 容器 `automated-video-workbench-control-plane-1` 的数据是另一份：

`B:/xiaozhu/.worktrees/automated-video-workbench/全自动视频发布/data/control-plane`

它历史上留有 ANALYZING 任务，不要未经核对重启、删除、迁移，也不要因为有 8130 容器名就认为是当前新代码。外层 `B:/xiaozhu/video-workbench/.env` 也不是当前开发工作树的配置来源。

## 5. Dify 已修复什么、方舟仍卡在哪里

本机 Dify 部署：`B:/Apps/Dify/docker`，Compose project `dify-local`。教程应用：

`http://127.0.0.1:5501/app/ded86843-6055-4ad6-9188-000b9e4eb381/workflow`

已在 9 月 8 日真实完成：

1. `.env` 的 `NEXT_PUBLIC_SOCKET_URL` 从遗漏端口的地址改为 `ws://127.0.0.1:5501`，只重建 web。
2. 主 API 使用持久化签名文件，api_websocket 原先未挂载并产生独立签名；新增 `docker-compose.override.yaml`，只读挂载主 API 现有 `.dify_secret_key` 文件到实时服务。没有换主密钥、放宽 CORS 或关闭认证。只重建 api_websocket。
3. 最终 `workflows/dify/tutorial-analysis.yml` 通过 UI 导入并发布成功；公开 `GET /v1/parameters` 确认 `visual_frames` file-list 及四个文本输入。

本机配置备份：`B:/Apps/Dify/docker/.env.before-socket-20260908`；旧 DSL：工作树 `.validation/tutorial-workflow-before-20260908.yml`。这些可能涉及本机私有配置，不提交、不回显。不要再次按历史文档说“Dify 还没发布”。今天没有重新读回发布参数，后续若有漂移请核实。

真实请求证据：

- `3b91f079-3483-407d-a480-0a655e2a1446`：两张真实绿豆沙素材帧，failed。
- 用户要求继续后的 `88bee11f-9de8-4cdb-9762-a3d9d822d433`：仍 failed。
- 公开运行详情确认：方舟 `429 / SetLimitExceeded`，`doubao-seed-2-0-pro` 达到账号设置的推理上限并暂停。不是已知 Key 错误。失败记录 total_tokens=0 不等于整个项目没有费用。
- 最后一次打开方舟控制台停在未登录弹窗；**今天没有核实登录态或再次调用模型**。

用户已说“没有上限”，并同意继续重跑：可视为愿意承担此次任务模型费用、授权处理限额问题，但并不证明平台设置已改变，也不等于授权不受控无限重试、其他采购或关闭安全认证。通过官方页面检查；本人登录、验证码及平台要求的确认不得绕过。若改动构成新的付费条款或其他敏感动作，按当前代理工具权限处理。

可用本机既有凭据静默读取公开 `/v1/parameters` 与 `/v1/workflows/run/{id}`；不输出 Authorization 或原始错误堆栈中的账号信息。不要反复跑收费探测；确认平台恢复后做一次有界调用，成功才推进完整任务。

## 6. 真实教程、素材、参考和旧交付

- 用户源教程：`B:/xiaozhu/video-workbench/素材/教程`
- 用户源素材：`B:/xiaozhu/video-workbench/素材/素材`
- 既有学习/清单证据：工作树 `.validation/user-courses-20260908/`，包含 `inventory.json`、`representative-materials.json`、教程转写、图像和学习结果；逐项核验文件/来源/完整性再复用。历史完成 27 份教程转写不等于当前课程数据库已经入库并关联好。
- 历史辅助数据：`B:/xiaozhu/.worktrees/automated-video-workbench/全自动视频发布/data/control-plane/user-courses-20260908`，不要跟当前开发库混用。
- 用户参考视频：`B:/wechat/history/xwechat_files/wxid_tep67v6jwyhv22_7374/temp/RWTemp/2026-09/2aafe15a4c2d303c11f9435472729d59/6bac0577c3a36baf0879f81e34bc651e.mp4`。这是临时目录，先检查存在，必要时经安全复制保留，不修改原文件。
- 旧交付目录：`B:/xiaozhu/video-workbench/data/deliveries/2026-09-08/绿豆沙-教程实剪`
- 旧 MP4：该目录的 `绿豆沙-教程实剪.mp4`，本次确认仍存在。目录还有 `先看这里.md`、`教程学习记录.md`、`检测报告.json`、`镜头与教程对应.json`、`剪映草稿位置.json`。草稿真实位置读这个 JSON，不凭空猜测。

旧视频由单任务脚本制作（历史记录 18.87 秒、1080×1920、12 镜头；本次未重测媒体参数）。`.validation/render-greenbean-20260908.py`、`prepare-greenbean-20260908.py`、`deliver-greenbean-20260908.py` 等只是历史辅助证据。**不能重跑这些脚本然后称新版正式服务已验收。** 新版必须从正式课程/任务入口走完，并生成独立 task_id/交付目录。

用户提供网课供学习不等于取得商用素材授权；当前测试可按已知个人学习范围，不伪造 `commercial_authorized`。不抓取他人受登录保护的素材，不破解签名或规避平台风控。成片不自动发到抖音。

## 7. Claude 应按这个顺序继续

1. 读取上述入口和实际 diff；确认路径、分支、未提交文件，保留用户所有改动。
2. 恢复 8330；核查 Dify 参数仍含 visual_frames，核实方舟本人登录及当前模型上限状态。不要让用户重新复制 Key。
3. 检查本地源教程/素材和已学证据，列出绿豆沙实际选用教程、原片、参考片清单及来源；不要把同目录的蛋挞/蓝莓混进去。
4. 使用正式接口/服务入库与创建任务。入口在 `app/main.py`：`POST /api/courses/intake`、`POST /api/courses/{course_id}/process`、`POST /api/course-edit-jobs`；模型在 `schemas/course_knowledge.py`、`models.py`，编排在 `services/course_edit_job_service.py`、`task_service.py`、`pipeline_service.py`。
5. **核对接线缺口**：CourseEditJobCreate 当前仅提供 course_id/title/content_type/commercial/quality_profile/cloud_processing_allowed；底层 service 有更多选材/requirements 参数，参考视频不自动因为磁盘存在而传入任务。检查普通任务参考上传路径和课程关联，若需要补接口则实现+测试，不能通过临时改数据库或特制成片脚本绕开。
6. 使用 production 档和任务级云处理同意；课程规则必须关联真实来源。现有 sidecar 不存在时不能假装视觉学习完成。参考风格可学，示例商品断言不可挪用。
7. 创建新任务、新 MP4、新草稿，保留旧交付。检查完整旁白、词级对齐或明确降级原因、字幕遮挡、镜头重复/越界、横竖裁切、黑场/静音、音量、转场和开头吸引力。与参考片比较，不仅看机械分数。
8. 检查剪映草稿的视频、旁白、BGM、字幕为可编辑独立轨道，新建目录不覆盖旧草稿。实际打开/回放才叫客户端验证；只复制/登记成功只能称“草稿已生成/已导入”。无可用 GUI 时明确留待验证，不作假。
9. 交付新任务页面、完整交付目录、MP4 和实际草稿绝对路径，以及本次云路由、用量和仍未知项。若只是测试片就明确标明；用户未验收不能说达到参考水平。

## 8. 测试与证据要求

历史最终代码全量测试：2026-09-08，404 passed in 161.48s。真实 FFmpeg + 云接口测试替身，**不是实际模型/成片/客户端验收**。今天仅进行了文档、Git、路径、HTTP 和连续性结构审计，没有重跑 404 项，也没有新云调用。

修改代码后从**实际仓库根目录**执行，避免部署测试相对路径失败：

```powershell
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
& .\services\control-plane\.venv\Scripts\python.exe -m pytest services/control-plane/tests -q --maxfail=3
node --check services/control-plane/app/static/workbench.js
git diff --check
```

重点测试：`test_director_plan.py`、`test_dify_visual.py`、`test_visual_evidence.py`、`test_director_cache.py`、`test_narration_alignment.py`、`test_pipeline_alignment.py`、`test_pipeline.py`。报告实际结果，不引用历史数字冒充本轮验证。

## 9. 必须保留的边界

- 不能 reset --hard、清理未跟踪文件、覆盖旧草稿/素材，不能随意操作其他 Docker 项目。
- 不读出/粘贴/输出 `.env`、API Key、AK/SK、Token、验证码、剪贴板或密钥文件；既有程序可正常静默使用配置。
- 本次交接不授权 Git 发布、服务器部署、替代模型、其他采购或自动公开发视频。
- 只改当前任务需要的内容；先验证再报完成。若登录/额度仍阻塞，说明具体错误和唯一需要用户完成的动作，不重复给一大堆泛泛配置清单。
- 历史“本地启动被策略拒绝”“Dify 未发布”已被后续恢复结果取代；今天新增事实是本地 8330 不可达，不能倒退套用旧根因。

## 10. 可直接给 Claude 的接手指令

> 请在 B:/xiaozhu/video-workbench/.worktrees/video-workbench-closure 工作。先完整读取 CLAUDE.md、AGENTS.md、docs/handoffs/2026-09-09-claude-handoff.md 和 docs/progress.md 最新条目，检查未提交代码，勿覆盖或清理。先安全恢复本地服务并核实方舟模型可用性，再使用真实教程、绿豆沙素材和参考视频走新版正式流程，补齐必要接线与测试，生成新 MP4 及独立轨道剪映草稿并验收。不要拿旧单任务脚本的成片充当正式流程结果；我只验收，除本人登录、权限/付费确认等必要动作外不要反复问我。最后报告真实完成项、文件路径、测试/模型证据、费用记录与尚未验证项。
