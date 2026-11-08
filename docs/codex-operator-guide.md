# Codex 启动与能力操作指南

## 2026-09-11 配音改用 CosyVoice v2（Claude）

- 用户反馈定版后语气仍不自然，并问能否改用 HeyGen 开源剪辑器（HyperFrames）。评估：HyperFrames 是 HTML 合成/渲染层，可提供动态字幕、推近、转场，但不改变配音语气；语气取决于 TTS。因此新增 `DashScopeCosyVoiceClient`（`dashscope` SDK WebSocket，`cosyvoice-v2`，默认 `longxiaochun_v2`，`speech_rate` 可调），`VIDEO_WORKBENCH_DASHSCOPE_TTS_ENGINE=cosyvoice|qwen` 选择引擎；5 个龙系音色样音已发用户。`.env` 已切到 cosyvoice/longxiaochun_v2/1.05。HyperFrames 接入留作后续可选的画面层升级（时间线→HTML 合成→`npx hyperframes render`），未实施。

## 2026-09-11 旁白禁词守卫与一句一字幕（Claude）

- 定版后的作业旁白出现“整箱囤货更划算”（价格暗示，需求里已禁止但模型未遵守）。新增 `VIDEO_WORKBENCH_PROHIBITED_NARRATION_TERMS`（默认含划算/便宜/性价比/优惠/折扣/无糖/无添加/降火/清热/功效等），`director_service.narration_violations()` 检出后流水线带违规明细重新请求导演一次；仍违规则抛 `director_narration_prohibited_terms` 回退本地预览；两次调用的 token 合并记账，`visual-input-evidence.json.claim_guard` 记首稿与重试的违规项。
- 字幕分组改为一句一条：`CaptionService.segment_text(sentence_per_chunk=True)` 用于逐词对齐与估算字幕，分镜旁白一段一句即一段一字幕（与参考片一致）；屏幕显示去掉句尾标点（`display_text`），剪映文本轨同样；按字号换行时不再把孤立标点拆到下一行（78 号时曾出现“。”独占一行）。

## 2026-09-11 音色与字幕样式可配置（Claude）

- 2026-09-14 用户反馈字幕“太素、没有爆炸感”。新增 `caption_emphasis_service.emphasis_terms(text, product_terms)`（数字+单位 > 商品名 > 感官词，每句最多 2 个、感官词最多 1 个，只选原文子串），`AudioRoutingService.decide(..., product_terms=)` 由流水线传 `product_terms_from_title(task.title)`，容错对齐后经 `inherit_caption_styles` 保留。`CaptionService` 新参数 `highlight_color/shadow/pop_in`：关键词 `{\\c&HBBGGRR&\\fs 1.2×}`（显式恢复白色与字号，不用 `\\r` 以免打断弹入缩放），每条 Dialogue 前缀 `\\fad+\\fscx118→100 (110 ms)` 弹入，片头 `\\fscx135→100` 并加 `TitleGlow` 发光层（Layer 0 blur16、Layer 1 正文），Title MarginV 560。剪映：`_RichTextSegment.export_material` 把 styles 拆成逐段 range（高亮段换 fill 颜色），`TextSegment.emphasis_ranges/highlight_color/intro`，字幕 `TextIntro.弹入`、片头 `放大`（250 ms），描边 48、阴影加深；`edit_plan_from_timeline(timeline, root, highlight_color=, pop_in=)`。默认字号 90/描边 6/片头 150/阴影 4，`.env` 同步。回归：test_caption_service（花字/发光）、test_caption_emphasis_service、test_jianying（range 与动画）、test_audio_routing。
- 用户反馈 Cherry 音色没激情、字幕太小字体不好看，委托拍板。做了 8 段同文案样音（qwen3-tts-flash 4 个预置音色、qwen3-tts-instruct-flash 带“热情带货口播”指令 2 段、qwen-voice-design 按描述定制 2 个音色，定制音色 id 记在 `.validation/voice-samples/designed-voices.json`）和 5 种字幕样式截图。选定：`VIDEO_WORKBENCH_DASHSCOPE_TTS_MODEL=qwen3-tts-instruct-flash`、`_TTS_VOICE=Serena`、`_TTS_INSTRUCTIONS=热情有感染力的带货口播…`（指令只在 instruct 模型上发送）；字幕 `VIDEO_WORKBENCH_CAPTION_FONT_NAME=Microsoft YaHei`、`_FONT_SIZE=78`、`_OUTLINE=5`、`_TITLE_FONT_SIZE=118`。`CaptionService` 改为实例化并按字号自动换行（1080 画布、左右 74 边距 → 每行字数 = 932 // 字号），剪映文本轨字号 8→10。`resolve_voice` 接受 `qwen-tts-vd-*` / `qwen-tts-vc-*` 定制音色 id。

