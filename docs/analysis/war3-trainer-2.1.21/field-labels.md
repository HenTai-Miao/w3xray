# Curated field label semantic audit

Baseline `cfe9f68a023ae5f5e274101cb32f70f536bfb64d`. 85 / 85 overrides classified; 17 confirmed corrections.

The target's item-field catalog prompted the check; every correction is independently supported by project-generated metadata, project WESTRING constants and/or fixed tech scalar roles. No target catalog is redistributed.

| Code | Previous curated label | Project metadata | Type | Disposition | Proposed/current label |
| --- | --- | --- | --- | --- | --- |
| `unam` | 名称 | 名字 | string | compatible-curated-wording | 名称 |
| `unsf` | 后缀名 | 名字 - 编辑器后缀 | string | compatible-curated-wording | 后缀名 |
| `upra` | 主属性 | 初级属性 | attributeType | compatible-curated-wording | 主属性 |
| `urac` | 种族 | 种族 | unitRace | identical | 种族 |
| `umdl` | 模型 | 模型文件 | model | compatible-curated-wording | 模型 |
| `ussc` | 缩放 | 选择缩放 | real | confirmed-semantic-correction | 选择圈缩放 |
| `uico` | 图标 | 图标 - 游戏界面 | icon | compatible-curated-wording | 图标 |
| `uhpm` | 生命上限 | 最大生命值(基础) | int | compatible-curated-wording | 生命上限 |
| `umpm` | 魔法上限 | 最大魔法值 | int | compatible-curated-wording | 魔法上限 |
| `uhpr` | 生命回复 | 生命值回复率 | unreal | compatible-curated-wording | 生命回复 |
| `umpr` | 魔法回复 | 魔法回复 | unreal | identical | 魔法回复 |
| `ustr` | 力量 | 初始力量 | int | compatible-curated-wording | 力量 |
| `uagi` | 敏捷 | 初始敏捷 | int | compatible-curated-wording | 敏捷 |
| `uint` | 智力 | 初始智力 | int | compatible-curated-wording | 智力 |
| `ustp` | 力量成长 | 每等级所加力量 | unreal | compatible-curated-wording | 力量成长 |
| `uagp` | 敏捷成长 | 每等级所加敏捷 | unreal | compatible-curated-wording | 敏捷成长 |
| `uinp` | 智力成长 | 每等级所加智力 | unreal | compatible-curated-wording | 智力成长 |
| `ulev` | 等级 | 等级 | int | identical | 等级 |
| `uhos` | 占用人口 | 对中立单位主动攻击概率 | bool | confirmed-semantic-correction | 可作为中立敌对显示 |
| `ufoo` | 提供人口 | 食物消耗 | int | confirmed-semantic-correction | 占用人口 |
| `ua1d` | 攻击间隔 | 攻击 1 - 伤害数量概率 | int | confirmed-semantic-correction | 攻击伤害骰子数 |
| `ua1b` | 基础攻击 | 攻击 1 - 基础伤害 | int | compatible-curated-wording | 基础攻击 |
| `ua1c` | 攻击次数 | 攻击 1 - 魔法施放时间间隔时间 | unreal | confirmed-semantic-correction | 攻击间隔 |
| `udp1` | 攻击力骰子 | 攻击 1 - 动画损伤点 | unreal | confirmed-semantic-correction | 攻击伤害前摇 |
| `usi1` | 骰子面数 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 骰子面数 |
| `udef` | 护甲 | 基础防御 | unreal | compatible-curated-wording | 护甲 |
| `umvs` | 移动速度 | 基础速度 | int | compatible-curated-wording | 移动速度 |
| `uspe` | 移动类型 | 分类 - 特殊的 | bool | confirmed-semantic-correction | 特殊分类 |
| `usin` | 视野(白天) | 视野范围(夜晚) | int | confirmed-semantic-correction | 视野(夜晚) |
| `usip` | 视野(夜晚) | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 视野(夜晚) |
| `ucol` | 碰撞体积 | 触碰体积 | unreal | compatible-curated-wording | 碰撞体积 |
| `uabi` | 技能列表 | 普通 | abilityList | compatible-curated-wording | 技能列表 |
| `uhab` | 英雄技能 | 英雄 | heroAbilityList | compatible-curated-wording | 英雄技能 |
| `upgr` | 可升级科技 | 已使用的升级 | upgradeList | confirmed-semantic-correction | 使用的科技 |
| `ucbs` | 选择圈大小 | 动画 - 魔法施放回复 | unreal | confirmed-semantic-correction | 施法后摇 |
| `ugol` | 金币花费 | 金子消耗 | int | compatible-curated-wording | 金币花费 |
| `ulum` | 木材花费 | 木材消耗 | int | compatible-curated-wording | 木材花费 |
| `ubld` | 建造时间 | 建造时间 | int | identical | 建造时间 |
| `ides` | 描述 | 描述 | string | identical | 描述 |
| `utub` | 提示文本 | 提示工具 - 扩展的 | string | compatible-curated-wording | 提示文本 |
| `utip` | 工具提示 | 提示工具 - 基础 | string | compatible-curated-wording | 工具提示 |
| `iabi` | 携带技能 | 技能 | abilityList | compatible-curated-wording | 携带技能 |
| `igol` | 金币价值 | 金子消耗 | int | compatible-curated-wording | 金币价值 |
| `ilum` | 木材价值 | 木材消耗 | int | compatible-curated-wording | 木材价值 |
| `ilev` | 物品等级 | 等级 | int | compatible-curated-wording | 物品等级 |
| `iico` | 图标 | 界面图标 | icon | compatible-curated-wording | 图标 |
| `icla` | 物品分类 | 分类 | itemClass | compatible-curated-wording | 物品分类 |
| `ipri` | 优先级 | 优先权 | int | compatible-curated-wording | 优先级 |
| `iperD` | 完美 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 完美 |
| `idrop` | 可掉落 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 可掉落 |
| `ilvo` | 等级(隐藏) | 等级(无类别的) | int | confirmed-semantic-correction | 等级(旧版) |
| `iusn` | 使用次数 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 使用次数 |
| `icid` | 冷却组 | 魔法施放间隔时间组 | abilCode | compatible-curated-wording | 冷却组 |
| `ifil` | 替换列表 | 已使用的模型 | model | confirmed-semantic-correction | 模型 |
| `iclb` | 战利品掉落 | 染色 3 (蓝色) | int | confirmed-semantic-correction | 染色(蓝色) |
| `anam` | 名称 | 名字 | string | compatible-curated-wording | 名称 |
| `ansf` | 后缀 | 编辑器后缀 | string | compatible-curated-wording | 后缀 |
| `arac` | 种族 | 种族 | unitRace | identical | 种族 |
| `aret` | 学习提示 | 提示工具 - 学习 | string | compatible-curated-wording | 学习提示 |
| `arut` | 未学习提示 | 提示工具 - 学习 - 扩展的 | string | confirmed-semantic-correction | 学习扩展提示 |
| `atp1` | 提示 | 提示工具 - 普通 | string | compatible-curated-wording | 提示 |
| `aub1` | 扩展提示 | 提示工具 - 普通 - 扩展的 | string | compatible-curated-wording | 扩展提示 |
| `aical` | 图标 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 图标 |
| `adur` | 持续时间 | 持续时间 - 普通 | unreal | compatible-curated-wording | 持续时间 |
| `ahdu` | 英雄持续 | 持续时间 - 英雄 | unreal | compatible-curated-wording | 英雄持续 |
| `acdn` | 冷却 | 魔法施放时间间隔 | unreal | compatible-curated-wording | 冷却 |
| `amcs` | 魔法消耗 | 魔法消耗 | int | identical | 魔法消耗 |
| `aare` | 作用范围 | 影响区域 | unreal | compatible-curated-wording | 作用范围 |
| `aran` | 施法距离 | 魔法施放范围 | unreal | compatible-curated-wording | 施法距离 |
| `acas` | 施法次数 | 魔法施放时间 | unreal | confirmed-semantic-correction | 施法时间 |
| `alev` | 等级数 | 等级 | int | compatible-curated-wording | 等级数 |
| `abuf` | buff效果 | 魔法效果 | buffList | compatible-curated-wording | buff效果 |
| `aeff` | 效果 | 特效 | effectList | compatible-curated-wording | 效果 |
| `Hbz1` | 数据 | 光波数量 | int | compatible-general-label | 数据 |
| `gnam` | 名称 | 名字 | string | compatible-curated-wording | 名称 |
| `gtp1` | 提示 | 提示工具 | string | compatible-curated-wording | 提示 |
| `gub1` | 扩展提示 | 提示工具 - 扩展的 | string | compatible-curated-wording | 扩展提示 |
| `glvl` | 等级数 | 等级 | int | compatible-curated-wording | 等级数 |
| `gef1` | 效果 | 效果 1 | upgradeEffect | compatible-curated-wording | 效果 |
| `gglb` | 基础金币 | 基础金钱 | int | compatible-curated-wording | 基础金币 |
| `gglm` | 金币增量 | 金钱增加 | int | compatible-curated-wording | 金币增量 |
| `gtib` | 基础木材 | 基础时间 | int | confirmed-semantic-correction | 基础时间 |
| `gtim` | 木材增量 | 时间增加 | int | confirmed-semantic-correction | 时间增量 |
| `greq` | 依赖科技 | 要求 | techList | compatible-curated-wording | 依赖科技 |
| `gico` | 图标 | unrecorded | unrecorded | retained-legacy-label-without-metadata-role | 图标 |

