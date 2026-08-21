# 本地运行手册

## 启动和验收

在 `全自动视频发布` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

验收脚本会创建一条包含横屏与竖屏语音素材、参考视频的版权已确认样例任务，真实运行本地转写、参考结构提取、场景与关键帧分析、多素材智能剪辑、字幕、封面、MP4、质量门禁和剪映 ZIP，并验证审核页；它不会替你批准或发布。

首次快速验收需要下载 Whisper `small` 与 OCR 模型，模型保存在 `data/control-plane/models/`。网络与 CPU 速度会影响首次耗时；不要在下载进行中删除模型目录。正式任务默认使用生产档：云端经同意且可用时选择豆包 ASR，否则选择本地 `large-v3`。可分别通过 `VIDEO_WORKBENCH_WHISPER_PREVIEW_MODEL` 和 `VIDEO_WORKBENCH_WHISPER_QUALITY_MODEL` 指向模型名或容器内 CTranslate2 模型目录。

制作质量档位：

- `production`：逐任务允许云端且火山凭据有效时走豆包 ASR；否则本地 `large-v3`；失败后才降级到预览模型并留下原因。
- `local_privacy`：永不调用云端，固定优先本地 `large-v3`。
- `fast_preview`：使用 `small`，适合快速试剪和验收，不应当作正式成片的默认质量。

火山引擎配置、隐私边界和现场验证方式见 [豆包 ASR 运行手册](runbooks/volcano-bigasr.md)。

启动后的日常入口是 `http://127.0.0.1:8130`。页面可完成素材上传、教程与要求填写、定时设置、立即运行、任务处理和审核跳转；`http://127.0.0.1:1241` 是 ArcReel 项目工作区。

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

`stop.ps1` 不删除数据卷或 `data/`。

## 凭据

`.env` 只保存在本机并被 Git 忽略。修改凭据后重新运行 `start.ps1`。不要把 `.env`、浏览器 Cookie、钉钉 Access Token 或 Dify API Key 复制到日志和工单。

钉钉启用命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -EnableDingTalk
```

## 每日自动化与抖音热点

控制面默认每天北京时间 08:30 执行一次：先通过官方抖音开放平台搜索配置的关键词，再处理所有已接收且含视频素材的任务。可以在 `/docs` 中使用以下接口：

- `GET/PUT /api/automations/daily`：查看或修改执行时间、时区和关键词。
- `POST /api/automations/daily/run`：立即执行一次，并留下运行记录。
- `GET /api/trends`：查看带来源、抓取时间和公开互动指标的趋势证据。
- `POST /api/trends/import`：在官方搜索能力未获批前，人工导入公开趋势数据。

官方接入需要在 `.env` 配置 `VIDEO_WORKBENCH_DOUYIN_CLIENT_KEY`、`VIDEO_WORKBENCH_DOUYIN_CLIENT_SECRET`、`VIDEO_WORKBENCH_DOUYIN_DEVICE_ID`，并申请 `aweme.dy.video_search` 能力。实现依据为[客户端凭证](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/client-token)与[视频搜索](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/douyin-search-capability/aweme-dy-video-search)官方文档；系统不使用 Cookie 抓取。

## 备份与恢复

停止服务后，完整复制以下目录和文件到受控备份位置：

```text
data/arcreel/
data/control-plane/
data/dingtalk/
.env
```

`data/control-plane/models/` 是可复用模型缓存，备份不是恢复任务数据的硬要求，但保留它可以避免重新下载。

恢复时先保持服务停止，把备份复制回相同路径，再运行 `start.ps1`。`.env` 含密钥，备份必须加密并限制访问。

## 升级

1. 先备份 `data/` 与 `.env`。
2. 修改 Compose 中明确固定的镜像版本或 Python 依赖版本。
3. 运行控制面和连接器测试。
4. 运行 `start.ps1` 重建容器。
5. 运行 `verify.ps1` 创建新的验收任务。
6. 人工在目标剪映版本打开新的草稿样例。

不要直接改成 `latest`。

## 排障

查看状态：

```powershell
docker compose --project-name automated-video-workbench --project-directory .\deploy --env-file .\.env -f .\deploy\compose.yml ps
```

查看控制面日志：

```powershell
docker logs --tail 200 automated-video-workbench-control-plane-1
```

查看 ArcReel 日志：

```powershell
docker logs --tail 200 automated-video-workbench-arcreel-1
```

如果剪映草稿无法打开，保留失败 ZIP、`compatibility.json`、剪映版本与错误截图；不要把“ZIP 结构测试通过”等同于“目标版本已打开验证”。

如果任务停在 `reviewing` 但无法批准，先在审核页查看“质量门禁”，再检查任务目录中的 `quality-report.json`。`fail` 且 `blocking=true` 的项目必须修复；`warn` 允许人工复核后继续。转写降级原因会同时写入交付清单的 `model_routes`。

## 导入本机剪映草稿箱

先安装并打开一次剪映，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\detect-jianying.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\import-jianying-draft.ps1 -TaskId <任务 UUID>
```

导入脚本会验证任务 UUID、ZIP 顶层目录、`draft_info.json` 和路径穿越风险；目标目录已存在时停止，不覆盖原工程。若自动检测不到草稿根目录，可显式传入 `-DraftRoot`。脚本完成只证明文件已复制，仍需在目标剪映版本人工打开确认。
