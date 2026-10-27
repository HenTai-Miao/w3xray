> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# War3ReforgedHotkeys v2.0.0 — 只读静态功能审计

目标：`C:\Users\zhong\Downloads\War3ReforgedHotkeys-v2.0.0.exe`。SHA-256：`96918355fd386afb7eabae8286e0a552c7dcbc81a239bc35e165fdc75529af41`。文件大小 18,607,643 字节，PE32+ x64；PE/APP_VERSION 均声明 2.0.0。

本报告没有启动 EXE，没有导入/执行目标 Python 字节码，没有加载目标 DLL，没有连接游戏、注入、发键、写游戏或运行自检。REA MCP 在会话中不可用，证据来自本地受信任的 PyInstaller/pefile、匹配的 CPython 3.12 marshal/dis，以及隔离安装的 PyPI Capstone 5.0.3。

## 首要结论

这是 WFE 风格格位配置 + 外部输入辅助 + 游戏内原生桥接工具，不是纯外部按键替换器。42格位编辑、SmartCast、自身施法、自动施法开关、连点、锁鼠和滚轮相机均有实现链；其中游戏格位和原生键位表路径会装载 DLL、挂游戏线程钩子并执行游戏函数。ready/context/selection/readback 等查询入口也经过同一桥接准备。

可以独立重做用于 GameXRay 的是更强的进程身份绑定、构建档案校验、纯被动注册元数据解析、配置校验/迁移、机器可读诊断和主线程队列交付。现成 NativeFrameBridge/transport 与 GameXRay 的 RPM/PrintWindow 只读边界不兼容。GameXRay 已有后台探针主线程轮询和路径身份检查；这里只提出可补强点，没有实现改动。

## 覆盖与证据

| 层级 | 完整结果 | 证据文件 |
|---|---:|---|
| CArchive | 1,148成员，全部提取并逐项SHA256，声明长度全部相符 | `carchive-complete.json` / `asset-ledger.json` |
| PYZ | 622条，其中3条仅namespace | `pyz-inventory.json` |
| base_library.zip | 155个pyc，全部header/marshal/dis读取 | `zip-inventory.json` |
| Python | 787非空模块，21,139 codeobject，0解码错误 | `coverage-modules.json` / `coverage-codeobjects.json` |
| 第一方 | 7模块、278个嵌套codeobject全部指令留档 | `bytecode/*.json`、`*.dis.txt`、`coverage-review.json` |
| PE支持件 | 76嵌入PE + 外层EXE，全部导入/导出/节/资源/版本清单 | `pe-inventory.json` |
| 第一方3DLL | 45,098代码段字节全部线性反汇编，pdata范围21/21/6 | `native/*.json`、`*.asm.txt` |
| 其他资产 | 923 Tcl/Tk文件、129发行元数据文件、2图片、2版本档案等全部列出 | `asset-ledger.json` |

标准库406模块、第三方363模块、PyInstaller运行件11、第一方7；3个空namespace另列。`fully_disassembled`指所有编码指令被读取，不代表执行覆盖、动态可达性、已恢复所有间接目标或原始源码。原生线性反汇编也不构成完全函数边界证明。

## 第一方模块逐项范围

| 模块 | 编码codeobject数 | 内容 |
|---|---:|---|
| `war3_hotkey_tool` | 56 | GUI、CLI入口、配置编辑、语言、诊断和队列交付 |
| `war3_hotkey_model` | 35 | 键名/配置数据模型、默认值、校验、迁移、持久化、本地化词典 |
| `war3_hotkey_engine` | 75 | Windows窗口保护、低级输入钩子、动作计划、四线程调度、相机/连点/SmartCast |
| `war3_hotkey_adapters` | 16 | 游戏构建身份、TLS/注册链元数据、精确版本档案和函数校验 |
| `war3_hotkey_native` | 62 | 被动内存读器/扫描器、NativeFrameBridge业务操作及legacy IPC |
| `war3_hotkey_transport` | 25 | 远端装载/映射、IAT、hook消息交付、回调/故障/清理/重试合同 |
| `war3_hotkey_transport_context` | 9 | ContextVar会话范围、profile摘要、wire header校验、派发前身份复核 |

