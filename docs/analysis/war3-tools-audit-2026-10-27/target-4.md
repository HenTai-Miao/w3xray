> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# 大象 1.27 修改器：只读静态审计

> **交叉复核更新：** 已从两张表单完整恢复 22 条真实序列事件，原文“原始事件表尚未恢复”已关闭。`无CD无蓝耗` 有真实 callback，但其 handler 实际读取“不会失败”控件，不能确认界面所述效果。下文初次记录中的相应旧结论由 [事件表恢复与语义冲突补充复核](target-4-crosscheck.md) 更正；原始版本已留档。完整主报告仍是 native 语义部分恢复，未声称运行验证。

原件 `C:\Users\zhong\Downloads\大象1.27修改器.exe`，1,229,162 bytes，SHA-256 `d0ea7e018a0c6480171360196f244649fb5328216ebfb94991ae1caa861964d4`。原件 SHA、大小、修改时间、inode、device 均与分析前一致；没有运行 EXE、DLL、嵌入物或生成的游戏代码。所有写出的文件只在本 target-4 证据目录。

结论：这是带 60 个选择框的易语言原生修改器，界面标题声明“魔兽争霸毁图器1.27a”。已完整恢复它声明的两张表单和所有标准资源清单，并证明多个控制分支通向游戏内存写入。对 GameXRay 的主要价值是离线审计、参数展示和界面组织的参考；没有新恢复出可直接接入的、已验证的只读游戏读取能力。精确事件分发表、完整生成载荷语义与实际游戏效果仍未恢复/验证，因此本报告明确是部分语义恢复。

## 文件、封装与结构

32 位 x86 PE，ImageBase `0x400000`，入口 RVA `0xe3240`，没有 CLR 目录。FileDescription/ProductName 为“易语言程序”，FileVersion/ProductVersion 为 `1.0.0.0`。入口以跳转垃圾包裹一个可静态还原的整数减法循环；按照入口表的 3 条记录恢复代码/数据字节，逐块前后哈希保存于 `unpack-evidence.json`。随后只用 Capstone 做静态解码，并识别常量进位分支与 call-next / 修改返回地址 / ret 的跳过垃圾模式。原始字节和静态还原副本分别保存，副本是 `.bin` 证据，不作为执行文件使用。

全部文件字节分为下列 6 个连续区域，没有漏掉 trailer：

| 区域 | 文件范围，右端不含 | bytes | 覆盖结论 |
|---|---|---:|---|
| headers | `0x0..0x1000` | 4,096 | All headers parsed and original whole-file SHA-256 checked. |
| .text | `0x1000..0xe4000` | 929,792 | Static arithmetic restoration; recursive x86 decoding plus all prolog/direct-call/data-pointer candidates. 710292 decoded-byte union out of 926228 restored code bytes. Candidate instructions are not all confirmed reachable code. |
| .rdata | `0xe4000..0x10a000` | 155,648 | 461 standard imports, 40 dynamic names, 94 vtable slots, 2 E-language forms/137 records, complete readable-string and referenced-inline-array inventories. |
| .data | `0x10a000..0x123000` | 102,400 | Static arithmetic restoration for 98808 bytes; remaining section bytes inventoried unchanged; pointer and string candidates scanned. |
| .rsrc | `0x123000..0x12c000` | 36,864 | 68 resource payloads saved and hashed, all 24 menu/dialog/string/manifest payloads format-decoded; icon/cursor/bitmap/wave/version payloads inventoried. |
| overlay | `0x12c000..0x12c16a` | 362 | 362 bytes; hashed, entropy measured; no additional validated PE image. Meaning remains unknown. |

递归解码字节并集为 710,292/926,228（76.7%）。5,854 个候选入口含数据指针误候选，51 个无效解码均保留为诊断；这不是已证明可达函数总数。应用区可确认边界的 prolog 函数档案为 297 个，两个类共 94 个 vtable 槽位，已定位 77 处类间接调用。没有把余下字节一概认作垃圾，也没有声称全程序已反编译。

## 实现证据与读写边界

动态 API 表位于 `.rdata` 文件 offset `0xe4844`，共有 40 个零基 name 指针；`0x432a9c` 按 EAX 索引调用。完整表见 `dynamic-api-table.json`，调用现场与前置指令见 `native-api-calls.json`。按唯一调用 VA 计，应用区包含：OpenProcess 5, VirtualAllocEx 1, VirtualFreeEx 1, WriteProcessMemory 3, CreateToolhelp32Snapshot 5, Process32First 3, Process32Next 4, Module32First 2, Module32Next 1。

