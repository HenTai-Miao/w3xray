> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

此文件是 **PE32 x86 的 Delphi/VCL Cheat Engine Trainer**，包含完整可读的训练器数据和两条 Auto Assembler 脚本。已读出全部 **28 个配置动作、37 个内存子记录、3 个实际自定义界面组件**，逐字段解析整个 39,540 字节 overlay 至文件末尾，未留下未解释的尾部字节。所有结论来自静态数据和反汇编；没有运行样本、加载其模块或操作游戏。

输入：`C:\Users\zhong\Downloads\war3 1.24E修改器V1.4by大象.exe`。SHA-256：`47a519e7cfd77c943a3f535ff5e49daf5ee7eccfb8020a1cd39df5ebd7348fa2`。大小：746,612 字节。入口 RVA：`0x93bbc`。前后 SHA-256、大小和纳秒修改时间一致，见 `identity-start.json` / `identity-end.json`。

**识别与版本**

版本资源的 InternalName 为 `Cheat Engine Trainer`；PACKAGEINFO 包含 `Trainerwithassembler`、`MemoryTrainerUnit`、`autoassembler`、`HotkeyHandler` 等单元名；四个 `TPF0` 资源均完整解析。静态恢复 209 个满足自指针/类名/实例大小约束的 Delphi VMT 候选，四张发布方法表共17方法，资源中的16事件绑定全部唯一解析。

工具标题声明 `war3 1.24E修改器V1.4by大象`；About 的游戏版本写为 **1.24E (1.24.4.6387)**、日期2010年6月19日。框架自己的 FileVersion=1.8.0.0、ProductVersion=1.2；这与工具标题的V1.4是不同层级，不能混用。Manifest 明确要求管理员权限。

主脚本注释明确说其他游戏版本需要修正游戏函数和入口绑定。训练器只按 `war3.exe` 名称枚举并取首个匹配进程；该路径没有PID选择或多实例拒绝猜测。原生框架确实有“游戏不兼容”的预期字节比较路径，但它读取的是各动作的 patch 列表；本样本28动作的 patch 列表全部为空。因此本样本没有提供可据此验证具体 Game.dll 的指纹/原字节表。声明的函数名与地址尚未通过匹配的1.24E Game.dll独立验证，不能承诺实际运行效果，也不能声称兼容其他版本。

**实际配置界面与动作**

实际窗口来自 overlay：559×669，一份 `tcheatlist` 动作列表、一个 `?` About按钮和一张装饰JPEG。三个组件完整保留于 `overlay-metadata.json`；28条动作的标签、原始快捷键词组和五个键码词均在 `overlay-records.json`。以下快捷键是证据盘点，不是使用操作指导。