## 2026-09-10 字幕逐词对齐容错（Claude）

- 第 6 次作业旁白全为汉字仍 `narration_text_mismatch`：ASR 把品牌“果知纯”听成“果汁纯”、“绵细密腻”听成“棉细腻腻”，并把“两百四十五克/十二个月”反规整成“245克/12个月”。`narration_alignment_service` 现在在精确匹配失败后做一次容错匹配：旁白侧中文数字先转阿拉伯数字（自带 `_chinese_numeral_to_int`），再用 `SequenceMatcher` 对比，只有相似度 ≥ 0.85、长度漂移 ≤ 10%、首尾都对齐时才接受，并把旁白字符映射回真实 ASR 词时间；缺句/多句仍判 `unavailable`。状态仍为 `word_aligned`，reason 记 `tolerant_match:ratio=…`，字幕时间全部来自真实词时间戳，不插值。回放第 6 次作业的真实转写：ratio 0.93，11 条字幕全部拿到真实时间。

## 2026-09-10 学习规则精选摘要（Claude）

- 完整视频学习后一门课有上千条规则（课程 v3：1340 条）。课程作业超过 40 条规则时，`course_edit_job_service` 不再把规则原样拼进 `tutorial_text`，改用 `course_recipe_service.rule_digest()`：按类别分组、规范化前缀去重、每类固定名额（开头 18、结构 24、节奏 18、字幕 12、声音 12、结尾 10、禁忌 14、特写 10、对比 8）、每条附课时 id 前缀与秒级时间码、总长上限 12000 字并标注截断；未入选规则仍在课程库并继续供本地配方使用。40 条以内保持旧格式。
- 课程 v3 首次入库失败原因：同一课时里模型规则与其父段落时间段完全相同，触发 `tutorial_segments` 唯一约束；已加 1 毫秒去重，并在 `_segments` 复用本资产的 `.tutorial-analysis.json` 侧车（material_id 一致且含转写才复用），重跑不再重复转写。

## 2026-09-10 语音改走阿里百炼 + 渲染死锁修复（Claude）

- 用户火山引擎欠费，识别与配音改接百炼：`adapters/dashscope_speech.py` 提供 `DashScopeParaformerTranscriber`（ffmpeg 抽 16k 单声道 MP3 → `GET /uploads?action=getPolicy` 取临时 OSS 凭证 → 表单上传 → `POST /services/audio/asr/transcription`（`X-DashScope-Async`、`X-DashScope-OssResourceResolve`）→ 轮询 `/tasks/{id}` → 下载结果，句子+词级时间戳，provider `dashscope_paraformer`）和 `DashScopeTTSClient`（`qwen3-tts-flash`，默认音色 Cherry，火山音色 id 一律回落到默认音色；下载 WAV 转 MP3）。配置 `VIDEO_WORKBENCH_DASHSCOPE_API_KEY/_BASE_URL`（原生 DashScope 端点）与 `VIDEO_WORKBENCH_SPEECH_PROVIDER=auto|volcano|dashscope`；`Settings.dashscope_speech_selected` 决定 `MediaAnalysisService` 的云识别器与 `build_tts_client()`。用量账本按 `CLOUD_ASR_PROVIDERS` 与 `tts.provider_name` 记 provider（volcengine/dashscope）。语音配置页/音色目录仍列火山预设，尚未改成百炼音色列表（Open）。
- 渲染死锁根因：`_build_filter` 里 `[program]` 同时喂给 `sidechaincompress` 和最终 `amix`，同一标签被消费两次，输入超过 FFmpeg 内部缓冲后死锁（第三、四次作业分别卡 100 分钟和 14 分钟，内存 1.6–1.9 GB）。已改为 `asplit=2[program_mix][sidechain]`，并保留有限 `-stream_loop N -t` 与 `render_timeout_seconds`（默认 1800 秒）超时保护；新增图结构测试（任何中间标签只能消费一次）。真实 32 秒时间线离线渲染 57 秒完成。
- 启动时 `reset_interrupted_course_processing()` 把上次进程中断遗留的 `processing` 课程/运行标记为 `failed(interrupted_by_restart)`，避免后台学习永远无法重触发（409）。

