# 本次运行环境恢复与验收入口

**后续更新：本地启动与 Dify 视觉发布两项均已恢复。一次真实请求目前被方舟 SetLimitExceeded 阻止；最新状态见 [真实验证记录](2026-09-08-dify-live-verification.md)。以下未恢复描述仅为历史排查过程。**

## 最新恢复结果

2026-09-08 用户再次要求代理直接启动后，原生启动已执行。SQLite 已备份至 `.validation/control-plane-before-start-20260908-2.db` 并通过 integrity_check。8130 绑定失败的当前原因已查明：Windows TCP 排除范围 8123–8222 包含该端口。没有修改系统保留范围或权限，改用未保留且空闲的 8330 后服务成功运行；`/health`、`/`、`/courses` 均实测 HTTP 200。当前入口为 http://127.0.0.1:8330/ ，每日调度关闭。以下启动受阻说明是上轮历史状态；Dify 发布与真实成片验收仍未完成。

当前不是全部完成：本地代码已改，真实发布/新成片验收受阻。不要拿旧绿豆沙 MP4 当作新版流水线产物。

## 1. Windows 启动（需要用户在自己的终端执行）

本次代理的启动命令被执行环境拒绝，不能换壳绕过。下面是已有 Python 环境的前台运行命令；不要关闭该终端。仅监听本机，不启动历史每日任务，也不打印或要求重填 Key。

```powershell
Set-Location 'B:\xiaozhu\video-workbench\.worktrees\video-workbench-closure'
$env:VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED='false'
$env:VIDEO_WORKBENCH_DIFY_BASE_URL='http://127.0.0.1:5501/v1'
& .\services\control-plane\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/control-plane --env-file .env --host 127.0.0.1 --port 8130
```

启动后检查 http://127.0.0.1:8130/health，再打开 http://127.0.0.1:8130/ 。这使用当前开发目录的 data/control-plane，不迁移旧 Docker 数据；目录中的既有数据库需在修改/迁移前用 SQLite backup 备份。

## 2. Dify 视觉工作流仍需实际发布

- 应用：视频教程拆解，ID ded86843-6055-4ad6-9188-000b9e4eb381。
- 本次备份：.validation/tutorial-workflow-before-20260908.yml；原始下载仍在用户 Downloads。备份不提交 Git。
- 已导入视觉草稿，但编辑器一直显示同步中；点击发布更新未产生发布结果。
- 应在正常浏览器解决实时连接后，导入最终 workflows/dify/tutorial-analysis.yml 并发布；不得直接写 Dify 数据库、扩大权限或关闭安全措施。
- 验收必须读回公开 /v1/parameters 中 visual_frames，检查 LLM vision 绑定 start/visual_frames，再运行一个有云同意的真实任务。
- 不要设置 VIDEO_WORKBENCH_DIFY_TUTORIAL_WORKFLOW_REVISION，直到真实发布版本核验成功；之后每次发布都要更新该值。它不是额外 Key。

## 3. 后续由代理继续的验收，不交给用户逐项手工做

运行环境恢复后，用正式课程/任务入口接入原教程、授权素材和参考片，核对 visual-input-evidence、director-plan、narration-alignment、usage、最终 MP4 和剪映独立轨道。记录真实云错误和调用量；费用限制时停止，不能换模型绕过。至少两种商品的语义、字幕遮挡、听感、风格与客户端回放没验收前，不称整体效果达标。
