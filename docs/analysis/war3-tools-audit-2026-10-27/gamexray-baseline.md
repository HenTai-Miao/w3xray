> `audit://` 指向完整静态证据 ZIP 的成员；原始报告与完整数据均在 ZIP 中保留。

# GameXRay 当前功能与适配判定基线

2026-10-27；`main@ac18ec8d6e02dc36103d6c43cc0de61a0f83ab4e`；版本0.6.2。

本报告仅静态核对源码和测试锚点，不执行测试、游戏、外部EXE/DLL或提取物，不改变仓库。553个源码文件和497个测试文件已做AST元数据索引，零解析错误；不声称这等于逐字段语义穷尽。

当前基线包含 83 个可定位能力条目，其中27个是pack-query子命令；静态知识包manifest见baseline.json，脚本索引13种，提取开关10类。

## 影响适配结论的边界

- Classic 1.27.0.52240在源码中有exact档案及历史真机来源；本次未重新验证运行中游戏。其他RVA表版本和template不能算相同保障。
- Reforged/x64 resolve_profile返回reforged-pending、空RVA与空句柄链。CASC与Reforged WTG文件解析可用，不等于Reforged实时句柄链可用。
- 新实时属性/技能/装备字段即使只读，也通常需要版本布局/解析证据与真实样本验证。
- 游戏内存写入、注入、桥接执行、平台解密算法绕过、编辑游戏存档或源地图属于当前边界外；相关数据目录和界面设计仍可分别评估。
- 现有快照不是游戏原子快照；图标匹配只证明可见图像，不产生owner或世界坐标。

## 判定分类

| key | 中文 | 判定 |
|---|---|---|
| `existing` | 已具备 | 当前源码有可达入口与实现，源/测试锚点可定位；仍保留版本与输入条件。 |
| `direct_add` | 可直接新增 | 可在现有已确认只读数据或GUI/报告基础上增加，不需新游戏布局、注入或写入；这是建议，并非已实现。 |
| `adaptation_required` | 需要适配 | 目标可做成只读，但依赖新版本/架构/布局/解码器、平台或真实样本才能实现与验证。 |
| `outside_read_only_boundary` | 超出当前只读边界 | 原功能依靠写游戏/存档/地图、注入/桥接执行、模拟执行或绕平台保护；只能另取其数据/界面设计。 |
| `undetermined` | 无法判断 | 外部只见标签/字符串/未解析模块或缺少行为证据，不能从名称推断实现，也不能从未检出断言不存在。 |

## 能力索引

精确来源、SHA256、完整调用链、测试锚点及限制保存在baseline.json；以下为可扫描目录。测试锚点表示存在，不表示本次通过。

