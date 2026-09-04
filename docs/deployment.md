# 生产部署手册

## 架构边界

控制台、SQLite/持久化数据、定时任务、Dify 调用和素材目录部署到服务器。剪映保留在 Windows/Mac 用户电脑；服务器不尝试在 Linux 容器里运行剪映。服务器生成的 `draft.zip` 由已配对的同步助手校验后放入剪映草稿目录并启动客户端。

## 服务器要求

- 推荐起步：2 vCPU、4 GB 内存、80 GB 系统盘；若在服务器本地跑 Whisper/大量 FFmpeg，使用 4 vCPU、8 GB 以上。
- Linux、Docker Engine 和 Docker Compose v2。
- 安全组只开放 22、80、443；8130/1241 保持本机绑定。
- 域名已解析到服务器时由 Caddy 自动申请证书；未使用域名时先用 SSH 隧道访问。

## 首次部署

1. 把项目放到服务器的专用目录，例如 `/opt/video-workbench`。
2. 复制 `deploy/.env.production.example` 为项目根目录 `.env.production`，填入唯一密码、密钥和已取得的平台凭证，并设置文件权限为仅管理员可读。使用 `docker run --rm caddy:2.10-alpine caddy hash-password --plaintext '你的强密码'` 生成 `VIDEO_WORKBENCH_BASIC_AUTH_HASH`，不要把明文密码写进 Caddy 配置。
3. 验证配置：

   ```bash
   docker compose --env-file .env.production -f deploy/compose.yml -f deploy/compose.production.yml config --quiet
   ```

4. 启动：

   ```bash
   docker compose --env-file .env.production -f deploy/compose.yml -f deploy/compose.production.yml up -d --build
   ```

5. 检查 `https://你的域名/health`，应返回数据库和产物存储均为 `ok`。

Windows 也可以在远端目录准备好后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy-server.ps1 -SshTarget user@server -RemotePath /opt/video-workbench
```

## 备份与恢复

部署前和升级前运行 `scripts/backup-server.ps1`；脚本会压缩并验证 `data/control-plane`。恢复时先停止服务，把当前数据目录移动到隔离位置，解压备份，再启动服务并检查 `/health`、任务数量和最近产物。

生产环境使用命名卷时，先用临时容器把 `control-plane-data` 导出到主机目录，再运行同样的压缩验证。不要在服务运行时直接删除或覆盖 SQLite 文件。

## 上线后检查

- 首页、素材中心、热点雷达、用量中心和审核页均能互相返回。
- 每日调度只运行一份，不同时启动第二个控制面实例。
- Pexels/Pixabay/Seedance 缺凭证时显示 `not_configured`，不影响本地授权素材回退。
- 抖音交付只有在应用获得 `video.create.bind` 且用户 OAuth 有效时启用。
- 剪映草稿在 Windows 上运行 `verify-jianying-handoff.ps1` 后再人工打开终审。

## 配对用户电脑并自动导入剪映

1. 管理员登录受 Basic Auth 保护的控制台，调用 `POST /api/devices/pairing-codes` 生成十分钟有效、只能使用一次的配对码。
2. 普通用户从 [Release 页面](https://github.com/BreetyGreen/video-workbench/releases/latest) 下载对应系统产物并运行随包安装脚本；安装器注册登录自启。首次运行输入一次配对码，以后不需要 Codex 或 Python。
3. 开发者需要排障时才直接运行：

   ```bash
   python scripts/sync-jianying-device.py \
     --server-url https://你的域名 \
     --data-dir "用户自己的同步数据目录" \
     --watch
   ```

4. 助手无回显地要求配对码，换取只显示一次的设备令牌。Windows 使用当前用户 DPAPI 加密保存；macOS 保存到权限为 `0600` 的用户目录文件。服务器只存令牌 HMAC-SHA256 摘要。
5. 之后助手只访问 `/api/devices/me/*` 专用接口。作业首次出队时原子绑定到该设备，其他设备不能查看、下载或回报；助手随后下载质量报告和草稿、执行 ZIP/媒体路径校验、新建草稿、启动剪映并回报结果。
6. Caddy 只允许 `/api/devices/pair` 与 `/api/devices/me/*` 跳过网页 Basic Auth；这些接口本身分别由一次性码和设备 Bearer 令牌保护。`/api/devices/pairing-codes` 仍受管理员 Basic Auth 保护。

## 同步助手发布

- 本地构建：Windows 运行 `sync-helper/build.ps1`，macOS 运行 `sync-helper/build.sh`。
- 自动构建：推送 `sync-helper-v*` 标签后，`.github/workflows/sync-helper-release.yml` 在 `windows-latest` 和 `macos-14` 分别生成产物并上传到草稿 Release；完成签名、公证和实机验收后才手动公开。
- Windows 安装器优先使用 B 盘；没有 B 盘时回退到当前用户的 `LOCALAPPDATA`，不会假设所有用户磁盘布局相同。
- macOS 使用 `~/Applications`、`~/Library/Application Support` 和用户级 LaunchAgent，不要求管理员修改系统目录。
- GitHub Actions 当前生成的是未签名构建。对外发布前必须补充 Authenticode 和 Apple Developer ID/公证；这一步需要仓库所有者提供签名身份，不能由代码自行伪造。

当前部署实现是单工作区、单实例 SQLite 和同步作业执行，适合受控团队首发，不等同于多租户高并发 SaaS。扩展到公网多租户前，需要把任务执行拆到持久队列/worker，并使用独立数据库、对象存储和租户级设备路由。
