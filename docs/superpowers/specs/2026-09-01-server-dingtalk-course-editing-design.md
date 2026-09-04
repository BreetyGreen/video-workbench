# 服务器化钉钉课程自动剪辑系统设计

## 1. 目标

把现有本地优先的视频工作台改造成面向普通用户的服务器产品。用户日常只使用钉钉和剪映，不需要安装 Codex，也不需要在自己的电脑上运行完整 AI 服务。

主链固定为：

```text
钉钉课程入库群 → 服务器接收教程/案例/素材 → 教程理解与素材索引
→ 用户提交剪辑任务 → 自动匹配课程方法和授权素材 → 渲染与质量门禁
→ 生成 MP4 和剪映草稿包 → 本机同步助手导入剪映并启动客户端
```

## 2. 范围与交付阶段

系统按四个可独立验收的子项目交付，但共享同一数据模型和接口：

1. **课程入库**：钉钉群附件接收、模拟入库、文件去重、角色分类与授权登记。
2. **课程理解与素材知识库**：教程转写、章节切分、剪辑规则抽取、素材镜头切分、标签与检索。
3. **自动剪辑任务**：课程方法选择、素材匹配、时间线、旁白字幕、渲染和机器质量门禁。
4. **服务器与剪映交付**：生产部署、设备配对、草稿包队列、跨平台同步助手和剪映导入。

第一条端到端验收链先使用模拟钉钉群事件，不等待企业应用审批。模拟范围只限于钉钉事件入口；文件入库、课程理解、素材匹配、剪辑、质检和剪映交付全部执行真实代码。真实钉钉凭据就绪后仅替换接入适配器，不改动后续课程处理接口。

## 3. 用户体验

### 3.1 一次性准备

- Windows 钉钉客户端安装到 `B:\Apps\DingTalk`。
- 课程缓存、模拟群附件和本机同步数据放到 `B:\VideoWorkbench`。
- 用户在钉钉中登录自己的账号。
- 管理员创建企业内部应用、课程入库机器人和专用课程入库群，并完成组织授权。
- 用户电脑安装轻量的 VideoWorkbench Sync；它只保存设备令牌，不保存 ASR、TTS、Dify 或素材平台密钥。

### 3.2 课程入库

用户把课程历史文件一次性转发到专用群。以后新增课程文件直接发到同一群。系统支持以下可选标签，但不强制填写：

- `#教程`：讲解如何剪辑的视频、PDF、DOCX、PPTX 或文本。
- `#案例`：课程中的示例成片、参考片。
- `#素材`：课程附带且允许使用的视频、音频、图片。
- `#任务`：需要生成的新视频要求。

没有标签时，服务器结合消息文本、文件名、MIME、视频转写、OCR 和画面特征自动分类。低置信度文件进入“待归类”，不会静默混入成片。

### 3.3 自动生成

用户在钉钉群发送 `#任务` 消息，或从服务器工作台创建任务。系统自动选择最相关课程规则和可用素材，生成预览、质量报告、成片和剪映草稿包。人工审核页面不再阻断主链；只有机器质量门禁失败或授权状态不足时暂停。

### 3.4 剪映交付

服务器不能直接写用户电脑上的剪映目录。VideoWorkbench Sync 通过设备令牌轮询交付队列，下载草稿包，校验 SHA-256、ZIP 路径和媒体完整性，只创建新草稿，不覆盖已有工程，然后尝试启动剪映/CapCut。服务器端与本机助手都不依赖 Codex。

## 4. 系统架构

### 4.1 服务器服务

- **Web/API**：FastAPI，负责用户、课程、素材、任务、设备和交付接口。
- **Worker**：执行长时间 ASR、OCR、镜头切分、嵌入、渲染和质量门禁；Web 进程不直接承担长任务。
- **Queue**：Redis，提供可恢复任务队列和幂等锁。
- **Database**：PostgreSQL，存储课程、素材、任务、规则、设备与审计记录。
- **Object storage**：S3 兼容对象存储；单机验收使用 MinIO，生产可替换火山 TOS。
- **Reverse proxy**：Caddy，提供 HTTPS、上传大小限制和基础安全头。
- **DingTalk connector**：Stream 机器人接收新附件；后续可增加用户 OAuth 历史迁移器，但不把它作为主链依赖。

