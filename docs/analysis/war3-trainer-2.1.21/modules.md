# War3ReforgedTrainer v2.1.21 功能审计采用矩阵

本表覆盖全部 180 个第一方模块记录。`same-marshal-sha256` 表示当前模块 bytes 与完整历史审计一致，具体函数语义/出处见 firstparty-code-coverage.json；不表示重跑或动态验收。当前源码对应只表达基线职责和采用方向，实施/测试由 root 的独立 lane 负责。

| 模块 | 新旧关系 | code / instructions | 采用状态 | 当前相关文件 |
|---|---|---:|---|---|
| CArchive.war3_web_gui | modified | 6 / 735 | 结构变化_无需移植 | gui.py, gui_topbar.py |
| diagnostics | same-marshal-sha256 | 1 / 4 | 已有相关设计_无本轮增量 | reference_catalog.py |
| diagnostics.war3_native_profile | same-marshal-sha256 | 1 / 35 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_3_extension_catalog | same-marshal-sha256 | 3 / 107 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_3_stats | same-marshal-sha256 | 2 / 260 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_ability_field_protocol | same-marshal-sha256 | 10 / 1250 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_ability_fields | same-marshal-sha256 | 8 / 255 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_ability_protocol | same-marshal-sha256 | 6 / 742 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_adapter_24332 | same-marshal-sha256 | 5 / 135 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_adapter_legacy | same-marshal-sha256 | 40 / 6356 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_adapter_modules | same-marshal-sha256 | 84 / 4834 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_adapter_properties | same-marshal-sha256 | 16 / 1092 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_adapter_state | same-marshal-sha256 | 13 / 278 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_app | same-marshal-sha256 | 4 / 210 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_application | same-marshal-sha256 | 311 / 17716 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_archive_fields_ui | same-marshal-sha256 | 35 / 2200 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_artifact_plan | same-marshal-sha256 | 20 / 962 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_artifact_plan_ui | same-marshal-sha256 | 13 / 811 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_attack_speed_protocol | same-marshal-sha256 | 9 / 673 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_backend | same-marshal-sha256 | 294 / 26136 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_basic_fields | same-marshal-sha256 | 6 / 543 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_batch_edit_ui | same-marshal-sha256 | 32 / 1907 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_bulk_protocol | same-marshal-sha256 | 5 / 364 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_camera_protocol | same-marshal-sha256 | 7 / 387 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_capabilities | same-marshal-sha256 | 8 / 508 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_casc_catalog_24268 | same-marshal-sha256 | 1 / 24 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_classic_selection | same-marshal-sha256 | 8 / 433 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_cli | same-marshal-sha256 | 4 / 2898 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_clone_bound_protocol | same-marshal-sha256 | 11 / 780 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_clone_protocol | same-marshal-sha256 | 9 / 1105 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_clone_state_protocol | same-marshal-sha256 | 10 / 903 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_contracts | same-marshal-sha256 | 46 / 2439 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_definition_jobs | same-marshal-sha256 | 13 / 1496 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_desktop_bridge | modified | 112 / 8216 | 可实施_离线入口接线参考 | reference_cli.py, gui_reference_catalog.py, gui_worker_host.py |
| war3_desktop_runtime | same-marshal-sha256 | 7 / 569 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_direct_cast_protocol | same-marshal-sha256 | 8 / 795 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_discovery_abi | same-marshal-sha256 | 20 / 1565 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_ability_identity | same-marshal-sha256 | 4 / 813 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_call_abi | same-marshal-sha256 | 10 / 1699 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_components | same-marshal-sha256 | 13 / 1632 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_decoder_flow | same-marshal-sha256 | 24 / 2616 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_dependencies | same-marshal-sha256 | 9 / 767 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_fields | same-marshal-sha256 | 43 / 6369 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_image | same-marshal-sha256 | 10 / 1253 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_locators | same-marshal-sha256 | 51 / 6805 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_native | same-marshal-sha256 | 24 / 2679 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_native_recovery | same-marshal-sha256 | 17 / 1410 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_properties | same-marshal-sha256 | 10 / 1320 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_selection | same-marshal-sha256 | 11 / 1772 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_stats | same-marshal-sha256 | 19 / 2194 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_discovery_validation | same-marshal-sha256 | 9 / 977 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_effect_protocol | same-marshal-sha256 | 6 / 742 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_engine_24268 | same-marshal-sha256 | 14 / 2464 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_engine_continuation | same-marshal-sha256 | 3 / 303 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_engine_transport | same-marshal-sha256 | 31 / 6400 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_equipment_effect_protocol | same-marshal-sha256 | 15 / 1843 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_equipment_protocol | same-marshal-sha256 | 6 / 563 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_error_messages | same-marshal-sha256 | 19 / 1632 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_extension_definition_ui | same-marshal-sha256 | 31 / 1952 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_extension_protocol | same-marshal-sha256 | 9 / 913 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_external_backend | same-marshal-sha256 | 10 / 543 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_field_labels | same-marshal-sha256 | 5 / 3804 | 已有_本轮字段标签增量 | pack_query_field_evidence.py, reference_catalog.py |
| war3_game_adapter | same-marshal-sha256 | 17 / 198 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_game_profile | same-marshal-sha256 | 56 / 3510 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_game_session | same-marshal-sha256 | 38 / 2702 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_game_speed_protocol | same-marshal-sha256 | 5 / 360 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_game_version | same-marshal-sha256 | 5 / 446 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_gamecache_fields | same-marshal-sha256 | 23 / 1845 | 已有_不重复0.8.0 | save_container.py, save_gamecache.py, save_codes.py |
| war3_gold_mine_protocol | same-marshal-sha256 | 13 / 880 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_gui | same-marshal-sha256 | 112 / 11324 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_hero_attributes_protocol | same-marshal-sha256 | 9 / 622 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_hero_protocol | same-marshal-sha256 | 7 / 444 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_hero_skill_catalog | same-marshal-sha256 | 1 / 236 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_hero_skill_ui | same-marshal-sha256 | 17 / 848 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_id_catalog | same-marshal-sha256 | 6 / 343 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_id_descriptions | same-marshal-sha256 | 3 / 378 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_integrity | same-marshal-sha256 | 7 / 545 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_item_ability_protocol | same-marshal-sha256 | 9 / 661 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_item_catalog_protocol | same-marshal-sha256 | 14 / 1204 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_item_effect_protocol | same-marshal-sha256 | 8 / 1005 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_item_field_protocol | same-marshal-sha256 | 8 / 1114 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_item_fields | same-marshal-sha256 | 4 / 233 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_item_protocol | same-marshal-sha256 | 24 / 1956 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_item_safety_protocol | same-marshal-sha256 | 7 / 467 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_jass_validation | same-marshal-sha256 | 5 / 425 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_layout_schema | same-marshal-sha256 | 2 / 113 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_legacy_equipment_probe_protocol | same-marshal-sha256 | 2 / 145 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_loadout_restore | same-marshal-sha256 | 23 / 2475 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_loadout_storage | same-marshal-sha256 | 6 / 682 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_map_bounds_protocol | same-marshal-sha256 | 8 / 387 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_map_catalog_jobs | added | 15 / 1126 | 可实施_本轮已选 | gui_worker_host.py, gui_reference_catalog.py, reference_catalog.py |
| war3_map_catalog_reference | added | 2 / 44 | 资料参考_不导入冻结资产 | client_object_data.py, base_names.py |
| war3_map_objects | added | 15 / 1217 | 可实施_本轮WTS证据 | wts.py, w3obj.py, object_pipeline.py, object_materialization.py |
| war3_metadata | modified | 1 / 16 | 声明变化_无需移植 |  |
| war3_mouse_protocol | same-marshal-sha256 | 7 / 388 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_mpq | same-marshal-sha256 | 29 / 2265 | 已有_只读归档边界 | archive_source.py, mpq.py |
| war3_mpq_names | same-marshal-sha256 | 1 / 13 | 已有_只读归档边界 | archive_source.py, mpq.py |
| war3_native_journal | same-marshal-sha256 | 7 / 820 | 已有诊断设计_无本轮增量 | live_inventory.py, live_field_evidence.py |
| war3_native_preflight | same-marshal-sha256 | 5 / 407 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_native_table | same-marshal-sha256 | 11 / 698 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_new_equipment_catalog | same-marshal-sha256 | 1 / 3626 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_new_equipment_ui | same-marshal-sha256 | 15 / 740 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_object_registry | same-marshal-sha256 | 22 / 1931 | 已有或资料参考_来源需限定 | reference_catalog.py, client_object_data.py, base_names.py |
| war3_object_tables | same-marshal-sha256 | 35 / 3289 | 已有_本轮W3I增量 | w3i.py, w3f.py, w3obj.py, slk.py, object_pipeline.py |
| war3_operation_reports | same-marshal-sha256 | 3 / 1887 | 已有诊断设计_无本轮增量 | live_inventory.py, live_field_evidence.py |
| war3_operations | same-marshal-sha256 | 5 / 693 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_player_resources | same-marshal-sha256 | 2 / 51 | 已有相关设计_无本轮增量 | reference_catalog.py |
| war3_position_protocol | same-marshal-sha256 | 7 / 570 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_position_target_protocol | same-marshal-sha256 | 7 / 535 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_profile_discovery | same-marshal-sha256 | 33 / 1976 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_profile_resolver | same-marshal-sha256 | 28 / 5290 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_remote_exports | same-marshal-sha256 | 13 / 1400 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_runtime_check | same-marshal-sha256 | 3 / 682 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_save_codes | same-marshal-sha256 | 20 / 1126 | 已有_不重复0.8.0 | save_container.py, save_gamecache.py, save_codes.py |
| war3_save_extraction_ui | same-marshal-sha256 | 34 / 2134 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_screen_protocol | same-marshal-sha256 | 5 / 302 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_selection_diagnostics | same-marshal-sha256 | 5 / 560 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_selection_protocol | same-marshal-sha256 | 6 / 321 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_services | same-marshal-sha256 | 1 / 4 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.abilities | same-marshal-sha256 | 21 / 993 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.ability_bundle | same-marshal-sha256 | 15 / 1141 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.archive_fields | same-marshal-sha256 | 12 / 1804 | 已有_不重复0.8.0 | save_container.py, save_gamecache.py, save_codes.py |
| war3_services.artifact_plan | same-marshal-sha256 | 2 / 35 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.backpack_carrier | same-marshal-sha256 | 5 / 1202 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.backpack_interface | same-marshal-sha256 | 8 / 1314 | 本地解析部分已有_改图不采用 | object_pipeline.py, object_materialization.py, client_object_data.py |
| war3_services.batch_edit | same-marshal-sha256 | 43 / 2841 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.camera_projection | same-marshal-sha256 | 10 / 774 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.cursor | same-marshal-sha256 | 7 / 660 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.effect_lifetime | same-marshal-sha256 | 15 / 1051 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.equipment_effects | same-marshal-sha256 | 35 / 3459 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.equipment_slots | same-marshal-sha256 | 2 / 82 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.extension_definitions | same-marshal-sha256 | 34 / 3948 | 本地解析部分已有_改图不采用 | object_pipeline.py, object_materialization.py, client_object_data.py |
| war3_services.extensions | same-marshal-sha256 | 15 / 408 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_abilities | same-marshal-sha256 | 136 / 11186 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_binding | same-marshal-sha256 | 3 / 132 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_extensions | same-marshal-sha256 | 96 / 9710 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_fields | same-marshal-sha256 | 105 / 13847 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_items | same-marshal-sha256 | 53 / 3744 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_native | same-marshal-sha256 | 43 / 2851 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_resources | same-marshal-sha256 | 57 / 4170 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_selection | same-marshal-sha256 | 96 / 7111 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.facade_units | same-marshal-sha256 | 46 / 2292 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.gold_mines | same-marshal-sha256 | 5 / 165 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.item_effect_fields | same-marshal-sha256 | 13 / 1440 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.items | same-marshal-sha256 | 18 / 907 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.loadout_runtime | same-marshal-sha256 | 10 / 580 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.map_catalog | added | 39 / 4204 | 可实施_本轮直接入口 | api.py, map_loader.py, reference_catalog.py, object_candidates.py, object_materialization.py |
| war3_services.mouse_terrain | same-marshal-sha256 | 9 / 762 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.operation_trace | same-marshal-sha256 | 22 / 1761 | 已有诊断设计_无本轮增量 | live_inventory.py, live_field_evidence.py |
| war3_services.save_extraction | same-marshal-sha256 | 12 / 1104 | 已有_不重复0.8.0 | save_container.py, save_gamecache.py, save_codes.py |
| war3_services.speed | same-marshal-sha256 | 3 / 220 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.talent_definitions | same-marshal-sha256 | 8 / 648 | 本地解析部分已有_改图不采用 | object_pipeline.py, object_materialization.py, client_object_data.py |
| war3_services.talent_points | same-marshal-sha256 | 6 / 519 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.unit_type | same-marshal-sha256 | 12 / 941 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.units | same-marshal-sha256 | 49 / 2147 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_services.world | same-marshal-sha256 | 27 / 705 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_spawn_protocol | same-marshal-sha256 | 10 / 463 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_speed_clock_backend | same-marshal-sha256 | 18 / 2112 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_stat_details_protocol | same-marshal-sha256 | 14 / 1138 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_talent_icon_control_protocol | same-marshal-sha256 | 6 / 279 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_talent_icon_display | same-marshal-sha256 | 12 / 1350 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_talent_order_protocol | same-marshal-sha256 | 5 / 270 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_talent_probe_protocol | same-marshal-sha256 | 6 / 442 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_terrain_protocol | same-marshal-sha256 | 6 / 376 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_thread_context | same-marshal-sha256 | 10 / 1184 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_tk_view | same-marshal-sha256 | 41 / 1175 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_trainer_session | same-marshal-sha256 | 21 / 773 | 逐函数分界_主动链不采用 | live_inventory.py, live_field_evidence.py, reference_catalog.py |
| war3_ui_i18n | same-marshal-sha256 | 4 / 9058 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_ui_services | same-marshal-sha256 | 3 / 245 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_unit_action_protocol | same-marshal-sha256 | 6 / 736 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_unit_bindings_protocol | same-marshal-sha256 | 12 / 911 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_unit_components | same-marshal-sha256 | 4 / 56 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_unit_stats_protocol | same-marshal-sha256 | 6 / 747 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_version_modules | same-marshal-sha256 | 4 / 174 | 部分已有_其余需真实输入 | live_inventory.py, live_profile_validation.py, live_field_evidence.py, live_selection.py |
| war3_view_contract | same-marshal-sha256 | 5 / 55 | 已有交互设计_主动入口不采用 | gui.py, gui_worker_host.py, gui_reference_catalog.py, gui_live_probe.py |
| war3_web_gui | modified | 6 / 735 | 结构变化_无需移植 | gui.py, gui_topbar.py |
| war3_webview_viewport | modified | 73 / 3059 | 已有_错误详情与保存交互参考 | gui_worker_host.py, gui_reference_catalog.py |
| war3_world_cast_protocol | same-marshal-sha256 | 6 / 634 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_world_effect_protocol | same-marshal-sha256 | 5 / 444 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
| war3_world_protocol | same-marshal-sha256 | 8 / 712 | 主动执行链不采用_纯格式只作参考 | live_inventory.py, live_field_evidence.py |