## 2026-09-10 分镜修复与旁白优先节奏（Claude）

- 真实模型回复暴露的三种偏差已按“机械修正、不编造”兜住：`director_plan` 裸列表/只返回分镜对象（适配器 `normalize_recipe_payload`，派生配方字段并写 `EditRecipe.notes`）、purpose 别名与首尾角色（`spec→feature`、`cta→closing` 等）、素材 ID 写成文件名或镜头组名（`repair_director_plan`：别名/唯一前缀映射、越界裁剪、重叠丢弃，少于 2 段则失败回退）。修正明细写入 `visual-input-evidence.json.plan_repairs`、`EditRecipe.notes` 和 warnings；导演失败落盘 `analysis/director-error.json`。用户轮追加“输出格式提醒”。
- 旁白优先（教程 R01）：有分镜计划且 TTS 自然时长超过分镜总长时，`TimelinePlanner.plan(stretch_to_seconds=...)` 按比例延长每段结尾（不越过素材末尾、不撞同素材后续段），随后 `_fit_voiceover` 只需极小变速；素材不够长时才由旁白加速吸收余量，说明写入 `timeline.warnings` 与 evidence。此前第三次作业曾把 18.7 秒旁白压成 12 秒（1.55 倍速），即由此修正。

## 2026-09-10 教程视频完整学习（Claude）

- 新增 `services/tutorial_video_study_service.py` + `schemas/tutorial_study.py`：教程视频按 `tutorial_study_chunk_seconds`（默认 120 秒）切段，转码为 ≤9 MB 的小 MP4（长边 640→480→360 逐级降级），以 base64 `video_url` + 该段转写发给导演端点（`complete_json`，`fps` 默认 0.5），返回 `segments[{start,end,type,summary,teacher_actions,rules[{category,instruction,evidence_quote,start,end}]}]` 与 `uncertain`。逐段结果落盘 `analysis/tutorial-study/<asset>/chunk-XXXX.json`，重跑只补失败段；聚合为 `<asset>.lesson-study.json`（含 sha256、用量、失败段、uncertain）。
- `TutorialUnderstandingService(study=...)`：视频教程在转写后、且导演端点可用、任务允许云处理时走视频学习；模型的规则直接成为 `EditingRule`（category 只接受 `ALLOWED_COURSE_RULES`，否则按关键词），讲解/软件操作/成片示例段落作为 `TutorialSegment` 保存并带 `action:` 线索；学习失败写 `study-error.json` 并回落本地关键词分类，不伪造。课程证据现在也复制 `tutorial-lesson-study.json`。
- `POST /api/courses/{id}/process` 支持 `{"background": true}`：立即返回 202，学习在响应后运行，轮询 `GET /api/courses/{id}` 的 `status`（processing/processed/failed）；同课程处理中再次触发返回 409。
- 实测探测（课 8《剪辑气口》300–420 秒）：qwen3-vl-plus、fps 0.5，输入 7.8k token（视频 6.6k）、输出 2.9k、49 秒，返回 14 段/13 条带原话规则并标注 3 处 uncertain。240 分钟教程估算约 130 万 token。
- 教程原件 37 GB、单文件最大 3.3 GB，超过课程入库 500 MiB 上限；正式入库使用 `transcode_tutorials.py` 生成的 480p/15fps/单声道学习副本（原件不动，manifest 记录原件路径与已知 sha256）。

## 2026-09-10 导演模型改走 OpenAI 兼容端点（Claude）