写入不是单靠进口表推测：`0x4143c7` 从调用者参数取值，使用 `OpenProcess` 和 `WriteProcessMemory` 提交 4 字节；`0x40d318` 提交字节数组；`0x414dcd` 把文本字节表示转换后提交。三处 WPM 现场分别为 VA `0x4144d5`、`0x40d48c`、`0x414f80`。`0x416b23` 把固定表 `0x4e7ef6` 与 `0x4e8016` 写进两个实例，因而能将许多原本间接的虚方法调用连接到具体写入函数。

可复核的例子包括：瞬移控件 ID `0x160123ab` → `0x41433c` 读取 checked → `0x4143c7` → WPM；开图 ID `0x16012450` → `0x4146b8` → 同一写入函数；和平模式 ID `0x160fcb59` → `0x40e39c` → vtable `+0x44` / `0x432395` → `0x40d318` → WPM；物品无限 ID `0x160fcb5b` → `0x4110f7` → vtable `+0x10` / `0x42fd19` → 字节数组写入。每一步的调用 VA 和表项文件 offset 都在 `app-api-paths.json` / `resolved-virtual-calls.json` 中。

这些证据确认的是“对应控件状态存在静态写入/命令提交通道”。按钮名称描述的游戏效果仍依赖生成代码、游戏版本与运行状态，未用运行验证，也没有假定每一个动作都成功。原始 event→callback 表仍未恢复，表单中的 `handler_va` 全部为 null。

## 所有选择框逐项清单

完整序列表单共 137 个记录：60 选择框、14 编辑框、53 标签、2 窗口、2 组合框、1 高级选择夹、1 超级按钮、3 定时器、1 普通按钮。下表列全 60 个选择框；53 项找到独立于中央同步函数的控件读取→WPM 静态路径。完整原始字段、默认值、全部代码引用与路径均在 `features.json` 及 `forms/controls.json`，不使用输出条数上限。