每个nested对象的qualname、source line、code_path、局部变量、co_names、完整常量、逐指令bytecode offset、分支/异常表均在`bytecode/<module>.json`。完整278行导航见`module-audit.md`。

## 界面与配置合同

三页由 Tk/ttk 创建；窗口默认1220×790，最小1060×700；顶部状态圆点/语言/启用；方案栏新建/复制/删除/保存；按键页四组格位各含按键捕获按钮和⚡SmartCast按钮。鼠标页五个功能勾选框、三个延时输入、两修饰符选择、暂停/锁鼠热键；相机区一个总开关、三修饰符、旋转/倾角各上下键。设置页语言、启动启用、覆盖技能键、四组总开关、六项诊断和刷新。完整控件→变量→callback→提交时机在`ui-inventory.json`，没有固定数量采样。

默认配置：enabled/enforce_hotkeys/pause_in_chat/4组均True；SmartCast 28ms，连发90ms，右键80ms；自身施法Ctrl、自动施法Shift、锁鼠/右键/相机均关闭；暂停Ctrl+F12，锁鼠Ctrl+F10；相机距离Ctrl、旋转Alt（Delete/Insert）、倾角Shift（PageUp/PageDown）。技能键`M S H A D F G T Q W E R`，物品`1..6`，技能书/商店`Q W E R A S D F Z X C V`。完整42条默认记录和数据校验见`config-contract.json`。

所有非即时控件需保存并应用；退出不会重新采集尚未保存的控件值。配置路径是`%APPDATA%/Twomengxi/War3ReforgedHotkeys/config.json`；保存`config.tmp`后replace，损坏备份`config.invalid.json`（固定名字）；运行诊断`runtime-status.json`，异常日志`hotkey-tool.log`。没有发现Windows开机启动注册。

## 完整功能→实现→效果→GameXRay适用性

每行编号可在`features.json`找到完整有序调用链、qualname、源代码行、bytecode位置范围、字节码哈希、confidence与unknown。源代码行来自codeobject调试信息，不表示原始.py源文件已恢复。