| ID | 能力 | 调用入口 | 主源码 | 测试锚点 |
|---|---|---|---|---|
| GX-ENTRY | 统一 GUI、CLI 与打包入口 | main.py -> gametool.app.main / gamexray 与 gamexray-gui | gametool/app.py:122 | tests/test_release_distribution_entrypoints.py:51 |
| GX-MAP | 静态地图与纯 Python MPQ 读取 | gamexray cli <地图> -> cli_options.run_cli -> api.load_map -> map_loader.load_map | gametool/map_loader.py:50 | tests/test_release_map_loading.py:79 |
| GX-CAMPAIGN | 战役容器与逐关共享对象 | map_loader._load_map_impl -> load_campaign_children; GUI 战役切换 | gametool/map_loader.py:82 | tests/test_campaign.py:28 |
| GX-ARCHIVE | 内部路径、匿名块与完整性证据 | archive_inventory.build_archive_inventory / archive_export.export_all_files / 知识包未知文件 | gametool/archive_inventory.py:23 | tests/test_archive_inventory.py:63 |
| GX-PROTECTION | 脚本保护识别与诊断 | script_protection.detect_encrypted_script_label / archive_diagnostics | gametool/script_protection.py:31 | tests/test_script_protection.py:26 |
| GX-OBJECTS | 八类对象与类别限定身份 | map_loader._load_map_impl -> object pipeline -> MapData / knowledge_object_exports | gametool/map_loader.py:82 | tests/test_object_pipeline.py:14 |
| GX-FIELDS | 字段元数据、继承与原始证据 | 对象编辑器查看 / 对象字段.tsv / pack-query 对象详情 | gametool/map_data.py:28 | tests/test_query_field_tables.py:107 |
| GX-TEXT | 完整对象文本与 UI 字符串 | object_text pipeline / knowledge_pack_contents -> 对象完整描述与UI文本TSV | gametool/knowledge_pack_contents.py:78 | tests/test_object_text_pipeline.py:17 |
| GX-REFERENCES | 对象引用图与孤立对象 | map_loader._load_map_impl -> build_reference_graph; GUI孤立对象/详情引用 | gametool/map_loader.py:82 | tests/test_references.py:31 |
| GX-PREPLACED | 预放置单位与装饰物完整嵌套证据 | map_loader -> _add_preplaced -> knowledge_preplaced_exports; 场景放置页 | gametool/knowledge_preplaced_exports.py:13 | tests/test_knowledge_pack_preplaced.py:18 |
| GX-WORLD | 区域、镜头、声音与地形路径网格 | map_extras.add_world_metadata / knowledge_terrain_exports.write_terrain_exports | gametool/map_extras.py:20 | tests/test_w3world.py:103 |
| GX-WTG | 经典/重制格式 GUI 触发器与 ECA | map_extras.add_trigger_summary -> parse_wtg; GUI触发器页 / 触发器ECA.tsv | gametool/map_extras.py:122 | tests/test_wtg.py:135 |
| GX-SCRIPTS | JASS/Lua 脚本与语言绑定 | script_sources.analysis_script_sources -> script scanners; 原始/可读脚本导出 | gametool/script_sources.py:164 | tests/test_script_language_context.py:39 |
| GX-INDEXES | 十三种脚本索引 | knowledge_script_index_exports.write_script_index_exports | gametool/knowledge_script_index_exports.py:55 | tests/test_knowledge_pack_script_call_catalog.py:12 |
| GX-GEOMETRY | 静态数值、位置与几何数据流 | script_placement_analysis / script_geometry -> 位置查询、区域与攻略标记 | gametool/script_geometry.py:60 | tests/test_script_geometry_complete.py:47 |
| GX-MECHANICS | 指令、订单、作弊与机制静态线索 | api.commands_from_map / gui_reports.build_analysis_blocks | gametool/api.py:125 | tests/test_cheats.py:7 |
| GX-RELATIONS | 掉落、商店、合成、奖励、装备技能关系 | map_loader._load_map_impl -> build_item_relation_index -> 掉落与获取关系.tsv / 装备技能关系.tsv | gametool/map_loader.py:82 | tests/test_item_relations.py:115 |
| GX-RESOURCES | 资源库存、引用追踪与安全导出 | knowledge_resource_exports.write_resources / archive_export / GUI资源报告 | gametool/knowledge_resource_exports.py:23 | tests/test_resources.py:23 |
| GX-ICONS | BLP 解码、图标证据与缺口 | BLP资源解码 / icon evidence / GUI图标缺口 | gametool/blp.py:51 | tests/test_icon_evidence_builder.py:42 |
| GX-CLIENT | 客户端目录、Classic MPQ 与 CASC 数据来源 | --game-data / GUI游戏数据 -> game_data_source.open_game_data_source | gametool/game_data_source.py:173 | tests/test_game_data_source.py:23 |
| GX-CASC | CASC Root 浏览与身份导出 | gamexray casc inventory/extract -> CascBrowserModel / CascLibDataSource.iter_entries | gametool/casc_cli.py:45 | tests/test_casc_inventory.py:60 |
| GX-GAMECONFIG | WGC 游戏配置只读摘要 | gamexray wgc/gameconfig <文件> / map_extras.add_game_configs | gametool/app.py:122 | tests/test_gameconfig.py:50 |
| GX-PACK | 知识包与逐文件写入/完整性状态 | gamexray cli <地图> --pack <新目录> -> write_knowledge_pack_report; GUI资料包 | gametool/knowledge_pack.py:44 | tests/test_knowledge_pack.py:21 |
| GX-PROFILE | 十类提取开关 | cli --profile / GUI提取设置 -> ExtractionProfile | gametool/extraction_profile.py:54 | tests/test_extraction_profile.py:22 |
| GX-BATCH | 递归全图批量、复用与依赖证据 | gamexray batch <目录> --output <新目录> -> batch_cli.run_batch_cli | gametool/batch_cli.py:25 | tests/test_batch_e2e.py:15 |
| GX-GUIDE | 九段玩家攻略与逐关速查 | gamexray guide <地图> [--section …] / GUI攻略速查 -> build_guide_sections | gametool/guide_report.py:98 | tests/test_guide_report.py:240 |
| GX-MINIMAP | 小地图 PNG 与静态位置标记 | guide --minimap-marks / GUI小地图 -> write_guide_minimap | gametool/guide_minimap.py:400 | tests/test_guide_minimap.py:32 |
| GX-Q-AGAIN | 包查询 again | gamexray pack-query <包> again / GUI包查询 -> execute_pack_query -> execute_query -> _query_again | gametool/pack_query_cli.py:3698 | tests/test_pack_query_cli.py:1840 |
| GX-Q-ITEM | 包查询 item | gamexray pack-query <包> item / GUI包查询 -> execute_pack_query -> execute_query -> _query_item | gametool/pack_query_cli.py:1010 | tests/test_pack_query_cli.py:1071 |
| GX-Q-RECIPE | 包查询 recipe | gamexray pack-query <包> recipe / GUI包查询 -> execute_pack_query -> execute_query -> _query_recipe_result | gametool/pack_query_cli.py:1292 | tests/test_pack_query_cli.py:1078 |
| GX-Q-WHERE | 包查询 where | gamexray pack-query <包> where / GUI包查询 -> execute_pack_query -> execute_query -> _query_where_result | gametool/pack_query_cli.py:1414 | tests/test_pack_query_cli.py:699 |
| GX-Q-DROP | 包查询 drop | gamexray pack-query <包> drop / GUI包查询 -> execute_pack_query -> execute_query -> _query_drop_result | gametool/pack_query_cli.py:2376 | tests/test_pack_query_cli.py:563 |
| GX-Q-QUEST | 包查询 quest | gamexray pack-query <包> quest / GUI包查询 -> execute_pack_query -> execute_query -> _query_quest_result | gametool/pack_query_cli.py:2482 | tests/test_pack_query_cli.py:1085 |
| GX-Q-TEXT | 包查询 text | gamexray pack-query <包> text / GUI包查询 -> execute_pack_query -> execute_query -> _query_text | gametool/pack_query_cli.py:2524 | tests/test_query_text_records.py:83 |
| GX-Q-PRICE | 包查询 price | gamexray pack-query <包> price / GUI包查询 -> execute_pack_query -> execute_query -> _query_price | gametool/pack_query_cli.py:1018 | tests/test_pack_query_cli.py:1096 |
| GX-Q-SHOP | 包查询 shop | gamexray pack-query <包> shop / GUI包查询 -> execute_pack_query -> execute_query -> _query_shop | gametool/pack_query_cli.py:1053 | tests/test_pack_query_cli.py:938 |
| GX-Q-TECH | 包查询 tech | gamexray pack-query <包> tech / GUI包查询 -> execute_pack_query -> execute_query -> _query_tech | gametool/pack_query_cli.py:600 | tests/test_pack_query_cli.py:397 |
| GX-Q-NEAR | 包查询 near | gamexray pack-query <包> near / GUI包查询 -> execute_pack_query -> execute_query -> _query_near_result | gametool/pack_query_cli.py:2981 | tests/test_pack_query_cli.py:547 |
| GX-Q-CMD | 包查询 cmd | gamexray pack-query <包> cmd / GUI包查询 -> execute_pack_query -> execute_query -> _query_cmd_result | gametool/pack_query_cli.py:3019 | tests/test_pack_query_cli.py:419 |
| GX-Q-REFS | 包查询 refs | gamexray pack-query <包> refs / GUI包查询 -> execute_pack_query -> execute_query -> _query_refs_result | gametool/pack_query_cli.py:3173 | tests/test_pack_query_cli.py:443 |
| GX-Q-LOCATE | 包查询 locate | gamexray pack-query <包> locate / GUI包查询 -> execute_pack_query -> execute_query -> _query_locate_result | gametool/pack_query_cli.py:949 | tests/test_pack_query_cli.py:997 |
| GX-Q-AFFIXES | 包查询 affixes | gamexray pack-query <包> affixes / GUI包查询 -> execute_pack_query -> execute_query -> _query_affix | gametool/pack_query_cli.py:3292 | tests/test_pack_query_affix.py:47 |
| GX-Q-REGISTERED | 包查询 registered | gamexray pack-query <包> registered / GUI包查询 -> execute_pack_query -> execute_query -> _query_registered | gametool/pack_query_cli.py:3321 | tests/test_pack_query_affix.py:47 |
| GX-Q-SEARCH | 包查询 search | gamexray pack-query <包> search / GUI包查询 -> execute_pack_query -> execute_query -> _query_search | gametool/pack_query_cli.py:3357 | tests/test_pack_query_cli.py:1233 |
| GX-Q-DIFF | 包查询 diff | gamexray pack-query <包> diff / GUI包查询 -> execute_pack_query -> execute_query -> _query_diff_result | gametool/pack_query_cli.py:3433 | tests/test_pack_query_cli.py:1257 |
| GX-Q-LIST | 包查询 list | gamexray pack-query <包> list / GUI包查询 -> execute_pack_query -> execute_query -> _query_list | gametool/pack_query_cli.py:3447 | tests/test_query_object_lists_complete.py:17 |
| GX-Q-DOC | 包查询 doc | gamexray pack-query <包> doc / GUI包查询 -> execute_pack_query -> execute_query -> _query_doc_result | gametool/pack_query_cli.py:3477 | tests/test_query_evidence_complete.py:62 |
| GX-Q-BUFFS | 包查询 buffs | gamexray pack-query <包> buffs / GUI包查询 -> execute_pack_query -> execute_query -> _query_buffs | gametool/pack_query_cli.py:3526 | tests/test_pack_query_cli.py:1296 |
| GX-Q-EXPORT | 包查询 export | gamexray pack-query <包> export / GUI包查询 -> execute_pack_query -> execute_query -> _query_export_result | gametool/pack_query_cli.py:3629 | tests/test_pack_query_cli.py:1331 |
| GX-Q-STATS | 包查询 stats | gamexray pack-query <包> stats / GUI包查询 -> execute_pack_query -> execute_query -> _query_stats | gametool/pack_query_cli.py:3554 | tests/test_pack_query_cli.py:1343 |
| GX-Q-SYNTH | 包查询 synth | gamexray pack-query <包> synth / GUI包查询 -> execute_pack_query -> execute_query -> _query_synth_result | gametool/pack_query_cli.py:1256 | tests/test_pack_query_cli.py:1498 |
| GX-Q-SKILLS | 包查询 skills | gamexray pack-query <包> skills / GUI包查询 -> execute_pack_query -> execute_query -> _query_skills | gametool/pack_query_cli.py:3549 | tests/test_pack_query_cli.py:1505 |
| GX-Q-UNITS | 包查询 units | gamexray pack-query <包> units / GUI包查询 -> execute_pack_query -> execute_query -> _query_units | gametool/pack_query_cli.py:3544 | tests/test_pack_query_cli.py:1545 |
| GX-Q-HEROES | 包查询 heroes | gamexray pack-query <包> heroes / GUI包查询 -> execute_pack_query -> execute_query -> _query_heroes | gametool/pack_query_cli.py:3530 | tests/test_pack_query_cli.py:1324 |
| GX-Q-CORE | 共享查询结果、JSON、战役与限制契约 | pack_query_cli.execute_pack_query -> pack_query_execution.execute_query -> PackQueryResult | gametool/pack_query_cli.py:3808 | tests/test_query_execution.py:43 |
| GX-CURRENT | 当前地图证据发现与歧义裁决 | gamexray current [--root] [--accept-suggestion] / GUI获取当前地图 -> locate_current_map | gametool/current_map_discovery.py:74 | tests/test_current_map_resolution.py:18 |
| GX-LIVE-READ | 被动进程快照与只读访问 | gamexray live -> live_inventory.read_live -> open_process/snapshot | gametool/live_inventory.py:134 | tests/test_release_platform_live.py:14 |
| GX-LIVE-ID | 多实例PID与打开后身份复核 | live --pid / live_inventory._read_live -> verify_opened_process | gametool/live_inventory.py:1205 | tests/test_live_profile.py:245 |
| GX-LIVE-VERSION | 版本、架构、模块与PE证据 | live_inventory.detect_version -> read_pe_fingerprint -> live_handle_chain.verify_profile | gametool/live_inventory.py:464 | tests/test_live_profile.py:127 |
| GX-LIVE-PROFILES | Classic四档版本档案 | live_handle_chain.resolve_profile / describe_live_profile | gametool/live_handle_chain.py:208 | tests/test_live_profile.py:56 |
| GX-LIVE-IMPORT | 只读档案JSON导入导出 | live --profile-json / --export-profile -> load_profile_override / profile_from_dict / profile_to_dict | gametool/live_inventory.py:415 | tests/test_live_profile.py:176 |
| GX-LIVE-DERIVE | Classic结构偏移发现与阶段诊断 | live_inventory._read_live -> live_handle_chain.derive_offsets | gametool/live_handle_chain.py:1408 | tests/test_live_handle_chain.py:223 |
| GX-LIVE-HANDLES | Classic选中单位与全部带物单位背包 | live --strategy handle/auto -> selected_unit / walk_item_units / read_inventory | gametool/live_handle_chain.py:625 | tests/test_live_handle_chain.py:193 |
| GX-LIVE-OWNERS | 全部玩家/单位/owner/坐标 | live --players --all-units --unit … -> walk_owned_units / summarize_owners | gametool/live_handle_chain.py:793 | tests/test_live_owned_units.py:26 |
| GX-LIVE-RESOURCES | 资源报数校准、自动差分与玩家标记 | live --resources <gold> <lumber>/auto [--nick …] -> find_resource_layout / find_auto_resource_rows / read_player_resources_chain | gametool/live_handle_chain.py:1025 | tests/test_live_resource_layout.py:46 |
| GX-LIVE-CHAIN | 旧物品链回退读取 | live --strategy chain/auto -> live_inventory._read_live.try_chain | gametool/live_inventory.py:1205 | tests/test_live_inventory_chain.py:15 |
| GX-LIVE-ICONS | PID窗口截图与图标匹配 | live --strategy icons / --test-image -> capture_window / match_inventory | gametool/live_inventory.py:811 | tests/test_real_session_live_icons.py:39 |
| GX-LIVE-SNAPSHOT | 快照保存与离线复查 | live --save-snapshot / --load-snapshot -> save_snapshot / load_snapshot | gametool/live_inventory.py:315 | tests/test_live_cli.py:131 |
| GX-LIVE-DUMP | 运行时SLK、注册消息与词缀对象包 | live --dump-objects <新目录> -> dump_live_objects -> write_object_pack | gametool/live_object_dump.py:447 | tests/test_live_object_dump.py:25 |
| GX-LIVE-LOGS | 探针journal、堆栈与权限诊断 | append_live_journal / log_live_exception / live --elevated-hint | gametool/live_inventory.py:1099 | tests/test_live_profile.py:505 |
| GX-SAVE-CLUES | 静态存档机制与键/对象线索 | build_save_report / 存档读写线索.tsv / GUI分析 | gametool/save_analysis.py:80 | tests/test_save_analysis.py:10 |
| GX-SAVE-CONTAINER | 真实存档文件/目录只读分析 | gamexray save --map … --save … --output … -> analyze_real_save_path -> unpack_save_container | gametool/real_save_files.py:73 | tests/test_real_save_files.py:42 |
| GX-SAVE-CODES | 知识包存/读码文本候选 | gamexray savecodes <包> -> run_save_code_cli -> extract_script_save_codes / extract_save_codes | gametool/save_code_cli.py:46 | tests/test_save_codes.py:6 |
| GX-GUI-READ | 十二工作区、对象过滤与完整详情 | App -> ShellLayoutMixin._build_tabs / GUI mixins | gametool/gui.py:48 | tests/test_gui_layout.py:14 |
| GX-GUI-QUERY | 包查询面板、历史、收藏与持久化 | GUI包查询 -> _PackQueryWindow._run_query -> execute_pack_query | gametool/gui_pack_query.py:808 | tests/test_gui_pack_query_memo.py:14 |
| GX-GUI-HANDOFF | live/攻略/查询的四码与坐标联动 | gui_topbar._open_live_probe.query -> on_pack_query; probe/context menus -> query_coordinates | gametool/gui_topbar.py:265 | tests/test_gui_live_probe.py:41 |
| GX-GUI-PROBE | 可取消独立子进程探针 | LiveProbeWindow._start -> LiveProbeChild.run -> app live CLI; _finish / destroy | gametool/gui_live_probe.py:307 | tests/test_gui_live_probe.py:41 |
| GX-GUI-WORKERS | 线程交付、地图租约与资源释放 | GuiWorkerHostMixin / GuiLifecycleMixin.on_close / MapData.close | gametool/gui_worker_host.py:110 | tests/test_gui_worker_registry.py:17 |
| GX-GUI-KEYS | 快捷键、段落跳转与文本操作 | GUI _show_hotkeys / dialog text controls | gametool/gui_topbar.py:665 | tests/test_gui_copy.py:9 |
| GX-CACHES | 外置缓存、源绑定与用户配置 | cache_root.gamexray_cache_root / live_pack_cache.complete_live_pack / gui_lifecycle._config_path | gametool/cache_root.py:18 | tests/test_release_platform_live_cache.py:44 |
| GX-INTEGRITY | 源树快照、校验与保留缓存审计 | gamexray integrity … / description-cache migrate … | gametool/integrity_cli.py:45 | tests/test_integrity_cli.py:16 |
| GX-SINGLE | GUI启动单实例生命周期 | app.main (default GUI startup) -> single_instance.ensure_single_instance | gametool/single_instance.py:182 | tests/test_single_instance.py:31 |
| GX-DEV | 发行构建、验收与隔离测试入口 | pyproject scripts -> dist_build / acceptance_cli / dev_test / quality_gate | gametool/dev_test.py:18 | tests/test_dev_test_cache_isolation.py:150 |

