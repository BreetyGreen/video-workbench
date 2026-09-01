# 仅需账号本人完成的操作

这份清单只保留购买、身份认证、平台审批和 OAuth 同意。代码、界面、测试、素材合规校验、剪映草稿导入脚本和服务器部署包已经由项目处理。

如果你还不确定某项能力是否需要 Key，先看[剪辑能力与配置完整指南](capabilities-and-configuration.md)。本地剪辑主链无需账号配置；本页列出的都是按需增强或外部授权。

## 先从配置助手开始

启动工作台后打开 <http://127.0.0.1:8130/setup>。本地上传、分析、剪辑、字幕、预览和剪映草稿不需要账号配置；先点击“使用本地模式进入工作台”。下面的操作只在你需要相应增强能力时完成。

任何 API Key、Access Key、Cookie 或 OAuth 令牌都不要发到聊天、Issue 或截图里。配置助手的状态接口只返回诊断和掩码，不返回秘密值。

## 0. 火山引擎（按需）

火山方舟模型、豆包语音和账户用量查询是三种不同能力，不要把它们当成同一个 Key：

1. 方舟模型：在[火山方舟 API Key 管理](https://console.volcengine.com/ark/apiKey)创建专用 Key，用于模型推理。
2. ASR/TTS：按实际开通的豆包语音服务取得对应凭证；没有配置时正式转写回退本地 Whisper。
3. 账户余量：在工作台“配置助手 → 火山引擎增强 → 配置只读用量”中填写专用 IAM 用户的 AK/SK，并只授予查询用量所需权限。
4. 验收：配置助手显示“已连接”或“部分连接”；账户余额读取失败不得解释为余额为零。

## 1. 购买或指定服务器

1. 在火山引擎云服务器 ECS 购买一台 Linux 服务器；起步可选 2 vCPU / 4 GB / 80 GB，服务器同时跑 Whisper 或大量 FFmpeg 时选择 4 vCPU / 8 GB 以上。
2. 安全组仅开放 22、80、443。
3. 把 SSH 目标（如 `root@服务器IP`）和专用目录（建议 `/opt/video-workbench`）提供给部署脚本。
4. 验收变绿条件：`https://域名/health` 返回 `status=ok`、`database=ok`、`artifact_storage=ok`。

如果服务器也要承载完整 Dify，而不是连接现有 Dify 地址，建议直接选 4 vCPU / 8 GB；购买后只需提供 SSH 目标，我会继续执行 Dify 官方 Compose 与本项目部署，不需要你手工搬容器。2 vCPU / 4 GB 只适合控制台、定时任务和轻量 FFmpeg，把 Dify 或重型 Whisper 放在外部。

## 2. 抖音开放平台应用与 OAuth

1. 进入 [抖音开放平台控制台](https://open.douyin.com/platform/)，创建移动/网站应用。
2. 在“应用详情 → 能力管理 → 能力实验室”申请“代替用户发布内容到抖音”，接口 Scope 为 `video.create.bind`。
3. 若要官方热点搜索，再申请视频搜索相关能力。
4. 由要发布视频的抖音账号完成用户 OAuth，取得该用户的 `open_id`、`access_token` 和刷新令牌；访问令牌不得发在聊天或截图中。
5. 把凭证写入服务器受保护的 `.env.production` 或后续 OAuth 凭证存储。
6. 验收变绿条件：连接诊断由 `oauth_required/permission_required` 变为 `configured`，审核页可选择“仅自己可见”或“公开发布”。仅自己可见也是已创建并进入审核的视频，不是客户端草稿。

## 3. 抖店/商家商品素材授权

1. 由店铺或供应商在抖店开放平台授权你的应用访问商品详情与素材中心。
2. 保留品牌方/商家对视频的书面授权、商品 ID、允许平台和授权期限。
3. 当前即可在“素材中心 → 上传授权视频”登记这些视频；获得抖店 API 授权后再把自动拉取凭证接入相同素材模型。
4. 验收变绿条件：素材显示 `merchant_authorized`、授权依据、商品 ID、允许平台和有效期，且 `rights_status=authorized`。

## 4. 可选素材与生成服务

- Pexels：在 [Pexels API](https://www.pexels.com/api/) 申请 Key，填写 `VIDEO_WORKBENCH_PEXELS_API_KEY`。
- Pixabay：在 [Pixabay API](https://pixabay.com/api/docs/) 申请 Key，填写 `VIDEO_WORKBENCH_PIXABAY_API_KEY`。
- Seedance：在火山方舟创建已开通的视频生成模型推理端点，填写 `VIDEO_WORKBENCH_SEEDANCE_API_KEY` 和 `VIDEO_WORKBENCH_SEEDANCE_MODEL`。系统不会因存在免费资源包就猜测可用端点，也不会自动触发付费生成。

验收变绿条件：素材状态页相应提供方由 `not_configured` 变为 `configured`；一次测试任务返回有来源记录的视频资产。

## 4.1 钉钉素材入口（按需）

1. 在[钉钉开放平台](https://open-dev.dingtalk.com/)创建企业内部应用和 Stream 模式机器人。
2. 为应用取得机器人应用标识与应用密钥，并由组织管理员完成所需权限授权。
3. 在本机受保护的运行配置中填写 `VIDEO_WORKBENCH_DINGTALK_CLIENT_ID` 和 `VIDEO_WORKBENCH_DINGTALK_CLIENT_SECRET`，然后启用钉钉连接器。
4. 验收：配置助手中的“钉钉素材入口”变为“已连接”，发送一条授权文件后任务来源显示为钉钉。

## 5. 域名与上线

1. 将域名 A 记录解析到服务器公网 IP。
2. 中国大陆服务器按实际业务完成备案要求。
3. 在 `.env.production` 填 `VIDEO_WORKBENCH_DOMAIN` 和 `ACME_EMAIL`，生成 Caddy Basic Auth 哈希。
4. 运行 `scripts/deploy-server.ps1`，再检查首页、素材中心、热点雷达、用量中心、审核页和每日调度。

## 6. 首次配对要接收草稿的电脑

1. 在受保护的服务器控制台生成一次性设备配对码。
2. 在已安装并至少打开过一次剪映/CapCut 的电脑运行同步助手，输入一次配对码。
3. Windows/macOS 弹出文件访问或自动化权限时由设备本人确认；以后助手可以常驻监听，不需要 Codex。

## 不需要你再做的事情

- 不需要手工整理旧验证任务：它们已归档且可恢复。
- 不需要再手工把今天的任务导入剪映：任务 `3c4bf267-77ad-4dac-9a85-5ee8a25ddbd3` 已导入 `B:\JianyingData\Drafts\JianyingPro Drafts\宠物治愈瞬间-290fadb1`，16 条容器路径已重写，媒体路径校验通过。
- 不需要找所谓“抖音草稿箱 API”：官方交付只实现真实的上传/创建视频；可编辑草稿保留在剪映本地。