| ID | 功能与实际行为 | 效果 | GameXRay判断 |
|---|---|---|---|
| `ui_localization` | **中英双语界面和系统语言选择**：Tk/ttk 三页界面（按键、鼠标与相机、设置）；语言 auto/zh/en，系统 Windows locale 以 zh 前缀判中文；切换即时重标注且保存。 | tool_ui, local_config_write | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `profiles` | **配置方案的新建、复制、删除、选择**：新建默认方案；复制当前已保存的 dataclass 深拷贝；删除需确认且至少保留1份；选择后保存 active_profile 并交给引擎。 | tool_ui, local_config_write, engine_profile_change | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `enabled` | **启用、启动后启用、保存并应用**：enabled 两个界面控件共享一个变量；切换即保存并 apply_profile。其他控件主要由保存并应用转换、校验、保存后交给引擎；close 保存 config，并不重新采集未保存控件。 | local_config_write, engine_profile_change, native_game_hotkey_write_independent_of_enabled | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `slot_editor` | **42 个格位的按键捕获**：每格位独立捕获键；运行时经低级钩子抓物理键，GUI以事件队列收结果；无钩子时用 Tk KeyPress/Button-2。Esc取消；键盘支持修饰组合，鼠标捕获支持侧键/中键。 | tool_ui, global_input_observation_when_engine_running | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `key_parser` | **键名解析、别名与修饰组合**：KeyStroke 冻结数据模型，CTRL/ALT/SHIFT/WIN 顺序规范化；声明字母、数字、F1-F24、导航、NUM、标点、Mouse4/Mouse5/Middle及多种别名；空值、多主键、未知键、禁用鼠标处抛 KeyParseError。 | pure_data_validation | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `conflicts` | **分组内重复触发键检查**：按 (group,完整 KeyStroke) 分组，只计 enabled 绑定和启用组，错误指出重复键。引擎匹配对修饰符采用子集判断，优先排序修饰符较多的绑定。 | pure_data_validation | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `contexts` | **技能/技能书/商店上下文切换**：命令栏 submenu_active 为真选 spellbook，否则 neutral_selected 选 shop，否则 ability；item 绑定在任一命令上下文均候选。 | process_memory_read, game_dll_loading, game_thread_hook, game_native_calls | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `window_guard` | **游戏窗口发现、PID 和焦点保护**：EnumWindows 可见窗口→窗口PID→QueryFullProcessImageNameW；只接受文件名 warcraft iii.exe（不区分大小写）；偏向当前前台匹配项，无前台匹配时取枚举首项；转换客户区屏幕边界。 | windows_window_query, process_path_query | 可独立重做被动读取部分；单独审计权限、身份、完整性边界；不调用桥接 |
| `chat_pause` | **Enter/Esc 聊天规避**：游戏前台、game_ready、pause_in_chat 时，首次 Enter keydown 翻转本地 _chat_mode，Esc keydown清除。聊天状态禁止绑定、连点、鼠标锁等维护动作。 | global_input_observation, tool_ephemeral_state | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `suspend` | **暂停/恢复与鼠标锁切换热键**：仅游戏前台且对局ready时处理；按下边沿切换，按键抬起清除toggle_down；暂停清除repeat_due；关闭锁鼠立即释放ClipCursor。 | global_input_observation, input_suppression, tool_ephemeral_state | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `smartcast` | **每格 SmartCast**：按钮只改UI变量直到保存；同键pass-through场景先让原键进入游戏，再延时左键；其他格位先原生 frame click，延时后鼠标当前位置左键。 | game_frame_click, sendinput_mouse, game_dll_loading | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `self_cast` | **自身施法辅助**：当前修饰符包含self_cast_modifier且该修饰符不属于绑定本身时，先点格位，延时再原生点击 portrait origin frame(16,0)。 | game_frame_click, game_dll_loading | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `autocast` | **游戏自动施法开关辅助**：仅ability组，额外修饰符激活；按12格的归一化固定布局估算屏幕点，释放当前修饰符、移动鼠标、右键、恢复鼠标与修饰符。 | cursor_move, sendinput_mouse, temporary_modifier_release | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `hold_repeat` | **按住绑定连发（模型/引擎具备，UI未露出单格开关）**：绑定被吞键并登记active时，maintenance按单调时钟调度，松开移除；每次按当前修饰符重新plan动作。 | repeated_game_frame_click, global_input_observation, game_dll_loading | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `right_repeat` | **按住右键连续点击**：物理右键down/up更新状态；前台、ready、启用、非聊天/非暂停时维护线程入队 right_click，串行线程SendInput。 | global_input_observation, sendinput_mouse | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `mouse_lock` | **前台客户区鼠标锁定**：维护线程在完整启用条件下根据GetClientRect/ClientToScreen构造RECT并ClipCursor；失焦、暂停、聊天、关闭时释放。 | cursor_clip | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `wheel_camera` | **滚轮组合控制距离/旋转/倾角**：默认Ctrl+wheel距离（释放Ctrl后重新发wheel）；Alt+wheel发送Delete/Insert用于旋转；Shift+wheel发送PageUp/PageDown用于倾角；优先级旋转→倾角→距离。 | global_input_observation, input_suppression, sendinput_keyboard, sendinput_wheel | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `input_safety` | **低级输入钩子、串行发输入和递归规避**：WH_KEYBOARD_LL/WH_MOUSE_LL 钩子；忽略系统INJECTED标志和自身dwExtraInfo标记；维护physical modifiers；阻断匹配键的down/up；动作由单独队列串行线程执行；SendInput前检查游戏前台并核对发出数量。 | global_input_observation, input_suppression, sendinput | 输入效果，与游戏内存写/注入分别记录；不属于当前 GameXRay 只读探针职责 |
| `hotkey_override` | **直接覆盖并保存游戏12格技能键**：把ability的12个source编码为(row,column,vk,modifier bits)，12个OP4写键/quickcast/hero_only，最后SAVE标志调用save_hotkeys，再OP5启用覆盖并刷新command bar。 | game_memory_write_via_game_functions, game_persistent_hotkey_save, game_dll_loading, game_thread_hook | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `readback` | **原生12格键位读回**：OP8调用选定profile的getter读取3×4表，逐格解码并与当前native_ability_hotkeys比较，native自检仅匹配后确认。 | game_native_getter_call, game_dll_loading, game_thread_hook, remote_memory_allocation_and_write | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `game_readiness` | **对局ready判定**：在游戏窗口线程回调 GetLocalPlayer，非空才视为已进入本地对局；有确定native错误时状态独立显示。 | game_native_call, game_dll_loading, game_thread_hook, remote_memory_write | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `session_identity` | **按进程出生时间与构建身份绑定缓存**：读取GetProcessTimes创建时间、主模块base、进程内MZ/PE头；与磁盘machine/timestamp/SizeOfImage核对，读取四段FileVersion；身份key=(pid,created,base,fingerprint)。缓存按key，清同PID旧项；dispatch再次核对。 | process_metadata_query, process_memory_read, disk_pe_read | 可独立重做被动读取部分；单独审计权限、身份、完整性边界；不调用桥接 |
| `version_profiles` | **精确版本档案与拒用旧地址**：包内仅2份schema1、bridge_protocol4档案：3.0.0.24268与3.0.1.24323；按machine/timestamp/image_size唯一选档案，bridge文件名白名单；无档案时非x64或major>=3拒绝。x64且major<3才走legacy解析。 | local_profile_json_read, process_identity_query | 可独立重做被动读取部分；单独审计权限、身份、完整性边界；不调用桥接 |
| `native_registry` | **TLS和Native注册表元数据解析**：选profile时读取窗口所属线程TEB/TLS索引/注册链，核对native名称、签名、handler记录和可执行/已声明受保护地址；缓存同注册上下文复用。legacy则按UnitAddAbility锚点和记录布局扫描。 | process_memory_read, local_windows_api_query, local_os_code_inspection | 可独立重做被动读取部分；单独审计权限、身份、完整性边界；不调用桥接 |
| `command_bar_resolution` | **命令栏函数/字段定位与代码校验**：profile函数RVA与完整预设校验字节比对；读取失败可defer到桥，字节不匹配则拒绝。override_enable只能接受唯一代码引用且可写region；legacy通过多个固定pattern和字段一致性证据定位。 | process_memory_read, code_pattern_analysis | 可独立重做被动读取部分；单独审计权限、身份、完整性边界；不调用桥接 |
| `wire_protocol` | **固定ABI和完整返回块校验**：magic=0x4b485257、version4，header32字节+最多16×48字节=800；选择查询占3个操作记录；检查操作范围1..13、count和返回长度/status/error/kind。profile与桥另有独立ABI marker和生命周期marker。 | local_binary_validation, remote_command_payload | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `current_transport` | **当前引擎远端装载/映射和线程回调**：验证窗口PID/TID和进程identity，验证桥导出ABI；以0x43a权限打开进程，优先远端LoadLibraryW，失败时SEC_IMAGE映射、IAT逐槽绑定与保护恢复；远端BridgeInstall安装指定游戏窗口线程hook，随机消息+nonce交付，采回回调和故障信息，再卸载清理。 | game_dll_loading, remote_memory_allocation_and_write, temporary_iat_protection_changes, create_remote_thread, game_thread_hook, game_native_call | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `legacy_transport` | **legacy DLL钩子和临时命令文件**：在工具进程LoadLibraryW native_helper并取hook导出，以WH_CALLWNDPROC挂到游戏线程；写%TEMP%/war3_hotkey_native_<pid>.bin，WM_NULL唤醒，轮询同800字节命令块；关闭unhook/FreeLibrary。 | local_target_dll_load_if_run, game_dll_loading, game_thread_hook, temporary_ipc_file_write, game_native_call | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `cleanup_quarantine` | **清理确认、错误归因与禁止不确定重放**：要求回调TID匹配且count=1，query_stage完成且无异常，active=0、hook脱离、unwind移除、线程完成、镜像卸载与分配释放才判safe；不确定保留资源并隔离当前session。仅证明业务回调未执行且clean的特定安装失败允许另一路重试。 | remote_cleanup, tool_diagnostics, session_quarantine | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `threading` | **后台线程与Tk主线程轮询交付**：GUI异步启动engine；engine创建hooks/actions/maintenance/native四个daemon线程；状态/错误/捕获入SimpleQueue，GUI_poll用after拉取（初始化120ms，后350ms），无后台Tk写入。停止发WM_QUIT、入队None、join、释放ClipCursor/bridge。 | tool_background_threads, tool_ui | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `status` | **运行诊断和机器可读快照**：显示进程PID、前台、客户区、钩子、对局、native error；runtime-status.json记录软件版本、游戏身份、桥文件、transport一致性、callback、安全清理和input_stats；内容未变化则不写，用临时文件替换且磁盘失败静默保留运行。 | tool_ui, local_status_json_write, process_window_query | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `config_store` | **AppData配置与损坏恢复**：%APPDATA%/Twomengxi/War3ReforgedHotkeys/config.json（无APPDATA时Path.home）；配置校验后asdict→UTF-8 JSON→config.tmp→os.replace；载入损坏时尽力原样copy到config.invalid.json并退回默认。 | local_config_read, local_config_write, invalid_config_backup_write | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `migration` | **旧版binding分组迁移与默认格位补全**：command→ability、inventory→item；重建旧binding_id前缀，保留可识别绑定并补齐4组格位，以固定组顺序排列；原始dict只采dataclass声明字段。 | pure_config_transform | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `exceptions` | **异常日志、错误面板和恢复重试**：未捕获异常追加hotkey-tool.log，仍调用系统原excepthook；Tk异常显示错误对话框；动作线程捕获异常统计failure，native初始化失败清ready、close并2秒后重试，同一错误不重复on_error。 | local_log_append, tool_ui, tool_diagnostics | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `cli` | **诊断CLI与自检模式**：--diagnose只做窗口发现JSON；engine自检启动完整引擎再停止；native自检读取当前配置、跑生产native loop，最多等20秒，读回验证，可--expected-game-pid和原子--diagnostic-output；--no-hooks仅GUI构造时不启动engine。 | conditional_window_query, conditional_full_engine_start, conditional_game_native_write, optional_report_write | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `single_instance` | **本地命名互斥体防重复GUI**：CreateMutexW Local\Twomengxi.War3ReforgedHotkeys；ERROR_ALREADY_EXISTS时关闭新句柄并正常退出；diagnose/自检分支在互斥体之前。manifest为asInvoker/uiAccess=false，界面提示游戏管理员运行时工具需同权限。 | windows_named_mutex, tool_process_control | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |
| `native_internal_ops` | **桥内另含未由UI暴露的诊断操作**：DLL在RVA0x2450按1..13分发。Python正常功能发1..6，自检读回发8；7为两阶段frame句柄查询，9为受块长度约束的内存复制，10为技能键设置/读回/恢复探查，11为二阶段handler/字段指针与诊断复制，12为限定函数调用后诊断复制，13为命令栏写入后字节差分探查。 | dormant_native_diagnostics, potential_game_calls_and_writes | 现成调用链不兼容当前 GameXRay 被动 RPM/PrintWindow 边界；仅协议/证据模型可借鉴 |
| `network_license` | **未发现第一方网络、升级或产品授权激活路径**：278个codeobject的IMPORT_NAME/co_names/字符串均未见HTTP/urllib/socket/webbrowser调用路径；3DLL的导入为Windows本地API。CompanyName=twomengxi.xyz为PE元数据，不是联网证据。包含网络标准库不能推导产品联网。 | bounded_negative_search | 可独立重做；仅工具自身状态/本地文件，不导入目标代码 |

