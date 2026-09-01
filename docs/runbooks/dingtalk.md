# 钉钉 Stream 课程入库

## 准备

钉钉连接器使用钉钉开放平台团队维护的 Python Stream SDK `dingtalk-stream 0.24.3`。Stream 模式通过长连接接收机器人消息，不需要把本机 Webhook 暴露到公网。

在钉钉开发者后台创建企业内部应用和机器人，启用 Stream 模式，然后只在本地 `.env` 配置：

```text
DINGTALK_CLIENT_ID=
DINGTALK_CLIENT_SECRET=
DINGTALK_ROBOT_CODE=
CONTROL_PLANE_URL=http://127.0.0.1:8130
DINGTALK_MAX_FILE_BYTES=524288000
DINGTALK_DEDUP_DATABASE=data/dingtalk/dedup.db
```

## 课程入库群规则

建议建立一个专用“课程入库群”。老师历史文件由账号本人一次性转发到该群，后续新教程和素材直接发到群里。消息可以带以下标签；不带标签时默认当作素材，版权默认为未知：

- `#教程`：需要转写/OCR 并提炼剪辑规则的课程内容。
- `#案例` 或 `#参考`：只提取节奏、钩子和字幕结构的参考成片。
- `#素材`：允许进入镜头库的源视频、音频或图片。
- `#个人学习`：只允许学习课程规则，不能用于商用成片。
- `#商用授权`：只有确实取得商用许可时才能标记。

## 无凭据端到端模拟

模拟只替代钉钉消息来源，后面的文件落盘、数据库去重和课程处理全部使用正式服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\generate-course-fixture.ps1
& .\services\control-plane\.venv\Scripts\python.exe .\scripts\simulate-dingtalk-course.py --base-url http://127.0.0.1:8130
```

脚本默认只允许回环地址。向已部署服务器提交测试数据必须显式添加 `--allow-remote`，避免误把测试素材发到外部环境。

## 安全规则

- 仅接受视频、音频、图片、PDF、DOCX、PPTX 和纯文本。
- 下载前检查声明大小，下载后再次检查真实字节数和响应 MIME。
- 以钉钉消息 ID 持久化去重，控制面成功创建课程后才标记消息已处理。
- 钉钉进入的附件默认 `rights_status=unknown`；只有明确标记且可追溯的素材才进入商用候选。
- Client Secret、Access Token、下载 URL 和文件内容均不写日志。

## 未配置行为

缺少凭据时连接器进程以退出码 2 结束，并输出不含密钥的 `not_configured` 原因；控制面和 ArcReel 可继续独立运行。