- 新增 `app/adapters/openai_compatible_director.py`：与 `DifyClient.analyze_tutorial` 同接口（同样的输入字段、最多 8 张已解码 JPEG/PNG、同样的 `EditRecipe` 输出与 `last_usage`），把分镜/旁白请求发到任意 OpenAI 兼容 `chat/completions`（当前用阿里云百炼 compatible-mode 的 `qwen3-vl-plus`）。系统提示词以代码常量为准，测试强制它与 `workflows/dify/tutorial-analysis.yml` 一致。
- 配置：`VIDEO_WORKBENCH_DIRECTOR_BASE_URL` / `_API_KEY` / `_MODEL`（可选 `_TIMEOUT_SECONDS`、`_MAX_OUTPUT_TOKENS`、`_DISABLE_THINKING`）。三项齐全时正式流水线优先用它，否则回落到 Dify；都没有仍是本地预览。用量记为 provider `openai_compatible` / service `chat`，metadata 带模型名。
- 分镜缓存对该路径自动启用：版本号 = `openai_compatible:<model>:<提示词摘要>`，提示词或模型一变即失效；Dify 路径仍要求人工填写已发布版本。
- `tests/conftest.py` 现在把 `VIDEO_WORKBENCH_DIRECTOR_*` 置空，避免开发者本机 `.env` 的真实凭据泄入单元测试；需要导演客户端的测试必须显式传参。
- 方舟 `doubao-seed-2-0-pro` 的 SetLimitExceeded 不再是卡点；Dify 工作流保留为备用路径，未删除。

## 2026-09-09 课程作业接线补齐（Claude）

- `POST /api/course-edit-jobs` 新增可选字段：`material_ids`（仅限该课程、已通过权利检查的视频素材 ID，1–200 个）、`requirements_text`（≤5000 字，商品事实与禁写项写在这里）、`reference_asset_id`（该课程 `reference` 角色的视频资产）。参考片不会因为磁盘或课程里存在就自动进入任务；只有显式指定才复制到任务目录并写入 `production_settings.reference_*`，且永远不进入可剪素材列表。非本课程、非 `reference` 角色或非视频一律 `422 selected_reference_unavailable`。
- `POST /api/courses/{course_id}/process` 接受可选 JSON `{"quality_profile", "cloud_processing_allowed"}`；不传时与旧行为一致（production、不云处理）。这是课程每日计划已有的能力，现在普通 API 也能指定。
- 教程工作流的 `frame_descriptions` 新增 `material_names`（素材 ID→用户文件名，≤80 字，≤40 个素材时才附带）和说明其只是镜头提示的 `material_name_policy`；仍不发送本地路径。
- 参考片对标后补的成片表现层（同日第二批）：`CaptionCue.style` 新增 `title`；任务标题为 12 字以内的商品名时，正式流水线在最终字幕前插入 0–1.4 秒居中大字片头（ASS `Title` 样式，剪映文本轨 size 15），`director-plan.json` 记录 `title_card`。商品/教程类旁白字幕全部放上方安全区（原来只有首句）。旁白链路加 `acompressor`（-18 dB、2.5:1）再进 loudnorm；`AudioMixPlan.bgm_gain_db` 默认 -15。课程作业现在把 `material` 角色的音频资产一并复制进任务作为可编辑音乐床，但至少要有一个视频素材，否则仍报 `*_material_not_authorized`；课程每日计划的 `material_ids` 校验未改（仍只接受视频）。
- 真实运行边界：2026-09-09 本机 8330 已重启并载入以上代码；一次最小 Dify 探测（run `38e09121-fb1d-46d0-844c-e16b2a553454`）仍返回方舟 429/SetLimitExceeded，doubao-seed-2-0-pro 处于暂停，所以正式绿豆沙作业未创建。当前状态与唯一外部动作见 `docs/progress.md` 最新条目。

## 2026-09-08 统一分镜首批改造

### 后续闭环实现与运行阻碍（以本段为最新状态）

- 最新运行验证见 `docs/superpowers/plans/2026-09-08-dify-live-verification.md`：服务已运行于 8330；Dify WebSocket 端口和持久化签名文件已修复，最终视觉工作流已发布，公开参数确认 visual_frames。真实两帧请求返回方舟 429/SetLimitExceeded，停止重试并等待用户决定恢复额度。以下“无法启动/发布”是已解除的历史卡点，不能继续让用户按旧指引操作；真实成片/效果和客户端验收仍未完成。