## 必须保留的实现限制

1. **“关闭启用”不等于无游戏写入。** `_native_loop` L1133–1147仅用`enforce_hotkeys && enabled_groups[ability]`控制覆盖，不看enabled、chat或suspended。`engine_self_test`虽把enabled设False仍启动native线程；`native_self_test`不装低级输入钩子也不代表没有注入/游戏写入。
2. **鼠标捕获和保存路径不连通。** UI可捕获Mouse4/Mouse5/Middle，但`_profile_from_ui` L471–472写source=target，`validate_profile` L440对target使用allow_mouse=False；按现有控制流，GUI保存该鼠标绑定会失败。
3. **分组内冲突检测有限。** 不检测item与当前命令组并发、不同modifier子集、暂停/锁鼠/相机互相冲突。
4. **聊天保护是本地Enter/Esc状态机。** 没有读取游戏实际聊天输入状态。
5. **自动施法右键用固定归一化UI位置。** 自定义UI、缩放/布局、技能是否支持自动施法和施法结果未知。
6. **每格repeat/enabled和独立target只有模型字段，无可见编辑控件。** 不能说具备可视化宏编辑/录制回放；普通绑定实际执行走frame click，不按target任意发一段键序列。
7. **多游戏实例会选前台/枚举首项。** GUI没有显式选择或拒绝歧义；这一点不宜移入GameXRay。
8. **旧版扫描有经验边界。** native字符串256字节、注册链8192节点、稳定TLS等待0.3秒、legacy候选4MiB和局部扫描范围。现成代码不能满足GameXRay默认完整覆盖要求；固定游戏格位/ABI容量属于不同性质。
9. **持久化和恢复不能过度表述。** `save_hotkeys`的最终游戏配置路径未知；close没有恢复原始技能表的路径。损坏配置备份固定名称、没有fsync/跨进程锁保证。
10. **复制方案未重新load/apply。** 此回调仅复制当前已保存对象、更新列表并保存，不包含即时UI/引擎同步调用。