| 功能/内部名 | 界面文字或热键 | 记录 offset | 已证明的实现层级 |
|---|---|---|---|
| 载入开图窗 | 载入开图窗 | `0xea2e4` | 界面及代码引用已确认，完整效果链未定 |
| 物品可以主动使用 | 最后创建的物品可以主动使用 | `0xea572` | 控件读取→写入：`0x411333` |
| 物品无限 | 全部物品无限（加载时开启） | `0xea64e` | 控件读取→写入：`0x4110f7` |
| 自残模式 | 自残模式 | `0xea722` | 控件读取→写入：`0x40ebff` |
| 和平模式 | 和平模式 | `0xea7e4` | 控件读取→写入：`0x40e39c` |
| 滑稽跑 | 滑稽跑 | `0xea8a6` | 控件读取→写入：`0x40eb55` |
| 无视人口限制 | 解除人口限制 | `0xea964` | 仅界面声明，未找到 ID 代码使用 |
| 解除技能科技限制 | 解除技能科技限制   | `0xeaa26` | 仅界面声明，未找到 ID 代码使用 |
| 物品增大 | 物品增大（加载时开启） | `0xeaaf2` | 控件读取→写入：`0x40ecac` |
| 物品无CD | 物品无CD（加载时开启） | `0xeabc2` | 控件读取→写入：`0x40eac9` |
| 无CD无蓝耗 | 无CD无蓝耗 | `0xeac92` | 仅界面声明，未找到 ID 代码使用 |
| 物品自动使用 | 最后创建的物品自动使用 | `0xead58` | 控件读取→写入：`0x40ec5a` |
| 不会失败 | 不会失败 | `0xeae2c` | 控件读取→写入：`0x40e2ad,0x40ebaa` |
| 快速建造且可以重叠 | 快速建造且可以重叠 | `0xeb10e` | 控件读取→写入：`0x40ecfe` |
| 技能全删 | Alt+J | `0xeb2bc` | 界面及代码引用已确认，完整效果链未定 |
| 无视碰撞体积 | Alt+L | `0xeb453` | 控件读取→写入：`0x4152a0` |
| 结束游戏 | Alt+H | `0xec6fe` | 控件读取→写入：`0x41699a,0x416a62` |
| 暂停单位 | Alt+F | `0xec7b5` | 控件读取→写入：`0x416813` |
| 增加经验获取率 | Alt+R | `0xec86c` | 控件读取→写入：`0x415fef` |
| 全屏叉状闪电 | Alt+S | `0xec929` | 控件读取→写入：`0x4165dc` |
| 全屏群星坠落 | Alt+A | `0xec9e4` | 控件读取→写入：`0x416514` |
| 全屏季风 | Alt+P | `0xeca9f` | 控件读取→写入：`0x41643a` |
| 全屏雷霆一击 | Alt+O | `0xecb56` | 控件读取→写入：`0x416380` |
| 全屏腐臭蜂群 | Alt+I | `0xecc11` | 界面及代码引用已确认，完整效果链未定 |
| 获得debuff | Alt+U | `0xecccc` | 控件读取→写入：`0x416253` |
| 获得buff | Alt+Y | `0xecd85` | 控件读取→写入：`0x41617a` |
| 重叠技能 | Alt+T | `0xece3c` | 控件读取→写入：`0x4160ad` |
| 暂停游戏 | Alt+G | `0xecef3` | 控件读取→写入：`0x4168d2` |
| 全屏攻击 | Alt+D | `0xecfaa` | 控件读取→写入：`0x4166b4` |
| 秒杀玩家的所有单位 | Alt+E | `0xed061` | 界面及代码引用已确认，完整效果链未定 |
| 设置属性 | Alt+Q | `0xed122` | 控件读取→写入：`0x415be1` |
| 设置技能点数 | Alt+W | `0xed1d9` | 控件读取→写入：`0x415ca1` |
| 注入脚本 | 注入灵魂 | `0xed786` | 控件读取→写入：`0x404038` |
| 创建所有物品 | Ctrl+S | `0xee017` | 控件读取→写入：`0x415b1d` |
| 得到科技 | Ctrl+O | `0xee1ab` | 控件读取→写入：`0x415a58` |
| 得到物品 | Ctrl+M | `0xee33b` | 控件读取→写入：`0x415980` |
| 呼叫增援 | Ctrl+K | `0xee4cb` | 控件读取→写入：`0x4158b7` |
| 得到6个神器 | Ctrl+numeric 3 | `0xee661` | 控件读取→写入：`0x4157f0` |
| 全被动 | Ctrl+numeric 2 | `0xee7f8` | 控件读取→写入：`0x41572d` |
| 全光环 | Ctrl+numeric 1 | `0xee98a` | 控件读取→写入：`0x415660` |
| 删除技能 | Ctrl+J | `0xeeb20` | 控件读取→写入：`0x4155a8` |
| 设置技能等级 | Ctrl+H | `0xeecb8` | 控件读取→写入：`0x4154eb` |
| 大量复制 | Ctrl+N | `0xeee4c` | 控件读取→写入：`0x415424` |
| 玩家钱木 | Ctrl+L | `0xeefe0` | 控件读取→写入：`0x41536d` |
| 获取对方控制权 | Ctrl+I | `0xef17c` | 控件读取→写入：`0x4151d9` |
| 复制单位 | Ctrl+B | `0xef312` | 控件读取→写入：`0x415108` |
| 添加技能 | Ctrl+G | `0xef70e` | 控件读取→写入：`0x41502f` |
| 丢弃背包所有物品 | Ctrl+T | `0xef8ae` | 控件读取→写入：`0x414d02` |
| 物品数量 | Ctrl+F | `0xefa46` | 控件读取→写入：`0x414c3d` |
| 设置大小 | Ctrl+P | `0xefbd6` | 控件读取→写入：`0x414b79` |
| 复制背包物品 | Ctrl+D | `0xefd6e` | 控件读取→写入：`0x414a28` |
| 复制单位给自己 | Ctrl+A | `0xeff0e` | 控件读取→写入：`0x41498a` |
| 重置CD | Ctrl+Z | `0xf00a0` | 控件读取→写入：`0x4148fa` |
| 取消无敌 | Ctrl+R | `0xf02fe` | 控件读取→写入：`0x414869` |
| 无敌 | Ctrl+E | `0xf03b6` | 控件读取→写入：`0x4147d9` |
| 关图 | End | `0xf060a` | 控件读取→写入：`0x414745` |
| 开图 | Home | `0xf06bb` | 控件读取→写入：`0x4146b8` |
| 秒杀 | Ctrl+W | `0xf0934` | 控件读取→写入：`0x414623` |
| 等级 | Ctrl+Q | `0xf0abc` | 控件读取→写入：`0x414589` |
| 瞬移 | Ctrl+X | `0xf0b70` | 控件读取→写入：`0x41433c` |

