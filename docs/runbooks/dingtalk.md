# 钉钉 Stream 素材接入

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

## 安全规则

- 仅接受视频、音频、图片、PDF、DOCX、PPTX 和纯文本。
- 下载前检查声明大小，下载后再次检查真实字节数和响应 MIME。
- 以钉钉消息 ID 持久化去重，控制面成功创建任务后才标记消息已处理。
- 钉钉进入的素材默认 `rights_confirmed=false`，必须在审核页人工确认版权。
- Client Secret、Access Token、下载 URL 和文件内容均不写日志。

## 未配置行为

缺少凭据时连接器进程以退出码 2 结束，并输出不含密钥的 `not_configured` 原因；控制面和 ArcReel 可继续独立运行。
