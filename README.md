# Windows 远程协助

教师电脑通过 Tailscale 和 Windows-MCP 操作学生的 Windows 电脑。学生电脑不安装 Codex。

学生首次配置一次，此后登录安装时的 Windows 账户会自动上线。接入密钥、配对配置、运行日志和交付包保存在仓库之外，不提交到 GitHub。

源码：D:\Projects\RemoteWindowsControl

交付包与验证：D:\Artifacts\RemoteWindowsControl

教师本机状态：D:\AppData\RemoteWindowsControl

## 学生电脑状态页

在教师电脑运行一次 `pwsh -File .\Install-StudentDashboard.ps1`，即可用桌面“学生电脑状态”或 [本机网页](http://127.0.0.1:8766/) 查看。页面服务仅监听本机，随教师登录 Windows 启动，用教师已有的配对资料发现通用包和单机包设备。

打开页面时每 15 秒更新网络状态。选中的设备在线时检查协助服务，约每 90 秒通过一条固定的只读命令采集配置，可点击“刷新”立即重读。学生正在操作鼠标键盘时延后采集。关闭页面会停止发起新的读取。离线时展示 Tailscale 的最后在线时间和带采集时间的设备记录，本机断网时标记为状态待确认。

设备资料缓存在教师端 `D:\AppData\RemoteWindowsControl\dashboard`。已有操作记录中明确确认的学生姓名与设备编号用于标注，首次显示可沿用已保存的配置和安装记录。页面只提供读取接口，浏览器不会取得配对凭据。停用请在教师电脑的任务计划程序中停用并结束 `RemoteWindowsControl-StudentDashboard`。

## 学生使用

完整解压 ZIP，双击 `Start.cmd`，确认管理员提示。窗口显示“配置完成，已自动上线”后即可关闭，后续无需再次运行安装包或逐次确认连接。默认交付通用包，同一个 ZIP 可以发给不同学生。旧版用户先关闭原协助窗口，运行更新后的包一次，原设备编号与配对凭据不变。

学生通过桌面“远程协助设置”停止或恢复自动连接。停止会同时停用登录触发任务、结束控制服务并关闭原协助防火墙规则；恢复会重新启用。仅关闭安装窗口不再中断协助。程序文件复制到本机固定目录，后续运行不依赖下载文件夹或解压包。

学生无需 Google、Tailscale 或 OpenAI 账号，不安装 Codex。当前发行包支持 Windows 10/11 AMD64。Python 和全部依赖随包提供，联网只用于 Tailscale 接入及后续任务。

Windows-MCP 在交互桌面的管理员会话中运行，开启全部工具：文件、PowerShell、进程、注册表和桌面工具。没有额外的命令、目录或软件白名单；启动器清除继承的工具排除设置，避免环境变量意外减少权限。Codex 单次工具等待时间为 3600 秒，长 PowerShell 命令需同时传入合适的 `timeout`，后台任务可按正常 Windows 方式启动。

程序只绑定 Tailscale IPv4，使用每台设备独立的 Bearer Token，并同时限制 Windows 防火墙和 MCP 来源地址。通用包首次运行会随机生成设备编号，保存在当前 Windows 用户的本机状态中，重复启动和重新解压保持相同身份；教师按设备名派生对应凭据，无需学生回传密钥。教师到学生的全部端口和 IP 协议均放行，支持访问学生电脑上另行启动的网站或其他服务；这些连接身份校验不缩小教师的操作权限。不修改 UAC 策略、Windows 自动登录设置或既有 Tailscale 身份。

Tailscale 使用自动启动服务和 `--unattended=true` 模式。Windows-MCP 使用 Windows 原生计划任务，在安装者登录后延迟 15 秒启动；任务采用 `Interactive` 登录类型和 `Highest` 权限，始终处于实际桌面会话而非 Session 0。没有执行时长上限，使用电池时继续运行。同一任务附带每分钟重复触发，已在运行时忽略，异常停止后自动补启；不依赖单独的 RestartOnFailure 属性。网络尚未就绪时后台等待正确的 Tailscale 配置。初次管理员授权后，后续登录启动不需要重复 UAC。

计划任务直接使用 `pythonw.exe` 无控制台入口，通过 `CREATE_NO_WINDOW` 启动后台管理脚本，避免 PowerShell 启动时先出现控制台再隐藏。Windows-MCP 原生 PowerShell 执行器已经使用无窗口进程；本地启动适配还让 `App.launch_executable` 启动命令行程序时不分配控制台，GUI 软件的正常窗口不受此标志影响。安装向导、软件本身的窗口、权限提示和学生主动打开的“远程协助设置”正常显示。

教师执行后台辅助任务时使用 PowerShell 工具；其中另行调用 `Start-Process` 启动命令行助手或安装器时显式使用 `-WindowStyle Hidden`，有官方静默安装参数时优先使用。需要显示软件界面时使用 App 工具或显式 `-WindowStyle Normal`。不通过终端窗口输入命令，不修改学生系统的全局控制台设置。

本方案保证的使用条件是：电脑已开机、登录安装时的 Windows 账户、联网且未休眠；截图和桌面操作需要解锁。尚未登录 Windows 时只有 Tailscale 网络层可用，不将 Windows-MCP 放入 SYSTEM 服务，也不绕过登录或安全桌面。安装必须在具有管理员权限的日常账户中完成；如果标准账户在 UAC 中输入另一个管理员账户，会明确拒绝，避免任务绑定到错误账户。

新设备优先安装到 `D:\AppData\RemoteWindowsAssist\<设备编号>`；无可用 D 盘时使用当前用户 LocalAppData。已有设备沿用原运行目录，避免复制运行时和破坏身份。持久化配置只保存该设备的 MCP 凭据，不复制 Tailscale 接入码或通用包配对秘密。桌面“远程协助设置”是取消自动启动的恢复入口，停用后可随时重新启用。

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
- `tests/persistence_canary.py`：实际注册临时登录计划任务，验证交互会话、认证 MCP、服务崩溃自动恢复、停止和恢复；不注销或重启正在使用的电脑。本机未提升时以 Limited 运行测试并单独校验生产 Highest 定义，不能把此测试当作学生机管理员权限或完整重启验收。
- `tests/quiet_runtime_canary.py`：通过实际 App 启动实现读取 Win32 控制台句柄与窗口可见性，确认命令行无控制台、GUI 可正常显示，并验证等待网络时停止启动器不会遗留管理进程；无需操作用户桌面。
- `tests/quiet_nested_command.py`：验证真实 PowerShell 执行器调用 CMD，以及显式隐藏启动的后台助手没有可见控制台。

安装失败会显示具体错误，不把仅完成下载或组件解压称为已接通。原交互版已在第一台学生电脑验证跨网络管理员 PowerShell、截图与安装软件。常驻版的学生机登录自启动仍需在线后实际验收。

## 官方来源

- https://tailscale.com/docs/install/windows/msi
- https://tailscale.com/docs/how-to/run-unattended
- https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks
- https://tailscale.com/docs/features/access-control/auth-keys
- https://tailscale.com/pricing
- https://github.com/CursorTouch/Windows-MCP/tree/v0.8.8
- https://docs.astral.sh/uv/concepts/python-versions/
- https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json