## 原生桥和版本证据

两份档案均schema1、adapter_version1、bridge_protocol4，精确指纹为machine/timestamp/SizeOfImage；不是exe完整哈希。3.0.0.24268指纹`(34404,1789189744,236277760)`、bridge默认`war3_hotkey_bridge.dll`；3.0.1.24323为`(34404,1790661601,236408832)`、`war3_hotkey_bridge_301.dll`。命令栏函数RVA、代码校验、TLS布局和native签名完整见`version-matrix.json`及原始JSON。对缺失档案的major>=3或非x64拒绝，只有x64且major<3允许legacy扫描；不能宣称已支持所有重制/经典版本。

发布包自己的validation字段写3.0.0 game_effect=not_run、3.0.1 physical_key_testing_pending。其他runtime_verified等文字也是发布者自述，审计没有重放验证。

业务协议是32字节header + 16×48字节OP = 800字节，magic0x4b485257，v4。操作1=frame click、2=命令上下文、3=3记录选择查询、4=写技能键、5=刷新/开关、6=GetLocalPlayer ready、8=技能表读回。DLL还含7和9–13诊断分支，完整jump table见`native-operation-dispatch.json`；未找到UI producer，不能当用户界面功能。

| DLL | 大小 | SHA256 | 静态导出 |
|---|---:|---|---|
| `war3_hotkey_bridge.dll` | 25600 | `b8beabcd314874585d1b212132ea47208138fcc23a6474f47a3b683b8135bec9` | BridgeDiagnoseLoad, BridgeDiagnoseLoadSafe, BridgeInstall, BridgeUninstall, HotkeyBridgeQuery, War3HotkeyHookProc, bridge_callback_lifecycle, bridge_callback_lifecycle_abi, bridge_fault, bridge_native_hook_abi, bridge_profile, bridge_profile_abi, bridge_recovered_faults, bridge_relocation_anchor, hotkey_adapter_abi, hotkey_bridge_abi |
| `war3_hotkey_bridge_301.dll` | 25088 | `d472bcd40d75cd7d2c1b3c3d195a679dbd510e3bc0355f1fb481d45ac2d151b7` | BridgeDiagnoseLoad, BridgeDiagnoseLoadSafe, BridgeInstall, BridgeUninstall, HotkeyBridgeQuery, War3HotkeyHookProc, bridge_callback_lifecycle, bridge_callback_lifecycle_abi, bridge_fault, bridge_native_hook_abi, bridge_profile, bridge_profile_abi, bridge_recovered_faults, bridge_relocation_anchor, hotkey_adapter_abi, hotkey_bridge_abi |
| `war3_hotkey_native_helper.dll` | 10240 | `c054c319e7d9c9f10ec8d25ce6d3943818f22a21b40f9178b4ade2d62d9dbd1a` | War3HotkeyHookProc, hotkey_adapter_abi |

