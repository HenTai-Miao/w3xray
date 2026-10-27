> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# target 5 — 魔兽争霸3修改器_new.exe 静态功能审计

样本为 x86 易语言原生程序，带 MFC/运行库，PE 版本声明 `1.5.2.1`，应用标题声明“新版魔兽争霸3修改器 1.521”。已用官方 UPX 5.2.1 静态解包到另一个文件。没有运行原样本、派生 EXE、嵌入 DLL/载荷或字节码，没有注入、写入游戏或解密平台算法。

原始 SHA-256：`8d6189762b0b5cf8789629f95e206be1882d7e9d6d3be972bed01ddd35dadba1`，300,544 字节。派生 SHA-256：`bd358aca526d454727b62df9cc66fbf28e47133b71b89657e20ee270781d4170`，778,240 字节。分析前后原文件 SHA-256、长度、创建时间、最后写入时间均一致；完整校验在 identity_verification.json (`audit://target-5/identity_verification.json`)。访问时间及 ACL 未作前后独立证明。

## 实际界面与实现链

序列化应用窗体表声明一个窗体、35 个对象、15 项事件，整个声明 blob 已解析到结束边界。可见表格是 `0x16010b69`，数据源是 `0x16010b6b`，提供者是 `0x16010b6a`，三者分开记账。下表中的 RVA/文件偏移均属于派生 PE；其代码区恰好一一对应。代码地址是审计证据位置，不是游戏写入配方。

| 功能 | 静态证明及限制 | 入口/关键证据 | 类别 |
|---|---|---|---|
| 查找游戏 / game discovery | 按 Warcraft III 窗口取一个 PID，枚举其 game.dll 并读版本；没有显式多实例选择 UI。 | 0xbd94 / 控件 0x160104d3 | read_game_process |
| 11 个精确版本分支 | 11 个精确历史版本字符串比较，最晚 1.26.0.6401；不等于当前实测兼容。 | 0x1437 | version_dispatch |
| 未知版本的 config.ini 读取与默认值写入 | 读/补默认 INI，但随后绕过正常 setup；非空配置还可能留下乐观支持文案。 | 0x1f1c | read_and_write_trainer_configuration |
| 12 玩家资源选择与四种当前值 | 构造 12 玩家地址表，当前组合框选项驱动四资源读取。 | 0x303a / 控件 0x16010de6 | read_game_memory |
| 修改并锁定：金钱 | 独立输入框、去重/加入锁定项并调用 WriteProcessMemory。 | 0xbde8 / 控件 0x16010deb | write_game_memory |
| 修改并锁定：木材 | 独立输入框、去重/加入锁定项并调用 WriteProcessMemory。 | 0xb8b0 / 控件 0x16010df5 | write_game_memory |
| 修改并锁定：当前人口 | 独立输入框、去重/加入锁定项并调用 WriteProcessMemory。 | 0xb3ea / 控件 0x16010df7 | write_game_memory |
| 修改并锁定：最大人口 | 独立输入框、去重/加入锁定项并调用 WriteProcessMemory。 | 0xaf18 / 控件 0x16010df8 | write_game_memory |
| 300ms 资源刷新与持续锁定 | 静态 Timer 为 300ms；按列表当前项数逐条回写锁定资源。实际节拍未测。 | 0x9252c / 控件 0x16010e09 | periodic_read_and_write_game_memory |
| 双击删除资源锁定 | 列表事件 -3 指向删除当前锁定行的处理函数。 | 0x38c3 / 控件 0x16010e07 | modify_trainer_state |
| 列出游戏当前选中集合 | 按游戏选择管理器声明 count 遍历选中集合，再由工具列表选一条；不是全图单位遍历。 | 0x3484 / 控件 0x16010b75 | read_game_memory |
| 69 行选中单位属性读取 | 57 个展开属性行 + 六物品槽各名称/数量，共 69 行，逐字段已有读链。 | 0x53cb / 控件 0x16010b75 | read_game_memory |
| 技能与物品所谓名称实际为 FourCC | 界面称名称，实际四字节读取后反序显示；没有证明本地化名称查询。 | 0x3759 | read_and_display_raw_code |
| 编辑目标属性及类型标记 | 按类型规范化目标文本，与当前值比较并标记变更。 | 0x3952 / 控件 0x16010b69 | modify_trainer_state |
| 空目标单元格填入当前值 | 在指定行列、空目标条件下把当前值复制到目标单元格。 | 0x10a1 / 控件 0x16010b69 | modify_trainer_state |
| 修改选中单位目标字段 | 遍历全部属性行，对变更标记的整数/浮点/四码字段走 WPM；不证明游戏语义成功。 | 0xc2ae / 控件 0x16011039 | write_game_memory |
| 刷新与切换页重取 | 清理目标格并重新发现/刷新；页签切换调用相同刷新入口。 | 0x1234 / 控件 0x16011032 | read_game_and_modify_trainer_state |
| 作者网站链接 | 内嵌作者链接；未激活，不推断在线授权或更新。 | 0x923ca / 控件 0x160104d5 | open_external_url_if_activated |

