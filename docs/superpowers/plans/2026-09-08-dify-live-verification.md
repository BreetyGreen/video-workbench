# Dify 视觉工作流真实验证

## 已确认

- 本地应用 http://127.0.0.1:8330/ 已恢复；本轮修复的是 Dify，不是重新生成旧成片。
- Dify 前端 NEXT_PUBLIC_SOCKET_URL 原为 ws://localhost，遗漏实际 5501 端口；修正为 ws://127.0.0.1:5501，仅重建 web。
- 连接到服务端后发现 InvalidSignatureError。API 使用持久化 storage/.dify_secret_key，api_websocket 没有持久化挂载，生成了独立密钥。新增本机 docker-compose.override.yaml，只读挂载 API 现有密钥文件到 api_websocket；只重建该服务，未生成或替换主密钥、关闭认证、扩大 CORS 或触碰其他项目。
- 两个容器的密钥文件摘要比较一致（不输出摘要或密钥）。实时同步提示消失，编辑器恢复可操作。
- 原 DSL 备份保留。最终 workflows/dify/tutorial-analysis.yml 通过 UI 重新导入并发布；界面显示操作成功、几秒前已发布。
- 公开 GET /v1/parameters 实际返回 visual_frames file-list 及四个文本变量，发布生效。

## 一次真实请求结果

- 使用用户提供绿豆沙素材的两张既有抽样帧，调用正式 DifyClient.analyze_tutorial，未替换模型，没有重试。
- workflow_run_id: 3b91f079-3483-407d-a480-0a655e2a1446。
- Dify failed，耗时 4.285562 秒，报告 total_tokens=0。不能据此认定全部系统费用为零。
- 通过公开工作流运行详情读回根因：火山方舟 HTTP 429 / SetLimitExceeded，doubao-seed-2-0-pro 达到账户设置的推理上限并暂停。
- 这是当前实际调用证据，不是沿用历史限额记录。未修改 Safe Experience Mode、提高限额或切换模型规避。
- 本轮未生成新版 MP4；真实课程理解、两种商品的完整剪辑与参考效果、剪映客户端回放仍未验收。独立事实验证及自动风格返工仍 Open。

## 需要用户完成的唯一当前外部动作

在火山方舟的模型开通/管理页面检查 doubao-seed-2-0-pro 的安全体验模式和用量上限，按自己可接受的费用预算决定是否恢复。不要重建或发送 Key。额度恢复后由代理继续正式课程/任务流程验收，不让用户逐项手工测试。

本机配置恢复文件：B:/Apps/Dify/docker/.env.before-socket-20260908；新增 override 不包含密钥值。它们属于本机 Dify 部署，不属于项目仓库发布物。