`NativeFrameBridge._dispatch`的shared链先识别进程并验证窗口TID，随后transport检查本地桥ABI、远端LoadLibraryW/SEC_IMAGE、IAT和unwind状态，安装指定游戏线程hook，以随机消息/nonce回调，再读命令结果。查询也有remote allocation/write/thread/hook等准备效果；选择查询另有游戏group生命周期副作用。legacy链则加载helper、挂WH_CALLWNDPROC、写临时命令文件并WM_NULL唤醒。

清理合同检查callback TID/count、query_stage、exception、active/hook、detached、unwind、线程、镜像和分配释放。不确定资源保留并隔离session，只有业务回调未开始且清理确定的限定安装失败才尝试兼容路线。`can_release`/quarantine思想可重做；现成代码不可导入为只读工具。

## 依赖、资源、权限、网络与授权

内嵌python312.dll的PE版本为3.12.3；分析解释器是独立可信3.12.15，magic均`cb0d0d0a`。目标capstone Python包装常量为5.0.7、pefile为2024.8.26、packaging25.0、platformdirs4.9.6；Tcl/Tk、pywin32、OpenSSL和VC/UCRT支持库均逐PE盘点。dist-info另含pyreadline3 3.5.4、typeguard4.4.4、wheel0.43.0，以及17项setuptools vendored记录（发行元数据共20项）；同名vendored版本与top-level版本不合并。完整版本/依赖记录在`distribution-metadata.json`与`dependency-version-evidence.json`。