| 行号 | 功能解释 | 内嵌快捷键标签 | 静态实现与边界 | 原始文件偏移 / 主脚本行 |
| --- | --- | --- | --- | --- |
| 0 | 初始化训练器/安装游戏内分派钩子 | Ctrl+numeric * | 主脚本声明可写命令区、分配代码/状态区并安装原生分派钩子；其他参数化动作依赖这条分派路径。 | `0xaca0c / 0xaca71` |
| 1 | 英雄增加等级 | Ctrl+Q | 读取首个所选单位的英雄等级，按参数逐级调用设级；属于加级，不是列出英雄或读取全体等级。 | `0xb0b60 / AA L191` |
| 2 | 所选单位移动到鼠标地图坐标 | Ctrl+X | 取得鼠标地图坐标和首个所选单位，调用 SetUnitPosition。 | `0xb0bf1 / AA L219` |
| 3 | 杀死首个所选单位 | Ctrl+W | 以首个所选单位为参数调用 KillUnit。 | `0xb0c4d / AA L232` |
| 4 | 关闭战争迷雾和黑幕 | Home | 分别请求关闭 FogEnable/FogMaskEnable。 | `0xb0ca2 / AA L240` |
| 5 | 恢复战争迷雾和黑幕 | End | 分别请求开启 FogEnable/FogMaskEnable。 | `0xb0cf2 / AA L248` |
| 6 | 所选单位设为无敌 | Ctrl+E | SetUnitInvulnerable 的布尔参数为真。 | `0xb0d42 / AA L256` |
| 7 | 取消所选单位无敌 | Ctrl+R | SetUnitInvulnerable 的布尔参数为假。 | `0xb0da9 / AA L265` |
| 8 | 重置所选单位技能冷却 | Ctrl+Z | 调用 UnitResetCoolDown；没有据此证明无限自动冷却刷新。 | `0xb0e11 / AA L274` |
| 9 | 在鼠标处创建同类型单位给本地玩家 | Ctrl+A | 从所选单位取类型ID，CreateUnitAtLoc 的所有者使用本地玩家；未复制单位完整状态。 | `0xb0e6f / AA L282` |
| 10 | 在鼠标处创建同类型单位给原所有者 | Ctrl+B | 从所选单位取类型ID和所有者，再创建新单位；未复制完整英雄等级/背包/生命等状态。 | `0xb0ed4 / AA L398` |
| 11 | 按参数数量创建同类型单位 | Ctrl+N | 以所选单位类型和所有者循环创建，数量来自输入；注释“复制10个”不等于实现固定10个。 | `0xb0f2a / AA L467` |
| 12 | 复制所选单位背包六槽的物品类型 | Ctrl+D | 枚举槽位5到0，取物品类型并在鼠标处 CreateItem；未复制充能/自定义实例状态。 | `0xb0fb6 / AA L304` |
| 13 | 移除所选单位背包六槽物品 | Ctrl+T | 槽位5到0调用 UnitRemoveItemFromSlot；具体落点/失败行为未运行核验。 | `0xb100c / AA L365` |
| 14 | 给所选单位固定六件装备 | Ctrl+Y | 先添加 AInv，随后向六槽加入固定类型：srtl四件、frhg一件、klmm一件；不是任意地图全部装备。 | `0xb1062 / AA L654` |
| 15 | 设置背包第一个槽位的物品充能 | Ctrl+F | UnitItemInSlot 的槽位参数固定为0，再调用 SetItemCharges；界面标签未提示仅第一个槽位。 | `0xb10bf / AA L348` |
| 16 | 按同一缩放参数改变单位三轴大小 | Ctrl+P | 向 SetUnitScale 传入相同数值地址三次；界面注明 Float，实际输入编码和引擎取值未运行验证。 | `0xb1152 / AA L334` |
| 17 | 按四字节代码添加技能 | Ctrl+G | 将共享技能代码做字节顺序转换，向所选单位调用 UnitAddAbility。 | `0xb11e2 / AA L385` |
| 18 | 设置所选单位指定技能等级 | Ctrl+H | 技能代码取共享字段，等级取独立输入；请求 SetUnitAbilityLevel，实际等级上限由游戏决定。 | `0xb1276 / AA L502` |
| 19 | 按共享技能代码删除技能 | Ctrl+J | 转换共享技能代码后调用 UnitRemoveAbility。 | `0xb130e / AA L517` |
| 20 | 让本地玩家获得所选单位玩家的共享控制 | Ctrl+I | 对所选单位所属玩家向本地玩家设置两种 alliance 标志；不是修改单位所属玩家。 | `0xb136d / AA L419` |
| 21 | 把12个玩家槽的金木设为各100万 | Ctrl+L | 循环玩家槽11到0，分别写两种玩家资源状态为1000000；是设值，不是增加100万或只读列出。 | `0xb13db / AA L442` |
| 22 | 添加固定八种光环技能 | Ctrl+numeric 1 | 固定八种技能 AHab、AHad、AOr2、AUau、AUav、AEar、ACac、Aoar；其中七种请求等级0x70(112)，最后一种只添加；不是枚举地图全部光环。 | `0xb1443 / AA L530` |
| 23 | 添加固定被动技能组合 | Ctrl+numeric 2 | 添加 AInv、AHbh、AOcr、Acdb；后三种请求等级0x70(112)，不是地图全部被动。 | `0xb14a5 / AA L612` |
| 24 | 强制不失败判定 | Ctrl+numeric 3 | 独立105字节AA脚本替换所声明 IsNoDefeatCheat 的实现并提供禁用段；不是整个游戏所有失败触发器均已验证失效。 | `0xb1506 / 0xb1554` |
| 25 | 按单位代码在鼠标处创建本地增援 | Ctrl+numeric 4 | 转换输入四字节类型ID，再为本地玩家在鼠标位置创建单位。 | `0xb15bd / AA L702` |
| 26 | 按物品代码在鼠标处创建物品 | Ctrl+numeric 5 | 转换输入物品类型ID，再调用 CreateItem；未直接放进所选单位背包。 | `0xb1651 / AA L724` |
| 27 | 按科技代码设置本地玩家科技等级 | Ctrl+numeric 6 | 转换科技类型ID后调用 SetPlayerTechResearched；脚本写死请求等级0x70(112)，不保证实际引擎接受该等级。 | `0xb16f2 / AA L738` |

