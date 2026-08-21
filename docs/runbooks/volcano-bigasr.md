# 豆包 ASR 运行手册

## 用途和路由

控制面接入火山引擎豆包录音文件识别极速版，用于生产档的高质量中文语音转写。系统不会把它当作唯一依赖：

1. `production` 且任务明确勾选云端处理同意，同时凭据已配置时，优先调用豆包 ASR。
2. 未同意、未配置或云端调用失败时，转到本地 Whisper `large-v3`。
3. 本地高质量模型仍失败时才降级到 `small`，并在 `manifest.json` 的 `model_routes[].fallback_reason` 留下原因。
4. `local_privacy` 永远不调用云端；`fast_preview` 直接使用预览模型。

参考视频遵循同一任务级同意。上传的参考视频只用于结构分析，不会进入最终时间线。

## 配置

新控制台鉴权优先使用 API Key：

```dotenv
VIDEO_WORKBENCH_VOLCANO_ASR_API_KEY=
VIDEO_WORKBENCH_VOLCANO_ASR_RESOURCE_ID=volc.bigasr.auc_turbo
VIDEO_WORKBENCH_VOLCANO_ASR_ENDPOINT=https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash
```

如果账号仍使用旧版鉴权，可以改填：

```dotenv
VIDEO_WORKBENCH_VOLCANO_ASR_APP_KEY=
VIDEO_WORKBENCH_VOLCANO_ASR_ACCESS_KEY=
```

本地模型建议：

```dotenv
VIDEO_WORKBENCH_WHISPER_PREVIEW_MODEL=small
VIDEO_WORKBENCH_WHISPER_QUALITY_MODEL=large-v3
VIDEO_WORKBENCH_WHISPER_DEVICE=cpu
VIDEO_WORKBENCH_WHISPER_COMPUTE_TYPE=int8
```

有受支持的 NVIDIA GPU 时可把 device 改为 `cuda`，并根据显存选择合适的计算类型。修改 `.env` 后重新运行 `scripts/start.ps1`。

## 验证

1. 打开 `http://127.0.0.1:8130`，确认“豆包 ASR”状态为已配置。
2. 创建任务，选择“生产高质量”，勾选允许该任务把音频发送到云端。
3. 处理完成后打开审核页，下载交付清单。
4. 检查 `model_routes`：成功时 provider 为 `volcano_bigasr`；降级时 provider/model 和 `fallback_reason` 会说明实际执行路径。
5. 不勾选同意再创建一条任务，确认 provider 为本地 Whisper，以验证同意开关有效。

自动化测试会模拟官方响应验证毫秒级分段与降级行为；没有真实账号密钥时，只能确认适配器和本地降级链，不能宣称云端现场调用已验证。

## 数据与合规

- 云端请求只发送从任务媒体抽取的单声道 16 kHz WAV，不发送视频画面。
- 同意按任务保存，默认关闭；旧任务也不会自动获得云端权限。
- 密钥只放在未跟踪的 `.env`，不要写入任务要求、日志或截图。
- 公开发布仍然停在人工审核边界，不使用抖音 Cookie 自动发布。
