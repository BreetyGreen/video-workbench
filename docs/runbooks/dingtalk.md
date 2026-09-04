# 钉钉课程入口运行手册

## 当前边界

钉钉是课程文件入口，不是剪辑器。真实组织接入需要企业内部应用、Stream 机器人和管理员授权；没有这些凭据时，可用 `scripts/simulate-dingtalk-course.py` 验证完全相同的课程入库接口。

## Windows 安装与检查

只从钉钉官方下载页取得安装器。安装前检查 Authenticode 发布者，安装目标优先使用 `B:\DingDing` 或 `B:\Apps\DingTalk`。应用二进制放在 B 盘后，Windows 仍可能在用户 `AppData` 写入少量登录状态、缓存与更新元数据，这是客户端正常行为。

运行只读检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/doctor-dingtalk.ps1
```

输出只包含安装路径、版本、签名状态和进程状态，不读取账号、聊天、文件或凭据。

## 无真实钉钉凭据时的端到端验收

```powershell
services/control-plane/.venv/Scripts/python.exe scripts/simulate-dingtalk-course.py `
  --base-url http://127.0.0.1:8130
```

模拟事件含教程、案例和三段合成素材。后续教程理解、素材镜头分析、授权过滤、自动剪辑、质量门禁和剪映交付均使用真实代码。

## 真实组织接入

1. 管理员创建企业内部应用与 Stream 机器人。
2. 为机器人开通群消息与文件下载所需权限。
3. 在服务器的秘密管理界面设置 `DINGTALK_CLIENT_ID` 和 `DINGTALK_CLIENT_SECRET`，不要写入 Git。
4. 启动 `dingtalk-connector`，把课程文件发到专用群；用 `#教程`、`#案例`、`#素材`、`#个人学习`、`#商用授权` 标记文件用途和权利。
5. 购买课程不自动等于取得商用素材授权；商用任务只会选择明确标记 `commercial_authorized` 的素材。
