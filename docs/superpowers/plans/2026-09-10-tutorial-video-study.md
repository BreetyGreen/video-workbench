# 教程视频完整学习（Tutorial video study）

状态：2026-09-10 设计中，尚未实现。目标是回应用户明确需求："把所有教学视频完整学一遍，之后给素材就能剪出教程示范的效果"。

## 现状与差距

- 27 节课已有完整转写（BigASR/Whisper），但视觉层只有每节抽样几帧；老师在剪映里的实际操作（切点、推近幅度、字幕位置、音效时机、调色参数）只学到文字层面。
- 课程系统里的教程资产是 7 份带时间码的规则 TXT（10 条规则），不是视频本体；`course_max_file_bytes` 500 MiB 挡住了 26 个原始教程文件。
- 导演模型已可走任意 OpenAI 兼容端点（`openai_compatible_director.py`），百炼 `qwen3-vl-plus` 支持视频输入（`video_url`，`fps` 0.1–10，默认 2）。

## 设计

1. **入库**：`course_max_file_bytes` 提到 4 GiB，教程视频以 `tutorial` 角色正式入库（流式写入已支持）。
2. **分段学习服务** `tutorial_video_study_service.py`：
   - 按 240 秒切段，转码为 480p、约 400 kbps 的小 MP4（单段 < 10 MiB，可 base64 直传），附该段完整转写。
   - 请求导演端点，要求结构化 JSON：`segments[{start,end,type:lecture|software_operation|finished_example|other,summary,teacher_actions[],rules[{category,instruction,evidence_quote,start,end}]}]`。
   - 每段结果落盘 `<asset>.study/<chunk>.json`，聚合为 `<asset>.lesson-study.json`；失败段记录原因，不伪造。
   - 用量按段记入课程学习账本（provider `openai_compatible`，purpose `tutorial_study`）。
3. **接入教程理解**：`TutorialUnderstandingService.process` 在导演端点可用且允许云处理时，用学习结果替代本地关键词分类：`type` 直接作为 `TutorialSegment.segment_type`，`rules` 生成 `EditingRule`（模型给的 category 映射到 `ALLOWED_COURSE_RULES`，映射不到的归 `structure`），`source_start_ms/end_ms` 来自模型给的时间并裁剪到段内。
4. **验收**：随机抽 5 段人工对照视频；规则必须能在转写或画面里找到证据；不通过的课标记 `partial`。

## 费用估算（待实测）

240 分钟教程，480p、fps 0.5：约 7200 帧 × 约 400 token ≈ 3M 输入 token，加转写文本约 0.3M。百炼新用户每模型约 100 万免费 token（90 天，是否含视觉模型需在控制台确认），完整学习大概率超出免费额度，需要账户有余额；qwen3-vl-flash 可先做粗学习降低成本。

## 不做的事

- 不复制教程音频/画面进成片；不把示例商品口播当商品事实；不绕过任何平台配额。
