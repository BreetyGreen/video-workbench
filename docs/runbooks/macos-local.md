# macOS 本地运行手册

## 最短路径

在仓库的 `全自动视频发布` 目录执行：

```bash
python3 scripts/doctor.py
bash scripts/bootstrap.sh
```

`bootstrap.sh` 固定使用 Python 3.12 和仓库内的 `uv.lock`，安装缺失的 FFmpeg，完成依赖同步，并在 `http://127.0.0.1:8130/health` 正常后打开工作台。再次运行不会启动重复进程。

停止服务：

```bash
bash scripts/stop-local.sh
```

## 自动创建的位置

- 数据库、日志、任务和 PID：`~/Library/Application Support/VideoWorkbench`
- 模型缓存：`~/Library/Caches/VideoWorkbench`
- 自动监听素材入口：`~/Movies/VideoWorkbench Inbox`

这些目录都在 Git 仓库之外。删除或重新克隆仓库不会删除用户素材和任务。

## Doctor 动作说明

- `install_ffmpeg`：启动脚本通过已有 Homebrew 安装 FFmpeg；没有 Homebrew 时只提示官方安装地址。
- `install_or_open_jianying`：本地剪辑和草稿包仍可生成；安装并至少打开一次剪映后重新运行 Doctor。
- `choose_jianying_draft_root`：只有多个候选目录或无法唯一确认时，应用才要求用户选择一次文件夹。

Doctor 只输出平台、命令可用性、非敏感路径状态和动作名称，不输出环境变量、凭据或目录内容。

## macOS 权限

首次选择剪映草稿目录或素材收件箱时，macOS 可能要求文件夹访问权限。这属于系统权限确认，不是项目配置。只授权实际需要的文件夹即可。

## 常见问题

- `uv installation finished but the executable was not found`：关闭终端后重新打开，再次运行 `bash scripts/bootstrap.sh`。
- `FFmpeg is required`：从 [Homebrew 官网](https://brew.sh) 安装 Homebrew，再次运行启动脚本。
- 服务没有在 120 秒内健康：查看 `~/Library/Application Support/VideoWorkbench/logs/control-plane.log`，然后运行 `python3 scripts/doctor.py`。
- 剪映已安装但没有识别草稿目录：先手动打开剪映创建一个空项目，再运行 Doctor；仍有多个候选时在应用里选择一次。