### 4.2 本机服务

- **钉钉客户端**：用户登录、转发文件和提交任务，不承载后台处理。
- **VideoWorkbench Sync**：仅负责设备配对、下载、验证、导入草稿和启动剪映。
- **剪映/CapCut**：最终人工微调和发布；服务器不尝试在 Linux 上运行剪映。

## 5. 核心数据模型

### 5.1 Course

- `id`, `name`, `source_type`, `source_conversation_id`
- `owner_user_id`, `created_at`, `status`
- `default_usage_mode`: `personal_practice` 或 `commercial_publish`

### 5.2 CourseAsset

- `id`, `course_id`, `role`: `tutorial`, `reference`, `material`, `unknown`
- `source_message_id`, `source_filename`, `source_sha256`
- `object_key`, `mime_type`, `size_bytes`, `duration_seconds`
- `rights_status`: `unknown`, `personal_learning`, `commercial_authorized`
- `classification_confidence`, `processing_status`, `failure_reason`

### 5.3 EditingRecipe

- `id`, `course_id`, `source_asset_id`, `version`
- `content_category`, `hook_rules`, `pacing_rules`, `caption_rules`
- `audio_rules`, `transition_rules`, `shot_selection_rules`, `quality_thresholds`
- `source_citations`: 每条规则对应教程视频时间码、页码或文本片段摘要
- `confidence`, `created_at`

### 5.4 MaterialShot

- `id`, `asset_id`, `start_seconds`, `end_seconds`
- `people_tags`, `product_tags`, `scene_tags`, `action_tags`
- `ocr_text`, `transcript_text`, `embedding`, `perceptual_hash`
- `quality_score`, `rights_status`

### 5.5 EditJob

- `id`, `user_id`, `course_id`, `request_text`, `target_seconds`
- `usage_mode`, `status`, `selected_recipe_version`
- `timeline_object_key`, `preview_object_key`, `draft_object_key`
- `quality_status`, `failure_reason`, `created_at`, `completed_at`

### 5.6 DeliveryDevice / DeliveryPackage

- 设备使用一次性配对码换取可吊销的随机令牌。
- 令牌仅能访问所属用户尚未领取的交付包。
- 每个交付包记录对象键、SHA-256、目标平台、领取状态、导入结果和客户端版本。

## 6. 处理流程

### 6.1 入库

1. 钉钉 Stream 回调转换成统一 `IncomingCourseEvent`。
2. 以 `source_message_id + file_sha256` 幂等去重。
3. 下载到隔离临时区，校验声明大小、实际大小、MIME 和允许的扩展名。
4. 上传对象存储并创建 `CourseAsset`。
5. 自动分类角色；低于置信阈值时进入待归类。
6. 教程、案例和素材分别投递到对应 Worker 队列。

模拟适配器从 `fixtures/course-inbox` 读取与真实事件同结构的清单和文件，确保无需钉钉凭据也能验收后续全链。

### 6.2 教程理解

1. 视频/音频执行 ASR，文档提取正文，所有类型执行必要 OCR。
2. 按主题和时间连续性生成章节。
3. 提取可执行的剪辑规则，而不是只生成摘要。
4. 每条规则保存来源时间码或页码，无法追溯的规则不进入正式配方。
5. 案例成片补充节奏、镜头长度、字幕位置、音频结构和转场统计。
6. 多份教程产生带版本的配方，后续任务按语义相关性和置信度选择。

### 6.3 素材理解与检索

1. 素材先做镜头级切分。
2. 对镜头执行人物、商品、场景、动作、OCR、转写和技术质量分析。
3. 生成文本/视觉嵌入和感知哈希。
4. 语义检索用于按任务要求找镜头；感知哈希用于近重复检测。
5. `commercial_publish` 任务只能选择 `commercial_authorized` 素材；`personal_practice` 可使用 `personal_learning`，但不得自动发布。

### 6.4 自动剪辑