主脚本有27个命令分派分支，其中26个有效分支对应界面动作。第17号分支“显示文字”仅 `ret`，且没有配置界面入口；不列为可用功能。另有初始化和独立 NoDefeat 动作，共28项。“全光环”实际固定8技能，“全被动”固定4技能（含物品栏），“复制单位/物品”创建同类型新对象，不能扩大解释成完整实例复制；物品充能只针对第一个槽。金木动作是对12玩家槽设值，不能当成实时读取资源的能力。

列表行事件在 RVA `0x9228c` 附近赋为 `CheatClick`（RVA `0x93618`），后者调用共用激活函数（RVA `0x8e840`）。主脚本原始数据在文件偏移 `0xaca71`，16,623字节；独立 NoDefeat 脚本105字节。两条原始脚本按原字节另存为 `scripts/*-original.bin`，UTF-8审阅件和每行原始文件偏移均保留。报告不提供修改游戏的可执行操作步骤。

资源中还捆绑 `TfrmPatcher`、`TfrmMemoryTrainer`、`TUserdefinedform`、`TfrmMain` 四个框架窗体，共22组件。`TfrmPatcher` 的占位备忘录有破坏磁盘的夸张文字，但本文件启动标记选择内存训练器路径；不能把休眠模板文字当成该样本已证实的磁盘擦除功能。资源内无菜单或加速键表，实际三组件配置也没有额外菜单。运行时生成的Win32控件ID/句柄没有在静态数据中恢复，报告以组件名和动作序号标识。

**读写、注入、文件、网络与依赖**

本工具的游戏能力属于写入：参数/命令内存写、远程可执行内存分配、原生代码钩子和游戏函数调用。动态解析已追踪26个Kernel32 API名字从 GetProcAddress 到函数槽及二级全局指针，包括读/写进程内存、进程枚举、远程分配/保护、远程线程。读写包装分别在 RVA `0x8ddd4` / `0x8de7c`，证据见 `dynamic-kernel32-apis.json` 与 `assembly/`。主界面没有单独的只读库存/属性浏览器动作。

417条静态导入、16个导入描述符已全部保留。导入DLL包括Kernel32、User32、Advapi32、OleAut32、GDI32、Version、ComCtl32、Shell32、ComDlg32、ImageHlp；额外动态DLL名和泛用VCL单元也已保留。通用框架有DLL注入相关字符串，但本样本两条脚本没有DLL文件/LoadLibrary动作，不能新增声称独立DLL注入功能。也没有把字符串中的内核驱动能力当成捆绑驱动。

配置标题、目标进程、About、快捷键和默认参数均嵌入本体；启动文件路径为空。自定义JPEG原生加载路径会取系统临时目录，生成带PID/计数器的临时文件，写出图片、加载后删除；这条文件侧效果有专门的FormCreate汇编证据。没有在已解析配置中发现专用日志文件或外置INI路径。PACKAGEINFO含Registry/IniFiles/Mapi/WinInet/UrlMon等通用单元；出现单元名本身不证明有实际邮件、网络或持久配置动作。About和版本资源带Cheat Engine网站文字，实际自定义控件没有配置网页动作。未观察网络运行，不给“无网络/安全软件”的结论。

**GameXRay 可用部分**