外层manifest=`asInvoker/uiAccess=false`，不是自动管理员启动器。外层EXE和三第一方DLL未见嵌入certificate security table；未验证catalog/证书信任或发布者真实性。外层PE资源12条，两个图片和所有资源ID/语言/范围/sha均保留。

全278第一方codeobject的网络符号/直接URL/导入搜索结果为0，三个第一方DLL仅本地Windows导入。PE的twomengxi.xyz不是联网调用；包内urllib/socket/http/Tcl HTTP属于支持件，不证明产品使用。未发现激活码、许可证校验、网络升级或遥测入口；这是明确边界的静态negative，不证明运行时绝无隐藏网络。

22份license文件主要属于Tcl/Tk及第三方/vendor包，原文、路径、哈希完整在`license-materials.json`。未发现第一方LICENSE/授权声明，第三方license不建立第一方代码可直接复制的授权。

## 对GameXRay的具体借鉴顺序

| 候选 | 收益与现有情况 | 必须保留的边界 |
|---|---|---|
| 进程出生时间 + base + 构建身份key | 补强当前`live_inventory.verify_opened_process`的exe路径检查 | 仅Windows查询与RPM；进程退出/身份未知分别诊断 |
| 状态JSON含版本、PID、来源、错误、完成与unknown | 使GUI/CLI报告更可追溯，避免把初始化失败误作成功 | 接自己的被动探针数据，不接NativeFrameBridge |
| 唯一版本档案 + 编码签名/字段校验 | 把适配证据与实际验收分开，并拒绝沿用旧地址 | 不复制写函数RVA或游戏native调用；完整证据保留 |
| 名称/签名/handler元数据纯RPM解析 | 仅作为未来重制版本只读探针研究线索 | 独立重写，不调用游戏函数，不照搬经验上限 |
| 配置校验/迁移/原子替换 | 清晰模型与UI转换，坏配置有证据可恢复 | 用GameXRay自己的cache隔离、确切备份，不覆盖旧用户资产 |
| UI线程队列 + 状态机 | 与GameXRay现有主线程轮询方向一致，可补重复错误抑制 | 不引入后台Tk调用，不加入额外global game hook |
| unknown/完成/清理三态与禁止不确定重放 | 可用于后台任务、探针失败和清理状态呈现 | 复用思想，注入清理机制不移植 |

