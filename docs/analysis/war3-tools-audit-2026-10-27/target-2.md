> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# target-2：War3ReforgedTrainer R8 静态功能审计

样本：`C:\Users\zhong\Downloads\War3ReforgedTrainer-v1.0.19-JianYX-v2.6.4-R8.exe`

SHA-256：`20098c26644bb20f2a6a846e2ca94aedbe013d5260c3c46d1d5aaa4c0ef1fd2c`
文件大小 18821684；x64 PyInstaller；CPython 312 / python312.dll。

核心结论：这是“单入口脚本 + 六模块 + 一个原生 helper”的旧版本。选中单位、资源和技能/物品字段等看似读取的活动入口，都可能前置加载 helper 并安装游戏窗口线程钩子。对 GameXRay 可借鉴字段/身份/诊断/校验设计和有出处的数据定义；当前实现不能直接认作外部被动只读组件。任何写游戏、作弊输入、钩子执行均排除。

## 边界与覆盖

本次没有运行下载 EXE、没有 import/exec/eval 目标代码对象、没有加载样本 DLL、没有连接游戏或写游戏，也没有处理平台加密算法。marshal 只用于CPython匹配版本静态解码，dis仅取指令；本地数据用base85/zlib/JSON标准解析。分析工具使用可信安装的PyInstaller、pefile和独立capstone 5.0.7，未加载样本自己的libcapstone。REA无可用MCP/provider，所以这里没有伪造REA Evidence ID。

全量：CArchive 1143成员、PYZ 615模块都逐项解压/哈希；第一方7模块、1112嵌套code对象、95769指令，零解码失败。helper COFF 384符号、103个.pdata函数range、另33个符号range、.text 119296字节全部线性解码。结构覆盖完整不等于运行覆盖：间接调用、条件可达性、游戏布局和效果未实机验证。

`coverage-ledger.json`逐一列出全部嵌套对象及完整字节码哈希、指令计数、代码路径、功能归组与限制；`native-coverage-ledger.json`列出136个原生函数range。`code/`、`dis/`保留每条指令、全部常量、异常表与所有嵌套对象；不是co_consts抽样。静态operand重建不是完整CFG证明，未建模指令在`static-operand-limitations.json`，原始指令仍完整保留。

修补后的code对象保留`<r4-repair>/<r6-repair>/<r7-repair>/<r8-repair>/<replacement>/<v262>/<r8-init>`等来源名；`code_id`中的const路径是唯一定位，不能只凭qualname或原始源码行号去重。

## 全功能分项