完整机器可读记录（每项控件、事件、VA/RVA/文件偏移、效果类别、置信度、未知）在 features.json (`audit://target-5/features.json`)。控件完整表与绑定证明在 ui_versions.md (`audit://target-5/ui_versions.md`) / ui_controls.json (`audit://target-5/ui_controls.json`)。

## 69 字段的范围与准确含义

HP/MP 各最大值、当前值、回复率；经验值与力量/敏捷/智力；攻击速度、主动攻击范围；两组攻击各 12 项（倍乘、骰子、两个基础、丢失因子、音效、种类、最大目标、间隔、首次延时、范围、范围缓冲）；移动速度、防御力、护甲种类、X/Y；五组技能各名称/可学/要求；可用技能点；六物品槽各名称与数量。

全部 69 行的初始化、读取区间、类型和 API 链在 readfields.md (`audit://target-5/readfields.md`) / readfields.json (`audit://target-5/readfields.json`)。读取函数为 RVA `0x53d7`，初始化为 `0x3d1a`；选择集合读取为 `0x3484`。所谓技能/物品名称在此实现里是 FourCC。不能把这些字段写入推演为已证明的“生成物品、添加技能、无 CD、正确升级、实时伤害重算或安全传送”。

资源与属性读写链经内存类虚表闭环：整数读取 `+0xc → RVA 0xc868 → 动态 API 8`，四码读取 `+0x10 → 0xc8e6 → API 9`，浮点读取 `+0x48 → 0xd4ce → API 9`；三类写入分别经 `+0x1c/+0x20/+0x24 → API 11/12/13`。动态 API 名称表从 RVA `0x8e760` 起，分派 `0x110d4 → 0x328b0 → 0x32890 → 0x2a7b0`，解析至 ReadProcessMemory / WriteProcessMemory。完整 19 声明 API 与 30 方法表在 bindings.json (`audit://target-5/bindings.json`)。

## 支持文案与配置分支缺陷

未知版本读取配置后，两种 key 状态都经 RVA `0x1fa9` 跳至 cleanup `0x2073`，绕过正常 setup `0x1fae`。而“完全支持”先于版本检查拼接，仅空资源 key 会改成“不支持”。因此非空配置可能显示支持但未执行正常初始化；不能把 INI 当作支持任意版本的已证路径。配置的空键还会被写入历史默认值，本次未执行该逻辑。

## 对 GameXRay 的可用部分

1. 扩展只读 `selected_units[]`：保留游戏整个选中集合，让用户在探针里挑选实例。当前 `selected_unit()` 找到第一个可解析成员即返回，扩展应沿仓库已验证的句柄/世代/进程身份校验。
2. 增加带类型和出处的只读单位详情视图：69 行是一个明确候选清单。逐个版本验证字段，区分读失败与数值零，并保留地址、原始值、类型和不确定性。
3. 将技能、物品、单位 FourCC 接到现有分类对象/字段/名称索引；保留四字节大小写、类别碰撞和源新鲜度。
4. 把 11 个历史版本分支作为 profile 研究证据来源；未经指纹与当前进程实测不可升级为已支持版本。
5. GameXRay 继续只读；不迁移修改、锁定、全权限 OpenProcess、调试权限调整、保护修改或代码写入逻辑。

## 覆盖与保留的未知

原始和派生文件均以不重叠区间完整覆盖，均无 overlay。55 资源叶已保留原始字节与哈希：10 个 Dialog、2 个 Menu、11 个 String block 完整解码，6 个图像组引用解码，其余 22 个图像载荷、3 个 TEXTINCLUDE 和版本记录都有清单。打印、数据库和密码对话框属于链接运行库模板；没有从模板或通用 API 名字自动认定修改器功能。

派生 `.text` 577,536 字节完成线性解码，其中 577,530 字节可解码、6 字节 skipdata、无遗漏；2,144 个静态函数候选及 1,540 条未解析间接调用/跳转/边界记录全部保留。线性解码不是全程序语义证明。71 个应用 prologue、已恢复的 15 项应用事件和所有 69 字段路径分别记账。30 方法内存类还链接了扫描、查询、保护和代码写入辅助，但没有恢复到应用 UI 的路径，不将它们称为可见隐藏功能。

未在恢复的应用窗体和聚焦应用代码中建立地图提取、存档修改、迷雾、全局快捷键、在线授权、自动更新或日志产品功能的实现链。运行库间接行为仍是未知。没有运行期成功、当前游戏兼容性或网络行为证据。完整区段/资源/code/overlay 账本见 coverage.json (`audit://target-5/coverage.json`)，完整反汇编见 full_disassembly.txt (`audit://target-5/code/full_disassembly.txt`)。
