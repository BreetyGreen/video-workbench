# 生产部署手册

## 架构边界

控制台、SQLite/持久化数据、定时任务、Dify 调用和素材目录部署到服务器。剪映保留在 Windows 本机；服务器不尝试在 Linux 容器里运行剪映。服务器生成的 `draft.zip` 由本地导入脚本放入剪映草稿目录。

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