| ID | 功能与已观察实现 | GameXRay归类 | 核心出处 |
|---|---|---|---|
| selection | 选中单位及多选快照：活动读取入口统一走 persistent native helper；快照含完整单位身份、HP/MP/坐标/英雄属性/物品/技能，拒绝失配身份并保留来源。 | requires_passive_reimplementation | `War3Trainer._selected_candidates_snapshot@4894; War3Trainer.persistent_native_selected_snapshots@3994; War3Trainer._parse_persistent_native_snapshots@4024; PersistentNativeUnitSnapshot@766` |
| selection_probe_alias | Native/JASS定位入口的实际行为：当前 probe_native_selection_manager/probe_jass_selected_unit/locate_selected_unit_win10 都转到同一 persistent snapshot；名字并不证明另有独立被动定位策略。 | design_only | `War3Trainer.probe_native_selection_manager@10153; War3Trainer.probe_jass_selected_unit@10517; War3Trainer.locate_selected_unit_win10@10545; War3Trainer.locate_selected_unit_by_handle@10534` |
| bridge | 读取前置桥接边界：persistent_native_init 与 _run_native_helper_ops 会确保 LoadLibraryW/GetProcAddress/SetWindowsHookExW 常驻钩子，文件协议与窗口消息驱动游戏线程执行；Get* 读取不能视为外部纯被动 RPM。 | excluded_bridge | `War3Trainer.persistent_native_init@3947; War3Trainer._run_native_helper_ops@2; War3Trainer._ensure_native_helper_persistent_hook@4473; War3Trainer._run_native_helper_ops_locked@4577` |
| snapshot_fields | 单位详细字段：展示基础 HP/MP/回复率、XY、移动速度、护甲/类型、英雄等级经验、基础与总属性、成长/技能点、英雄技能栏/实例/效果类/缓存、双攻击组件、六槽背包及数量；候选只读字段明确标注。 | requires_passive_reimplementation | `War3Trainer._unit_fields_from_candidate@12028; War3Trainer._append_attack_fields@11443; War3Trainer._native_unit_field_memory@12005; UnitMemoryField@628` |
| inventory | 背包与物品身份：保存 slot/handle/item对象/rawcode镜像/ability rawcode/数量及出处地址，并检验完整六槽快照和身份；活动完整读取仍调用 helper。 | design_only | `InventoryItem@658; War3Trainer._inventory_items_from_candidate@11910; War3Trainer._native_inventory_items@11869; War3Trainer._parse_native_inventory_items@11882` |
| abilities | 技能实例与字段读取：保存 wrapper/data/vtable/tag/handle/class/rawcode/cache；按实例、效果类、字段类型与等级选择适用字段，原生 getter 经 helper 执行。 | requires_passive_reimplementation | `AbilityInstance@679; War3Trainer._ability_instances_from_candidate@11610; War3Trainer.read_selected_ability_fields@6569; War3Trainer._ability_field_context_from_candidate_locked@6386` |
| ability_catalog | 753条技能字段元数据：完整目录 44 全局字段 +709等级字段，值类型 Boolean/Integer/Real/String，包含字段名、分类、适用/不适用效果类、范围、可写标记；680条具标量/等级getter类型，679条声明可写。 | data_reference_license_review | `AbilityFieldSpec@13; AbilityFieldSpec.runtime_supported@37; ability_fields_for_effect_class@807` |
| item_fields | 20条物品字段：目录包含等级/使用次数/冷却组/最大及当前HP/优先级/护甲类型/着色/缩放/死亡掉落/可丢弃/消耗/随机/自动使用/售卖/主动使用/模型；模型字符串项未开放runtime。 | data_reference_license_review | `ItemFieldSpec@10; War3Trainer.read_selected_item_fields@6948` |
| resources | 玩家资源读取：列出28个玩家槽资源查询，含金币、木材、当前人口/上限；另保留属性组扫描、已知缓存、校准与验证路径。活动列表调用原生handler，数值合理范围只是样本自身策略。 | requires_passive_reimplementation | `War3Trainer.list_resource_caches@8689; War3Trainer._read_local_player_resources_via_native@8422; War3Trainer._resource_cache_candidates_from_group@8236; War3Trainer.validate_local_player_resource_cache@8588` |
| passive_reader | 外部内存读取底层：ProcessMemory 以 QueryInformation+VMRead打开，写模式额外申请写权限；读不到时可重试启用SeDebugPrivilege。Win10读取区分小范围精确读取与大范围容错恢复，并输出原始读取错误。 | design_only | `ProcessMemory.__init__@1407; ProcessMemory.regions@1437; ProcessMemory.read@2; Win10ProcessMemory.read@2157；其余见features.json完整evidence` |
| discovery | 保留的发现与定位代码：包含私有/映射/映像区扫描、精确native名查找、rel32调用/跳转、selection manager/list偏移探测、owner/component/index/ability布局验证以及Win10低地址可读区索引。大量旧路径仍在包内，不能据存在宣称活动入口使用它们。 | design_only | `War3Trainer._find_native_handlers_by_exact_name_scan@3652; War3Trainer._discover_native_selection_layout@10032; War3Trainer._unit_component_layout_matches_process@11124; BackupReadWar3Trainer.set_readable_pointer_regions@14052；其余见features.json完整evidence` |
| profile | native表身份与硬编码布局：嵌入1689个native名字及NATIVE_INDEX、profile_id=3736663128，另有选择/组件/物品等布局常量和历史地址；未发现新版profiles/*.json、schema导入导出或完整游戏版本PE指纹矩阵。 | reference_only_not_portable | `War3Trainer@2257` |
| limits | 样本中的完整性边界：选择manager最多64、批量selected最多12；快照能力数量超过4096直接诊断；协议每批16操作；还有扫描region窗口与合理值过滤。须与输入编码边界和分批传输区分，不能移植为GameXRay的静默枚举上限。 | design_only | `War3Trainer._parse_persistent_native_snapshots@4024; War3Trainer._selected_candidates_snapshot@4894; War3Trainer@2257` |
| window_identity | 进程与窗口选择：--pid支持显式PID；未给PID时find_war3取匹配可见窗口列表第一个。refresh_window检查窗口可用性/可见性/标题/PID后重建缓存，未见多实例拒猜或打开后exe身份复核。 | do_not_copy_weakness | `find_war3@2198; is_war3_window@2208; War3Trainer.refresh_window@2892` |
| write_unit | 单位与英雄修改：实现HP/MP/回复率/XY/移动/护甲/双攻击/等级/经验/基础力量敏捷/总智力/技能点/成长/技能栏写入及独立读回；部分字段只读、部分拒绝危险降级或不稳定路径。 | excluded_mutation | `War3Trainer._write_unit_fields_to_candidate@13645; War3Trainer._write_basic_unit_values_to_candidate@13784; War3Trainer._write_hero_skill_name_field@13122; War3Trainer.set_selected_hero_level@2；其余见features.json完整evidence` |
| write_items | 物品与背包修改：添加/替换/清空/复制/丢弃物品、设置数量、六神器、创建已加载物品、清除生成物；含完整物品/槽身份和失败清理结果。 | excluded_mutation | `War3Trainer.replace_selected_inventory_items@6261; War3Trainer._write_inventory_slot_field@13378; War3Trainer.clear_selected_unit_inventory@6176; War3Trainer.duplicate_selected_inventory_items@6185；其余见features.json完整evidence` |
| write_abilities | 技能修改及组合：添加/删除/设置等级/重置/全删能力、全光环/全被动、技能字段设置与独立读回、实例替换；修补路径记录成功/跳过/失败，native致命异常时停止后续写入。 | excluded_mutation | `War3Trainer.add_abilities_to_selected_unit@2; War3Trainer.add_ability_bundle_to_selected_unit@2; War3Trainer.set_selected_unit_ability_level@2; War3Trainer.remove_all_selected_unit_abilities@2；其余见features.json完整evidence` |
| write_item_fields | 物品字段编辑：对选中背包槽的支持Boolean/Integer/Real字段写入并检查上下文、允许范围、读回；模型字符串保留为不支持项。 | excluded_mutation | `War3Trainer.set_selected_item_field@7023; War3Trainer._coerce_item_field_value@6983` |
| write_resources | 资源与玩家修改：设置/增减/锁定金币木材、人口已用/上限；设置科技等级与经验倍率、玩家联盟和平模式。 | excluded_mutation | `War3Trainer.write_resource_cache@8728; War3Trainer.set_food@8858; War3Trainer.set_local_player_tech@7096; War3Trainer.set_local_player_xp_rate@7126；其余见features.json完整evidence` |
| write_world | 单位/地图/游戏操作：开关图、暂停恢复单位/游戏、无敌、碰撞、大小、冷却、击杀/删除/爆炸、接管、单位创建/复制/批量复制、对方全单位击杀。 | excluded_mutation | `War3Trainer.set_map_revealed@7166; War3Trainer.set_game_paused@7189; War3Trainer.set_selected_unit_invulnerable@5177; War3Trainer.create_local_unit@5813；其余见features.json完整evidence` |
| effects | 直接效果、buff与全屏技能：实现标准buff/debuff及腐臭蜂群/雷霆一击/季风/群星陨落/叉状闪电/自动特效；包含目标/点/无参/开关型能力分支、暂存/清理与回调计数。静态ack仅证明其协议/代码处理，不能确认实际游戏效果。 | excluded_mutation | `War3Trainer.apply_standard_buffs_to_selected_unit@2; War3Trainer.apply_standard_debuffs_to_selected_unit@5643; War3Trainer.cast_fullscreen_swarm@5678; War3Trainer.cast_fullscreen_starfall@2；其余见features.json完整evidence` |
| mouse_camera | 鼠标世界坐标：Python query_mouse_world_position 调用helper；DLL存在camera snapshot/lens/matrix/inverse/contains/full-depth与world-point函数，属于原生游戏线程/相机路径，不是截图OCR。 | requires_passive_reimplementation | `War3Trainer.query_mouse_world_position@5291; War3Trainer.move_selected_unit_to_mouse@5324; War3Trainer.move_selected_group_to_mouse@5328` |
| cheats | 游戏聊天作弊输入：PostMessageW逐字符发送作弊指令，含内置12项命令和raw --send-cheat；快速建造/直接胜利快捷键走此通路。 | excluded_mutation | `post_cheat@2247; War3Trainer.send_cheat@3013; run_gui.<locals>.send_cheat_command@16087` |
| locks | 周期锁定：资源/字段锁定列表、单次执行/删除锁；定时一般锁与我方锁血，执行繁忙防重入并在关闭/错误时停止。 | excluded_mutation | `run_gui.<locals>.apply_locks_once@14963; run_gui.<locals>.lock_tick@15028; run_gui.<locals>.ally_health_lock_tick@15055` |
| hotkeys | 50项全局快捷键：50项声明与50项callback一一可定位，RegisterHotKey/MOD_NOREPEAT，失败项有GetAsyncKeyState轮询替代、按键边沿去重、启停清理和日志；危险项有确认/启用控制。 | design_only | `GlobalHotkeyManager.start@348; GlobalHotkeyManager.stop@450; _factory.<locals>.worker@4; _factory.<locals>.fallback_worker@4；其余见features.json完整evidence` |
| gui | 完整Tk界面：连接/PID显示、资源、选中单位/候选/字段、锁定、技能字段、物品字段、大象功能与快捷键子页，以及物品/技能/单位ID目录、搜索/复制、筛零/未开放字段、双击选项。 | design_only | `run_gui@14135; run_gui.<locals>.build_id_catalog_tab@16319; run_gui.<locals>.refresh_ability_field_tree@15376; run_gui.<locals>.refresh_item_field_tree@15631` |
| id_catalog | 1950条离线ID目录：283物品、833技能、834单位，含四码、中英名/分类；按词匹配查找并复制ID。数据由base85+zlib封装JSON，已以标准解码完整取出，不执行目标函数。 | data_reference_license_review | `get_id_catalog@456; search_id_entries@470; War3IdEntry@27` |
| localization | 中英文切换：检测Windows/locale语言并切换静态、前缀与动态UI词条；Treeview行和既有控件可重新翻译。 | design_only | `detect_ui_language@14; translate_ui_text@1023; run_gui.<locals>.refresh_gui_language@16473; run_gui.<locals>.capture_translatable_widgets@16410` |
| hover_dictionary | 内置悬停翻译：R8新增Tk控件/Treeview文本悬停卡片，3395条六列词库；索引中文、英文、字段码/说明，在本软件控件上匹配；约0.22s驻留、120ms轮询。不是读取游戏画面的翻译。含AI辅助整理声明。 | data_reference_license_review | `run_gui.<locals>.init@10; _factory.<locals>.init.<locals>.widget_text@109; _factory.<locals>.init.<locals>.lookup@136; _factory.<locals>.init.<locals>.hover_tick@179；其余见features.json完整evidence` |
| ocr_disabled | 旧OCR实现已禁用入口：保留数字模板/分割/HPMP条解析函数，但capture_physical_screen_image直接抛出OCR/截图读取已禁用异常；活动选择只接受native快照，不能宣称有可用OCR定位。 | retained_disabled_code | `capture_physical_screen_image@1110; read_selected_panel_from_image@1366; read_selected_panel_loose_from_image@1384` |
| transport_protocol | 本地协议/事务：协议版本69、固定header/operation结构、白名单、操作数/结果长校验、PID命名mutex、常驻/批量/临时钩子路径、pending/完成状态与超时、文件写失败重试。 | design_only | `War3Trainer._pack_native_helper_command@4182; War3Trainer._parse_native_helper_results@1; War3Trainer._native_helper_transaction@4341; War3Trainer._native_helper_batch_transaction@4376；其余见features.json完整evidence` |
| async_lifecycle | 后台操作与生命周期：RLock串行化、operation_key去重、繁忙按钮、跟踪线程；关闭停止定时/快捷键、等待操作、卸钩/释放helper并清理会话。错误含结构化code/stage。 | design_only | `run_gui.<locals>.call_async@14339; run_gui.<locals>.start_operation_thread@4; _factory.<locals>.finish_close@4; War3Trainer.close@2` |
| fatal_pending | 严重错误及在途防重派：R7/R8修补记录native AV/fatal、Alt+S pending/faulted，熔断当前会话并拒绝重复派发，要求新游戏进程；callback/attempt/cleanup计数分开，不把未确认执行当成功。 | design_only | `War3Trainer._run_native_helper_ops@2; War3Trainer._run_direct_ability_over_enemy_units_locked@2; _factory.<locals>.finish@5; run_gui.<locals>.trigger_elephant_hotkey@6` |
| logging | 诊断日志：Win10ReadLogger记录PID/时间/线程/阶段/地址/读长/部分读与zero-fill、异常栈；native失败及hotkey另有prefix，archive+latest双份，旧日志保留数量128。 | design_only | `Win10ReadLogger@1691; Win10ReadLogger.__init__@1711; Win10ReadLogger.log@1764; War3Trainer._write_native_helper_failure_log@4324；其余见features.json完整evidence` |
| numeric_validation | 数值与字段验证：Decimal整数解析、有限float32往返校验、类型区分；技能/物品字段写入再检验身份与独立读回，缓存/候选语义不等同运行时生效。 | design_only | `parse_integer_number@1019; coerce_finite_float32@1039; War3Trainer._coerce_memory_value@11012; War3Trainer.set_selected_ability_field@6734；其余见features.json完整evidence` |
| selftest | 打包运行时自检入口：--runtime-self-test分支验证打包decoder来源/hash与指令边界，加载helper并输出JSON。存在加载DLL动作，因此本审计未运行此命令。 | design_only | `main@17723; run@11` |
| cli | 53个CLI参数及特殊自检分支：包含PID/status/resource list/focus/raw cheat、资源校准和修改、选中读取/字段/candidates、手动identity、probe验证、各unit字段写入、GUI强制；完整原始帮助字符串和参数在cli-declarations.json。 | design_only | `build_arg_parser@17352; run_cli@17410; main@17723` |

## 50项快捷键：全部声明与处理器

| 功能 | 声明 | 绑定处理器 |
|---|---|---|
| read_unit | Ctrl+F11  读取所有选中单位 | `run_gui.<locals>.read_unit_with_sound@15192` |
| hero_level | Ctrl+Q  英雄等级 | `run_gui.<locals>.elephant_set_hero_level@15261` |
| instant_move | Ctrl+X  瞬间移动 | `run_gui.<locals>.elephant_move_to_mouse@15908` |
| explode_unit | Ctrl+W  瞬间爆炸目标单位 | `run_gui.<locals>.<lambda>@16099` |
| reveal_map | Home  开图 | `run_gui.<locals>.<lambda>@16103` |
| hide_map | End  关图 | `run_gui.<locals>.<lambda>@16104` |
| invulnerable | Ctrl+E  无敌 | `run_gui.<locals>.<lambda>@16105` |
| vulnerable | Ctrl+R  取消无敌 | `run_gui.<locals>.<lambda>@16109` |
| reset_cooldown | Ctrl+Z  重置冷却 | `run_gui.<locals>.<lambda>@16113` |
| clone_to_self | Ctrl+A  复制单位给自己 | `run_gui.<locals>.<lambda>@16117` |
| duplicate_inventory | Ctrl+D  复制背包物品 | `run_gui.<locals>.elephant_duplicate_inventory@15822` |
| unit_scale | Ctrl+P  设置大小 | `run_gui.<locals>.elephant_set_scale@15273` |
| item_charges | Ctrl+F  物品数量 | `run_gui.<locals>.elephant_set_inventory_charges@15811` |
| drop_inventory | Ctrl+T  丢弃背包所有物品 | `run_gui.<locals>.elephant_drop_inventory@15832` |
| add_ability | Ctrl+G  添加技能 | `run_gui.<locals>.elephant_add_ability@15338` |
| clone_unit | Ctrl+B  复制单位 | `run_gui.<locals>.<lambda>@16123` |
| take_control | Ctrl+I  获取对方控制权 | `run_gui.<locals>.<lambda>@16124` |
| add_resources | Ctrl+L  增加金币木材 | `run_gui.<locals>.elephant_add_resources@15842` |
| mass_clone | Ctrl+N  大量复制 | `run_gui.<locals>.elephant_mass_clone@15847` |
| ability_level | Ctrl+H  光环/被动等级 | `run_gui.<locals>.elephant_set_ability_level@15364` |
| remove_ability | Ctrl+J  删除技能 | `run_gui.<locals>.elephant_remove_ability@15351` |
| all_auras | Ctrl+Num1  全光环 | `_factory.<locals>.elephant_add_standard_auras@4` |
| all_passives | Ctrl+Num2  全被动 | `_factory.<locals>.elephant_add_standard_passives@4` |
| six_artifacts | Ctrl+Num3  得到6个神器 | `run_gui.<locals>.elephant_add_six_artifacts@15955` |
| reinforcements | Ctrl+K  呼叫增援 | `run_gui.<locals>.elephant_create_reinforcement@16016` |
| preset_item | Ctrl+M  得到物品 | `run_gui.<locals>.elephant_add_preset_item@16023` |
| preset_tech | Ctrl+O  得到科技 | `run_gui.<locals>.elephant_set_preset_tech@16036` |
| create_all_items | Ctrl+S  创建所有物品 | `run_gui.<locals>.elephant_create_all_items@15973` |
| ignore_collision | Alt+L  无视碰撞体积 | `run_gui.<locals>.<lambda>@16139` |
| hero_attributes | Alt+Q  设置属性 | `run_gui.<locals>.elephant_set_hero_attributes@15863` |
| skill_points | Alt+W  增加技能点数 | `run_gui.<locals>.elephant_add_skill_points@15874` |
| kill_owner_units | Alt+E  秒杀玩家的所有单位 | `run_gui.<locals>.elephant_kill_owner_units@16075` |
| xp_rate | Alt+R  增加经验获取率 | `run_gui.<locals>.elephant_set_xp_rate@15806` |
| reset_ability | Alt+T  重置技能 | `run_gui.<locals>.elephant_reset_ability@15885` |
| all_debuffs | Alt+Y  获得 debuff | `run_gui.<locals>.elephant_apply_all_debuffs@15977` |
| all_buffs | Alt+U  获得 buff | `run_gui.<locals>.elephant_apply_all_buffs@15989` |
| fullscreen_swarm | Alt+I  全屏腐臭蜂群 | `run_gui.<locals>.<lambda>@16150` |
| fullscreen_clap | Alt+O  全屏雷霆一击 | `run_gui.<locals>.<lambda>@16154` |
| fullscreen_monsoon | Alt+P  全屏季风 | `run_gui.<locals>.<lambda>@16158` |
| fullscreen_starfall | Alt+A  全屏群星陨落 | `run_gui.<locals>.<lambda>@16162` |
| fullscreen_forked | Alt+S  全屏叉状闪电 | `_factory.<locals>._alts_lambda@5` |
| fullscreen_auto | Alt+D  全屏自动特效攻击 | `run_gui.<locals>.elephant_fullscreen_auto@16007` |
| toggle_unit_pause | Alt+F  暂停/恢复单位 | `run_gui.<locals>.elephant_toggle_unit_pause@16051` |
| toggle_game_pause | Alt+G  暂停/恢复游戏 | `run_gui.<locals>.elephant_toggle_game_pause@16048` |
| end_game | Alt+H  结束游戏 | `run_gui.<locals>.<lambda>@16173` |
| remove_all_abilities | Alt+J  技能全删 | `run_gui.<locals>.elephant_remove_all_abilities@15898` |
| ally_health_lock | Alt+K  我方锁血 | `run_gui.<locals>.elephant_toggle_ally_health_lock@16064` |
| allied_cooldowns | Alt+C  重置我方全部技能冷却 | `run_gui.<locals>.<lambda>@16176` |
| rapid_build | Alt+V  快速建造/研究 | `run_gui.<locals>.<lambda>@16180` |
| instant_victory | Alt+B  直接胜利 | `run_gui.<locals>.<lambda>@16184` |

快捷键数量与callback key集合逐项相等；`hotkey-features.json`保留声明bytecode offset、完整callback code身份及直接引用。快捷键标签是静态产品声明，handler字节码证明对应通路存在；未观察它们在实际游戏中的成功效果。

## 资料、版本与许可

离线ID目录：物品283、技能833、单位834，总1950。嵌入出处声明为用户单位列表、固定W3x2LNI zhCN-1.32.8快照、war3-objectdata快照；只证明包内出处声明，不证明可直接再分发。技能字段753项是完整数据，不是运行时已读到753项；680项支持的getter类型和679项可写标记也不等于每个地图/实例均有效。物品字段20项中字符串模型未开放。

翻译词库3395记录（另1表头），每条6字段：修改器界面561、技术提示84、界面与提示7、全局技能字段44、等级字段709、ID目录同名区分1990。3395不等于唯一对象数量；保留原始TSV和分类计数。悬停翻译作用于本程序Tk控件及Treeview，不读取游戏像素。

`native-name-index.json`的1689个native名及profile_id是native表身份材料。包内布局常量/历史地址不构成可移植版本矩阵；没有新版profiles JSON导入导出协议。UI作者/完全免费/防倒卖字样不能替代代码、DLL或翻译数据的许可证。应用本体和helper复用许可unknown；可借架构思路，复制分发前需另行查清授权。

## 给GameXRay的具体取舍

可借设计：值与出处地址同行、完整单位/槽/能力身份交叉检查、不可读范围诊断、零填充与有效值区分、native返回/回调/实际效果分离、读取前后身份复核、独立读回、pending状态防重派、错误stage/code、窗口关闭等待后台完成、离线字段目录带来源和适用性。若新增被动读取，只提取这些约束重新实现，继续使用现有运行缓存隔离与完整性纪律。

可参考数据：753技能字段schema、20物品字段schema、1950基础ID中英名分类、3395界面/字段术语、1689 native名字索引。需要保留源版本/分类/rawcode大小写，地图自定义数据优先，未知许可先标注，不把基础目录当地图已加载或可生成证明。

需要适配：重制版结构/组件布局、低地址读区策略、单位/背包/技能/玩家快照、鼠标世界坐标与相机模型。当前这些入口依赖hook/helper，不能复制整个读取函数进GameXRay；应用静态定义和自己的被动RPM/地图证据重做。

明确排除：修改资源/单位/物品/技能/科技、作弊聊天、全屏效果、定时锁值、实例创建/替换、任何把DLL加载或hook当读取前置的通路。也不继承first-match进程选择、经验数字上限或静默截断；GameXRay现有多实例明确选择、完整枚举、来源身份和只读边界更适合保留。

## 未观察项与未知

在七模块/1112对象的全部指令、imports、名字引用和递归字符串以及资源清单/本体helper静态范围内，未见CASC/MPQ/地图/存档解析产品流程；未见账号登录/产品激活授权/HTTP更新/遥测/远程下载通路。CPython打包的socket、http、urllib、webbrowser或native表里的存档API不能单独证明应用具有这些功能。未见锁定/历史等用户配置落盘协议。负搜索边界完整见negative-search-and-license.json，不能升级为运行时绝对不存在。

本次没有实机运行、目标自检、跨游戏版本验证、游戏效果验证。native间接分派、异常恢复在实际宿主的正确性、完整GUI条件可达性、原子快照保证、安全身份认证及版权来源链仍有未知；不以旧trainer-parity结论替代。

## 证据入口

- `features.json`：每项结论的module/qualname/唯一code_id/指令范围/哈希与限制。
- `coverage-ledger.json`、`bytecode-ledger.json`：每模块、每嵌套对象全覆盖台账。
- `carchive-full.json`、`pyz-full.json`、`identity.json`：全部成员offset/压缩长度/实际长度/哈希。
- `code/*.json`、`dis/*.txt`、`call-sites.json`、`static-calls.json`、`function-reference-graph.json`：全量字节码、常量和调用/引用候选。
- `ui-feature-index.json`、`hotkey-features.json`、`cli-declarations.json`：完整UI声明、50快捷键与53参数。
- `ability-field-catalog.json`、`item-field-catalog.json`、`unit-field-constructor-index.json`、`id-catalog-decoded.json`、`native-name-index.json`：完整字段与数据。
- `native-pe.json`、`native-coff-symbols.json`、`native-functions.json`、`native-symbol-ranges.json`、`native-disassembly.txt`、`native-text-linear.txt`、`native-call-graph.json`：原生函数与全.text静态证据。
- `validation.json`：源文件前后SHA一致、计数对账、无执行证明范围与工具身份。