1. 根据任务文本选择课程和配方。
2. 将配方约束转换成时间线目标。
3. 检索素材并做多样性、连续性、重复率和授权过滤。
4. 生成旁白、字幕、时间线、预览和剪映草稿。
5. 执行黑场、长静音、画布、时长、字幕覆盖、旁白覆盖、媒体可播放和草稿路径检查。
6. 质量通过后自动创建交付包；失败任务保留诊断证据，不交付半成品。

## 7. 接口边界

- `POST /api/intake/dingtalk/events`：仅连接器服务调用，使用服务身份认证。
- `POST /api/intake/simulate`：仅开发/验收配置启用，生产配置不存在该路由。
- `GET /api/courses`、`GET /api/courses/{id}`：课程与处理状态。
- `POST /api/edit-jobs`：创建任务。
- `GET /api/edit-jobs/{id}`：状态与质量结果。
- `POST /api/devices/pair`：一次性设备配对。
- `GET /api/deliveries/pending`：同步助手拉取待交付包。
- `POST /api/deliveries/{id}/result`：回报校验、导入和启动结果。

上传、下载和交付接口都采用限时签名 URL；API 不把对象存储主密钥下发给客户端。

## 8. 错误处理与可恢复性

- 所有阶段使用幂等键，重复钉钉回调不会重复创建课程资产。
- 下载中断保留可重试状态，临时文件在校验完成前不进入素材库。
- Worker 任务记录阶段、次数和最后错误；达到上限后进入人工可见失败队列。
- 配方抽取失败不把普通摘要伪装成可执行规则。
- 素材不足时返回明确缺口，不自动抓取无授权视频。
- 同步助手校验失败时不改剪映目录；导入采用同卷暂存加原子重命名。
- 所有导入只创建新草稿，重复领取按包哈希幂等。

## 9. 安全与版权

- 购买网课不自动等于获得公开发布课程素材的权利。
- 教程视频用于学习剪辑方法，不直接出现在生成视频中。
- 素材必须记录权利状态和来源；商用任务只使用明确授权素材。
- 钉钉 Client Secret、用户 OAuth、云模型密钥和设备令牌加密保存，不写日志。
- 服务器按用户隔离课程、素材和交付包；下载 URL 短时有效。
- 生产环境关闭模拟入口，启用 HTTPS、备份、上传限制和审计日志。

## 10. 部署默认值

- 起步服务器：4 vCPU、8 GB 内存、160 GB SSD；模型推理优先调用云服务，FFmpeg 在服务器执行。
- 单机 Docker Compose 包含 `api`、`worker`、`redis`、`postgres`、`minio`、`dingtalk-connector`、`caddy`。
- 大文件和成片放对象存储，不放数据库。
- 数据库每日备份，对象存储启用版本或生命周期策略。
- 域名与 HTTPS 就绪前，只允许 SSH 隧道管理，不公开裸端口。

## 11. 验收标准

1. 钉钉安装器把客户端主程序安装到 B 盘目标目录，C 盘只允许操作系统不可避免的少量用户配置。
2. 模拟课程群事件包含至少一份教程视频、一个案例和三个素材视频，入库后角色分类正确且去重有效。
3. 教程生成至少一版含来源时间码的 `EditingRecipe`。
4. 素材完成镜头切分、标签、语义检索和相似检测。
5. 一个 `#任务` 从入库到 9:16 成片和剪映草稿全程无需 Codex。
6. 质量门禁零阻断后自动创建交付包。
7. 同步助手在 Windows 验证下载、校验、导入、启动剪映和结果回报。
8. 服务器重启后课程、素材、任务和交付状态不丢失。
9. 无钉钉真实凭据时模拟链仍通过；有凭据后真实连接器仅替换事件来源。
10. 生产接口不暴露秘密、模拟路由或服务器文件系统绝对路径。

## 12. 用户必须完成的外部动作

- 在钉钉客户端登录个人账号。
- 创建或加入专用课程入库群，并把历史课程文件转发进去。
- 企业管理员创建应用、机器人并授权文件消息能力。
- 购买服务器并提供 SSH 登录目标；配置域名、HTTPS 和必要备案。
- 在目标电脑安装并至少打开一次剪映/CapCut，确认系统文件访问权限。
- 对课程素材的个人练习或商业使用范围作出真实选择。