可以复用这份审计作为静态能力目录、四字节代码/分类检索案例、选择对象与坐标关联的研究线索。现仓库 `gametool/object_codes.py:4`、`pack_query_cli.py:3808` 已有相应的只读四码和知识包查询边界。可借鉴逐条动作溯源、完整字段/默认值保留、标签与实现区分的呈现方式。

当前 `live_inventory.py:145` 只申请查询/读取权限；`live_handle_chain.py:126` 的确证句柄链表目前仅有1.27条目，`live_handle_chain.py:169` 的1.24E公开RVA表不能由这个修改器的函数钩子声明直接升级为exact档案。`resolve_profile`（同文件354行）已有分级诊断路径。鼠标指针/原生函数位置只能作未验证线索，需要同版本、同源文件身份与新的只读观测后才能使用。全部资源/属性/技能/物品/联盟/迷雾写入、代码补丁、远程分配和钩子安装均不符合本项目现有只读边界，不应移植。

**覆盖台账**

| 区域 | RVA | 文件偏移 | 虚拟字节 | 原始字节 |
| --- | --- | --- | --- | --- |
| CODE | `0x1000` | `0x400` | 601100 | 601600 |
| DATA | `0x94000` | `0x93200` | 24464 | 24576 |
| BSS | `0x9a000` | `0x99200` | 4281 | 0 |
| .idata | `0x9c000` | `0x99200` | 9510 | 9728 |
| .tls | `0x9f000` | `0x9b800` | 16 | 0 |
| .rdata | `0xa0000` | `0x9b800` | 24 | 512 |
| .reloc | `0xa1000` | `0x9ba00` | 38044 | 38400 |
| .rsrc | `0xab000` | `0xa5000` | 30844 | 31232 |

PE头1,024字节 + 八节原始大小 + 39,540字节overlay = 全部746,612字节，物理范围无未计入空隙。53个资源叶均导出并哈希；17张字符串表272槽（264非空）均解析，剩余尾字节全部为零且原样保留。四DFM合计3,353字节，解析至各资源末尾；TLS表无回调；嵌入证书表目录为空（不等同于全面签名信誉判断）。overlay中主/独立脚本合计16,728字节、JPEG19,241字节、结构与元数据3,571字节，全部计入。

原生CODE声明601,100字节已完整线性解码并保留，原始节还含500字节填充。该节混有Delphi字符串、RTTI和跳表，线性扫描得到的指令或xref不能自动证明可达性。十段关键原生路径另从指定边界解码，覆盖启动数据定位、API解析、进程选择、UI构建、事件激活、读写和定时器。REA MCP与原生反编译provider在此代理不可用，实际工具为pefile 2024.8.26和Capstone 5.0.7；未声称每个通用库函数均已完成语义反编译。

完整机器可读结果：`features.json`；区域及问题逐项状态：`coverage-ledger.json`。核心原始证据：`resources.json`、`dfm-all.json`、`ui-resource-components.json`、`delphi-classes.json`、`overlay-records.json`、`overlay-metadata.json`、`script-main-lines.json`、`script-dispatch.json`、`native-focus.json`、`assembly/`、`scripts/`。尚未验证实际Game.dll绑定、输入转换、游戏等级限制、游戏函数返回行为和所有原生虚调用路径。没有运行任何历史目标文件。

另行完整解析了82字节的通用RT_DIALOG模板：一个静态控件ID1119，无标题/菜单；见 `win32-dialog-templates.json`。各节虚拟长度以外的原始尾部也已单独核对，CODE等尾部为零，资源节388字节是重复的PADDING字样；见 `raw-tail-and-pe-candidates.json`。全文件扫描MZ→有效PE头签名候选，没有发现除外层样本以外的有效PE签名候选；这不是对所有压缩/编码载荷的否定。

数值记法按 [Cheat Engine官方Auto Assembler文档](https://wiki.cheatengine.org/index.php?title=Cheat_Engine:Auto_Assembler#Value_Notation) 复核：无前缀数字按十六进制解释，故源脚本的70对应112；它描述请求值，未证明游戏会接受该等级。