游戏自动施法/SmartCast/连点/相机属于主动输入；技能表覆盖/原生frame/group调用/装载桥属于游戏执行与写入。它们可以作为产品比较信息，不能直接接入当前只读GameXRay。工具自身快捷键配置/冲突提示可重做，但应修正鼠标保存、跨组冲突等接线限制。

## 未决事项

- 本次无运行时验收，真实键盘/鼠标行为、平台补丁、权限差异、游戏效果均未知。
- 没有完整原始.py/构建工程/可复现构建或第一方license；源行是bytecode调试信息。
- native部分间接目标和诊断op11的完整业务意义未完全恢复；所有编码字节已保留，不以猜测填空。
- GameXRay重制版本适配是否值得独立实现需另立明确任务；此报告未作代码/配置修改。

## 文件索引

- `features.json`：38项功能，逐项入口/调用链/效果/置信度/限制。
- `ui-inventory.json`：全部控件、变量、callback、提交时机及隐藏模型字段。
- `config-contract.json`：静态重建默认配置、42条bindings、校验边界。
- `version-matrix.json`：两份完整版本档案及选择策略。
- `module-audit.md` / `coverage-review.json`：每个第一方nested codeobject的导航/链接和效果符号。
- `carchive-complete.json` / `pyz-inventory.json` / `zip-inventory.json` / `asset-ledger.json`：所有资产与hash。
- `coverage-modules.json` / `module-categories.json` / `coverage-codeobjects.json` / `bytecode-errors.json`：全部Python编码覆盖。
- `bytecode/*.json` / `*.dis.txt`：7个模块全部指令、异常表、常量和位置。
- `native/*.json` / `*.asm.txt` / `native-analysis-summary.json` / `native-operation-dispatch.json`：三DLL完整静态证据。
- `pe-inventory.json`：77个PE的导入/导出/节/资源/版本/签名目录。
- `first-party-imports.json` / `first-party-effect-references.json` / `network-search.json`：受边界约束的全量查询。
- `distribution-metadata.json` / `dependency-version-evidence.json` / `license-materials.json`：支持件版本与许可资料。
- `source-identity-after.json`：最终原始EXE哈希复核。
- `extract_inventory.py` / `decode_bytecode.py` / `native_static.py` / `enrich_inventory.py` / `compile_report.py`：此次静态证据生产脚本，均不执行目标代码。
