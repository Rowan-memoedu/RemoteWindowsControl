# Windows 远程协助

教师电脑通过 Tailscale 和 Windows-MCP 操作学生的 Windows 电脑。学生电脑不安装 Codex。

学生主动启动协助窗口，结束后停止 Windows-MCP。接入密钥、配对配置、运行日志和交付包保存在仓库之外，不提交到 GitHub。

源码：D:\Projects\RemoteWindowsControl

交付包与验证：D:\Artifacts\RemoteWindowsControl

教师本机状态：D:\AppData\RemoteWindowsControl

## 学生使用

完整解压学生专属 ZIP，双击 `Start.cmd`，确认管理员提示。窗口显示“已启动，等待老师连接”后保留窗口，电脑保持解锁。结束时关闭窗口。

学生无需 Google、Tailscale 或 OpenAI 账号，不安装 Codex。当前发行包支持 Windows 10/11 AMD64。Python 和全部依赖随包提供，联网只用于 Tailscale 接入及后续任务。

Windows-MCP 在交互桌面的管理员会话中运行，提供文件、PowerShell、进程、注册表和桌面工具。程序只绑定 Tailscale IPv4，使用每台设备独立的 Bearer Token，并同时限制 Windows 防火墙和 MCP 来源地址。关闭窗口会通过 Windows Job Object 结束该窗口的服务和子进程；不会自动启动、修改 UAC 策略或替换既有 Tailscale 身份。

Tailscale 网络服务使用 Windows 的 `--unattended=true` 模式，避免没有托盘程序时出现 `NoState`；这只维持网络连接，Windows-MCP 仍须学生主动打开窗口，关闭窗口后不再提供远程操作。

## 教师配置

教师本机首先登录 Tailscale。网络策略必须显式设置空 `acls`，且唯一网络 grant 为教师 Tailscale IPv4 → `tag:codex-student` 的 `tcp:8765`。标签由管理员管理。已存在其他设备或策略时先检查原有用途，不直接覆盖。

为每台学生电脑创建单次、非临时、预授权、仅含 `tag:codex-student` 的 Auth Key。接入码有效期只限制首次加入，不会自动撤销已经加入的设备。正式结束设备管理时在 Tailscale 控制台撤销对应设备。

`New-StudentPackage.ps1` 接收官方 API 返回的接入码 JSON，以及只保存在教师本机的 DPAPI 加密 API 凭据；实时检查网络隔离后，生成学生专属包并注册一个暂时禁用的 Codex MCP。API 凭据不会进入学生包。禁止多台电脑复用同一个包。

学生启动后，由教师执行 `configure_codex.py <教师配对文件> --connect`。脚本读取 Tailscale 在线设备地址，完成真实 MCP 握手后启用对应连接。首次加载新 MCP 工具可能需要在 ChatGPT 桌面端中的 Codex 新开对话；不自动重启正在使用的应用。

## 构建与验证

构建入口 `Build-Runtime.ps1`，固定 Windows-MCP 0.8.8、CPython 3.14.10 和 Tailscale 1.104.4。依赖从 PyPI 锁定并校验哈希；uv 仅用于教师构建环境，不分发给学生。MSI 校验官方 SHA-256 和 Tailscale Authenticode 签名。

- `tests/smoke_runtime.py`：解压至新位置后实际启动 HTTP MCP；验证 Bearer 认证、来源地址限制、工具列表与真实 PowerShell 命令。
- `tests/test_config.py`：保留现有 Codex 配置、重复执行、名称冲突拒绝和启用更新。
- `tests/Test-Student.ps1`：Windows PowerShell 5.1 语法及来源地址校验。
- `tests/lifetime_canary.py`：结束父进程后其子进程被回收。

安装失败会显示具体错误，不把仅完成下载或组件解压称为已接通。远端整机安装、UAC 和跨网络连通需要第一台学生电脑的实际验收。

## 官方来源

- https://tailscale.com/docs/install/windows/msi
- https://tailscale.com/docs/features/access-control/auth-keys
- https://github.com/CursorTouch/Windows-MCP/tree/v0.8.8
- https://docs.astral.sh/uv/concepts/python-versions/
- https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json