- 正式管线在最终配音变速结束后调用 RoutedTranscriber 一次；遵守 production/fast_preview 与 cloud_processing_allowed。完整旁白规范化文本与词序列匹配、真实时间有序且不越界才采用 word_aligned；否则保留 character_weighted_not_word_verified 并写原因。analysis/narration-transcript.json 与 narration-alignment.json 留证；真实 BigASR 秒数计入任务 usage，purpose=narration_alignment。同一最终时间线用于 MP4 和剪映字幕轨。
- 图像总预算 8：最多 2 reference_not_editable、2 tutorial_not_editable，剩余 editable_material。教程来自课程配方关联的本机 sidecar（最多 2 个视频教程、4 MiB/分析、数据根边界与素材 ID 校验）；不是全课程视觉覆盖。参考和教程不进入可剪素材验证目录。
- VIDEO_WORKBENCH_DIFY_TUTORIAL_WORKFLOW_REVISION 默认空，禁用缓存。只有读回真实发布版本后才设置，后续发布必须更新；不能把仓库文件哈希当成尚未发布的版本。缓存键覆盖规范输入、图像内容/顺序、端点、凭证作用域摘要及版本；命中不上传、不重复记账。缓存损坏回退请求，保存失败不丢弃有效结果。
- 2026-09-08 通过 UI 导出了旧 DSL 到 .validation/tutorial-workflow-before-20260908.yml 并导入视觉草稿；公开 GET /v1/parameters 仍只有四个文字输入。编辑器持续 WebSocket error，同源代理探测却返回 101；根因未最终定位，不扩大 CORS、不绕过认证或直接写 Dify 数据库发布。
- 新版本地服务启动命令被执行环境 policy 拒绝；不得以换壳/后台变体绕过。旧 Docker 工作台数据不同且留有 ANALYZING 任务，没有重启或迁移它。真实新成片和剪映客户端验收仍未完成，不能把本地代码/Mock 测试当上线。

以下“首批”条目为历史边界；冲突时以上述最新状态为准。

- `EditRecipe.director_plan` 可选，version=1。每段包含 purpose、完整 narration、material_id、source_start_seconds/source_end_seconds、rationale。仅引用该任务分析的素材，禁止模型指定文件路径；越界、重叠、非法结构被拒绝。
- 正式 PipelineService 与 TimelinePlanner 共同使用该计划；有计划时旁白不再走固定品类模板。无计划时保留明确标记的本地预览，商品降级旁白不再把所有商品写成宠物梳。
- Dify 教程/趋势请求和云 TTS 均要求 task.cloud_processing_allowed。无同意不发送请求；无 Key 仍可本地处理。
- `director-plan.json` 与 manifest.creative_validation 保存实际模式。素材时间范围有效只表示机械校验通过；semantic_match/product_claims/style_match/native_playback 仍为 unknown。课程规则对分镜的作用未独立验证时不伪造通过结论。
- 教程 YAML 已增加可选计划输出及 `visual_frames` file-list，LLM vision 绑定 `[start, visual_frames]`，但没有自动更新用户已发布的 Dify 工作流。获云处理同意且配置教程 Dify 后，正式任务最多上传 8 张任务分析目录内的有效 JPEG/PNG（每素材最多 2 张、每张不超过 2 MiB/4096 像素），复用教程凭证调用公开 `files/upload` 后传入工作流。模型是否真正使用图像、实际理解质量仍需真实服务验收，不能由 HTTP 成功推断。
- `analysis/visual-input-evidence.json` 记录本轮图像序号、素材 ID、时间码和传输状态；不保存凭据或本地路径。`not_sent/text_only/attempting/workflow_returned/failed_or_partial` 是传输状态，非效果评分。上传失败不自动重试，可能已有部分图像留在所配置的 Dify；遵循该部署的数据保留策略。
- 本批只把当前任务素材抽样接入分镜请求，尚未把教程视频/参考成片按角色直接传入此视觉输入，也未实现模型语义结果缓存。旧工作流需要更新发布，图像模型需要已开通；不能称本机运行实例已自动升级。
- 字幕仍按字数估计时间，不是词级对齐。实际多模态、商品事实验证、语义索引、风格验收与有限返工属于后续批次；不能把本批自动测试说成整体参考效果验收完成。


本文件供 Codex 或其他代码代理读取。普通用户的完整说明见 `docs/capabilities-and-configuration.md`；机器可读能力清单见 `services/control-plane/app/capability_catalog.json`。

Mac 用户逐步操作入口：`docs/macos-user-guide.md`。2026-09-07 文档核查发现 `provider_settings.html` 引用 `provider-settings.js/css`，实际文件名为 `provider_settings.js/css`；修复并验证前不得把增强配置页称为已可用，本次仅记录，没有修改应用代码。

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

- macOS 原生脚本不主动读取仓库根 `.env`。可选配置支持启动进程环境和 ProviderSettingsService 的加密持久化；图形配置页当前资源引用问题见上文。不得为了绕过页面问题索取用户秘密。
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
