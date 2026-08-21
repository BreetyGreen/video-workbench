# Dify 工作流接入

## 作用

- `tutorial-analysis.yml`：把教程、转写和画面描述转成严格的剪辑配方。
- `viral-analysis.yml`：分析带来源的趋势记录，区分公开指标与账号授权指标，并生成三套发布文案。

控制面不会接受自由文本结果。Dify 返回值必须通过 Pydantic 结构校验；无效返回会记录为审核警告并回退本地配方，不会把未经验证的内容写入剪映草稿。

## 导入

1. 在 Dify 工作室选择“导入 DSL 文件”。
2. 分别导入 `workflows/dify/tutorial-analysis.yml` 和 `workflows/dify/viral-analysis.yml`。
3. 安装 Dify Marketplace 的官方 `Volcengine Ark` 模型插件（`langgenius/volcengine`），API Endpoint 填写 `https://ark.cn-beijing.volces.com/api/v3`。
4. 两份 DSL 默认使用效果优先的 `doubao-seed-2-0-pro-260215`；若方舟账号未开通该模型，需在两个 LLM 节点中改为账号实际可用的同档 Pro 模型 ID。
5. 发布每个工作流，并分别复制应用 API Key。生产环境建议为两个工作流配置独立密钥。

当前控制面使用标准工作流接口 `POST /v1/workflows/run`。默认配置字段为：

```text
VIDEO_WORKBENCH_DIFY_BASE_URL=http://host.docker.internal:5501/v1
VIDEO_WORKBENCH_DIFY_TUTORIAL_API_KEY=
VIDEO_WORKBENCH_DIFY_VIRAL_API_KEY=
```

API Key 只写入本地 `.env`，不得提交 Git。

本机 Dify 管理页面为 `http://127.0.0.1:5501`。控制面运行在 Docker 容器中，因此通过 `host.docker.internal` 访问宿主机；不要在控制面 `.env` 中改成 `127.0.0.1`，否则它会指向控制面容器自身。

## 实际处理链

创建任务时可填写 `requirements_text` 与 `tutorial_text`；也可以把 UTF-8 的 `.txt` 教程与视频一同上传。处理任务时控制面会：

1. 把教程、任务要求与类目送入教程拆解工作流。
2. 用返回的目标时长裁切预览和剪映主轨，并把第一条钩子规则写入首屏文字轨。
3. 从本地趋势库取最近的带来源公开记录，送入爆款分析工作流。
4. 把三套结构化标题、正文、话题写入审核页，并把两份结构化分析保存到任务的 `analysis/` 目录。

如果任一工作流未配置或请求失败，该部分会明确显示警告并使用本地基线，不会阻断预览与草稿生成。

## 证据边界

- 公开页面可见的点赞、评论、收藏等标记为 `public`。
- 完播率、转粉率、成交等仅在账号所有者授权导出后标记为 `owner_authorized`。
- 没有来源的数值不得进入分析输入。
- 生成的标题、文案和话题只是候选项，必须在审核页人工确认。

## 未配置状态

未设置 API Key 时，控制面返回：

```json
{"status":"not_configured","reason":"missing_tutorial_and_viral_api_key"}
```

这不会阻止本地上传、FFmpeg 预览和剪映草稿功能。