## Confirmed role distinctions

- `ussc`: selection scale 与模型 usca 缩放不同；原标签丢失了选择范围限定. fields.py:44 / field_meta.py:1423.
- `uhos`: 精确 WESTRING_UEVAL_UHOS 声明中立敌对显示，不是人口或主动攻击；生成标签存在旧翻译冲突，不跟随该错误. fields.py:57 / field_meta.py:1306.
- `ufoo`: food used/食物消耗；生产人口另为 ufma. fields.py:58 / field_meta.py:1294.
- `ua1d`: ATTACK_DAMAGE_NUMBER_OF_DICE 整数字段，不是攻击间隔. fields.py:59 / field_meta.py:1208.
- `ua1c`: ATTACK_BASE_COOLDOWN 时间字段，不是攻击次数. fields.py:61 / field_meta.py:1207.
- `udp1`: ATTACK_DAMAGE_POINT 动画伤害点时间，不是伤害骰子数. fields.py:62 / field_meta.py:1281.
- `uspe`: bool 分类标志；移动类型另为 umvt 的 moveType. fields.py:66 / field_meta.py:1419.
- `usin`: night sight radius；白天视野另为 usid. fields.py:67 / field_meta.py:1413.
- `upgr`: upgrades used：应用于该单位的科技，不是可研究/可升级清单. fields.py:72 / field_meta.py:1360.
- `ucbs`: CAST_BACK_SWING 动画施法回复时间，不是选择圈大小. fields.py:73 / field_meta.py:1264.
- `ilvo`: 精确 WESTRING_UEVAL_ILVO 声明旧版等级；生成表称无类别等级，二者均没有隐藏状态语义. fields.py:90 / field_meta.py:1037.
- `ifil`: ITEM_SF_MODEL_USED / model 路径；不存在替换列表语义. fields.py:93 / field_meta.py:1026.
- `iclb`: ITEM_IF_TINTING_COLOR_BLUE int 0..255；掉落另为 idrp/idro 的 bool. fields.py:94 / field_meta.py:1013.
- `arut`: ABILITY_SLF_TOOLTIP_LEARN_EXTENDED，不是未学习状态提示. fields.py:100 / field_meta.py:651.
- `acas`: ABILITY_RLF_CASTING_TIME，不是施法次数. fields.py:110 / field_meta.py:604.
- `gtib`: upgrade time base；木材基础另为 glmb 的固定角色. fields.py:123 / field_meta.py:983.
- `gtim`: upgrade time increment；木材增量另为 glmm 的固定角色. fields.py:124 / field_meta.py:984.
