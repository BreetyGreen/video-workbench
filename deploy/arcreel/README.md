# ArcReel 本地部署

本目录固定使用 `ghcr.io/arcreel/arcreel:0.26.0`。服务只监听本机回环地址，不直接暴露到局域网或公网。

## 启动

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-arcreel.ps1
```

首次启动会从 `.env.example` 创建未跟踪的 `.env`。当 `AUTH_PASSWORD` 为空时，ArcReel 会自动生成密码并写回 `.env`；请只在本机查看，不要提交或粘贴到聊天中。

界面：<http://127.0.0.1:1241/>

健康检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-arcreel.ps1
```

持久数据保存在 `data/arcreel/`，容器重建不会删除项目和日志。