“解除人口限制”“解除技能科技限制”“无CD无蓝耗”三个控件没有找到明确 ID 字面量代码引用，保留为界面声明。“技能全删”和“秒杀玩家的所有单位”只恢复到中央状态设置引用，没有找到独立动作链。“全屏腐臭蜂群”的精确控件 getter wrapper `0x416317` 仅根据 checked 返回 1/0，函数内没有写入或后续动作调用；不能因相邻法术功能有写入而替这一项补全实现。“载入开图窗”是辅助窗口控制。“局域网开图”普通按钮在副窗存在，副窗状态更新函数包含进程查询及图状态文案；原始按钮事件归属仍未证明。buff/debuff 两个 label 的内部名和实际显示文字倒置，见 `forms/README.md`，没有替目标软件纠正或猜测。

14 个输入默认值、2 个组合框及其它辅助控件逐项在 `features.json`：等级、物品/技能/科技/增援 raw code、数量、大小、属性、经验率、重复次数等。保留 `amrc`、`AUcs`、`Rost`、`hcth`、`Apxf` 的原样大小写，不能推定为该地图的有效 ID。热键目前作为 UI 声明保存，尚未建立每条 UI 热键到 OS 注册/回调的完整所有权链。

## 资源、内嵌物与外部行为

68 个标准资源全量枚举并保存原始哈希。2 个菜单、10 个对话框（共105个控件）、11 个字符串块（含全部176槽）和1个manifest均格式解码并精确消耗，详见 `forms/standard-resources.json`。其它图标、光标、位图、wave、版本资源均有来源范围和哈希。原始和还原后的整个 PE 都扫描了 MZ/PE 结构，没有发现额外有效 PE；`War3Plugin.dll` 是代码引用的模块名字符串，没有建立它是内嵌 DLL 的证据。另有 10 个引用到的一维 byte-array 候选，头、长度、哈希、全部使用点在 `referenced-inline-arrays.json`；其中的机器码或补丁字节没有运行。362-byte overlay 的含义保持未知。

程序静态链接了较多易语言/Win32 运行时内容。数据库密码、打印菜单和框架错误字串不能直接归类为本修改器的授权、收费、数据库或打印功能。标准进口中有 socket、profile/registry/file API；目前未建立应用级网络端点、授权协议或配置/日志落盘路径。界面确有“免费”和反馈声明，只作为作者文本记录。manifest 为 `E.App` x86 / Common-Controls 6.0，未声明 requestedExecutionLevel；代码有 SeDebugPrivilege 请求与高权限 OpenProcess，不能据此说它完全不需要权限。

## 对 GameXRay 的可用性

可借鉴的是源码层面的呈现方式：把对象 raw code、数量和快捷操作放在同一面板；保留可见参数及快捷键说明；用格式解析器建立二进制表单和资源证据；以显式进程/模块身份解释版本相关能力。接入时仍须采用 GameXRay 现有的 category 与四字节身份、完整字段证据、独立缓存、窗口持久化及失败出路规范。

本工具核心是向游戏分配可执行内存并写入修改命令/代码。全图、瞬移、实体创建/复制/删除、无敌、技能/资源/属性修改等实现不属于 GameXRay 的只读读取/解析功能；不建议移植写入 helper、载荷或旧二进制。也未证明它能补充新的实时背包/坐标读取、地图 MPQ/CASC 解析、任务/物品/配方查询。

兼容性证据只到界面声明 1.27a、进程/模块名和硬编码 offset。没有找到并证明 Game.dll 文件指纹/版本校验门，也未建立多实例显式 PID 选择与冲突拒绝策略，不能把该地址表当作 GameXRay 可发布 profile。与 1.24E 工具是否同构，应比较功能和资源布局后另列；偏移表绝不能跨版本直接沿用。

## 交付与剩余未知

`features.json` 是机器可读逐项交付；`coverage-ledger.json` 是全文件区域台账；`app-dossiers.json`、`class-vtables.json`、`resolved-virtual-calls.json`、`app-api-paths.json` 是实现路径证据；`forms/README.md` 是控件格式和标准资源详报；`source-verification.json` 证明原件未变。所有复现脚本保存在同目录，不依赖修改项目的 pyproject/lock。

尚未完成的是原始易语言事件表、生成游戏载荷全部语义、全部可达 native 函数反编译、overlay 含义及运行时效果/兼容性/外部协议验证。以上未知均在 JSON 中显式记录；静态完整读取、完整 UI 清单和部分实现路径不能合并表述成“六十项全都已运行验证”。