## 历史文档核对差异

- trainer-parity记载DERIVE_STAGES 16阶段已落地。现源DERIVE_STAGES仅5键；Classic推导已落地，Reforged16阶段是条件设计。 来源：gametool/live_handle_chain.py:1397、gametool/live_handle_chain.py:1408。
- 旧orientation称GUI后台线程直接run_live_cli。现源通过LiveProbeChild独立子进程，线程等待、主Tk轮询；Windows Job确保归属取消。 来源：gametool/gui_live_probe.py:307、gametool/gui_live_subprocess.py:215。
- 旧parity称snapshot天然免疫撕裂读数。快照读取跨区域/时序完成，仅本地解析用同一捕获；源码无游戏原子快照协议。 来源：gametool/live_inventory.py:283。
- CLI 27与GUI 26数量可能被当不一致。现源三个模式面板合计26，包含again；CLI额外有recipe，而GUI提供synth。 来源：gametool/pack_query_cli.py:113、gametool/gui_pack_query.py:162。
- 只读边界意味着整个程序无TerminateProcess。single_instance确有终止同一GameXRay映像旧实例路径；game进程open仅0x0410。 来源：gametool/single_instance.py:118、gametool/live_inventory.py:134。

## 审计产物

- baseline.json：完整机器可读能力、证据、测试、限制、目录与判定规则。
- source-index.json / test-index.json：当前全部Python文件SHA256、行数、定义和顶层声明。
- mapping-taxonomy.json：跨外部程序共享判定定义。
- 外部功能全量交叉表待六个目标features清单到齐后写入；不以标签预先猜测实现。
