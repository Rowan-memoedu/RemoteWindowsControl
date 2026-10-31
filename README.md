# Windows 远程协助

教师电脑通过 Tailscale 和 Windows-MCP 操作学生的 Windows 电脑。学生电脑不安装 Codex。

学生主动启动协助窗口，结束后停止 Windows-MCP。接入密钥、配对配置、运行日志和交付包保存在仓库之外，不提交到 GitHub。

源码：D:\Projects\RemoteWindowsControl

交付包与验证：D:\Artifacts\RemoteWindowsControl

教师本机状态：D:\AppData\RemoteWindowsControl

## 学生使用

完整解压 ZIP，双击 `Start.cmd`，确认管理员提示。窗口显示“已启动，等待老师连接”后保留窗口，电脑保持解锁。结束时关闭窗口。默认交付通用包，同一个 ZIP 可以发给不同学生。

学生无需 Google、Tailscale 或 OpenAI 账号，不安装 Codex。当前发行包支持 Windows 10/11 AMD64。Python 和全部依赖随包提供，联网只用于 Tailscale 接入及后续任务。

Windows-MCP 在交互桌面的管理员会话中运行，开启全部工具：文件、PowerShell、进程、注册表和桌面工具。没有额外的命令、目录或软件白名单；启动器清除继承的工具排除设置，避免环境变量意外减少权限。Codex 单次工具等待时间为 3600 秒，长 PowerShell 命令需同时传入合适的 `timeout`，后台任务可按正常 Windows 方式启动。

程序只绑定 Tailscale IPv4，使用每台设备独立的 Bearer Token，并同时限制 Windows 防火墙和 MCP 来源地址。通用包首次运行会随机生成设备编号，保存在当前 Windows 用户的本机状态中，重复启动和重新解压保持相同身份；教师按设备名派生对应凭据，无需学生回传密钥。教师到学生的全部端口和 IP 协议均放行，支持访问学生电脑上另行启动的网站或其他服务；这些连接身份校验不缩小教师的操作权限。关闭窗口只结束远程控制服务，不额外强制结束已启动的应用和后台任务；不会自动启动、修改 UAC 策略或替换既有 Tailscale 身份。

Tailscale 网络服务使用 Windows 的 `--unattended=true` 模式，避免没有托盘程序时出现 `NoState`；这只维持网络连接，Windows-MCP 仍须学生主动打开窗口，关闭窗口后不再提供远程操作。

## 教师配置

教师本机首先登录 Tailscale。网络策略必须显式设置空 `acls`，且唯一网络 grant 为教师 Tailscale IPv4 → `tag:codex-student` 的 `*`（全部端口与 IP 协议）。标签由管理员管理。学生主动访问教师或其他学生的方向没有授权。已存在其他设备或策略时先检查原有用途，不直接覆盖。

当前 Personal 免费计划包含 50 个带标签的资源，因此本方案可免费接入 50 台学生电脑；教师本机使用用户身份，不占这 50 个名额。通用包不改变设备额度。超过免费额度后，官方价格为每个额外带标签资源 1 美元/月。Personal 适用于非商业用途，收费教学或机构用途需按官方适用范围选择计划。

通用包使用可重复、非临时、预授权、仅含 `tag:codex-student` 的 Auth Key，最长有效期为 90 天。`New-UniversalPackage.ps1` 接收官方 API 返回的接入码 JSON，打包已有运行组件并保存教师的批次配对配置。密钥更新时保留同一 `fleetId` 和配对秘密；重新运行打包脚本即可，现有设备身份不变。批量接入依靠 Tailscale 官方能力，不运行额外的注册服务器。

接入码有效期只限制新电脑首次加入，不会自动撤销已经加入的带标签设备。正式结束设备管理时在 Tailscale 控制台撤销对应设备。通用包包含可复用接入码和批次配对秘密，不应公开发布；教师 API 凭据不进入任何学生包。

学生启动后，运行 `Connect-Students.cmd` 或 `python connect_students.py`，一次扫描此通用包接入的全部设备，逐台完成真实 MCP 握手后注册和启用对应连接。`--list` 仅查看设备，`--host <设备编号>` 只连接指定电脑。扫描需要在学生启动后执行，不是后台常驻自动发现服务。首次加载新 MCP 工具可能需要在 ChatGPT 桌面端中的 Codex 新开对话；不自动重启正在使用的应用。

原有单机包仍可使用：`New-StudentPackage.ps1` 接收单次接入码和教师 API 凭据，`configure_codex.py <教师配对文件> --connect` 连接该设备。单机包不能多人共用；已经使用单机包接入的电脑继续使用原包，不自动覆盖其 Tailscale 身份。

## 构建与验证

构建入口 `Build-Runtime.ps1`，固定 Windows-MCP 0.8.8、CPython 3.14.10 和 Tailscale 1.104.4。依赖从 PyPI 锁定并校验哈希；uv 仅用于教师构建环境，不分发给学生。MSI 校验官方 SHA-256 和 Tailscale Authenticode 签名。

- `tests/smoke_runtime.py`：解压至新位置后实际启动 HTTP MCP；验证 Bearer 认证、来源地址限制、工具列表与真实 PowerShell 命令。
- `tests/test_config.py`：保留现有 Codex 配置、重复执行、名称冲突拒绝和启用更新。
- `tests/Test-Student.ps1`：Windows PowerShell 5.1 语法及来源地址校验。
- `tests/lifetime_canary.py`：关闭启动器后控制服务停止，已启动的独立后台进程继续运行。
- `tests/test_universal.py` 和 `tests/Test-UniversalPairing.ps1`：两台模拟电脑的独立身份、重复启动、接入码更新、旧包兼容、损坏状态拒绝、PowerShell/Python 凭据一致性、设备发现及多 MCP 配置保留。

安装失败会显示具体错误，不把仅完成下载或组件解压称为已接通。远端整机安装、UAC 和跨网络连通需要第一台学生电脑的实际验收。

## 官方来源

- https://tailscale.com/docs/install/windows/msi
- https://tailscale.com/docs/features/access-control/auth-keys
- https://tailscale.com/pricing
- https://github.com/CursorTouch/Windows-MCP/tree/v0.8.8
- https://docs.astral.sh/uv/concepts/python-versions/
- https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json
