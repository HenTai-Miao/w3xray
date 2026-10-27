> 本分卷的证据路径以 `audit://target-4/crosscheck/` 为基准，完整内容在静态证据 ZIP 中保留。

# 大象 1.27：有界交叉复核附补

本附补完成父任务指定的一次 target-4 / target-5 易语言格式对照，以及对原未解码区域的完整分类。只读对方脚本与静态结果，没有运行两个目标或其载荷，没有改对方目录或项目源码。此前主报告和 JSON 原件已留在 `before-event-recovery/`；顶层 README 加了本附补入口，features.json 只更正新增的事件证据和明确冲突。

## 事件表的特定未知已经关闭

target5 最终 parser 的关键点是连续读取 NUL 名称、NUL tag 后再定位 child table，而不是扫描绝对 callback VA。对 target4 的全部137记录，q 为 tag 终止符之后，child_count 在 q+28，event_count 在 q+53+4*child_count，后随完整 (int32 event_id, uint32 relative_code_offset) 对。高级选择夹20项 children 已计入，两个 blob 的编码末边界均精确吻合。

恢复总量为21个带事件对象、22条事件：主窗18对象19事件，副窗3对象3事件。全部偏移加声明 code base 后落在真正 canonical prolog，并与既有恢复 CFG 一致。数值 event ID 按原值保留，不把所有类型的 event 0 都叫“点击”。137个控件连 event_count=0 一起保存于 `forms/controls-with-events.json`，全部事件在 `forms/events.json` / `events.tsv`。

这次不只套用另一份程序的惯例：target4 自己的 loader 在 VA `0x46d06c/0x46d071` 从原文件 metadata `0xe478c/0xe4788` 取 blob size/pointer，传入完整解析；VA `0x46d0de` 明确读取原metadata `0xe477c` 的 code base `0x401004`，`0x46d1ac..0x46d1c6` 逐项对非 -1 事件 offset 加这个 base 并写回。对应字节已逐条断言，见 `event-loader-proof.json` / `.asm`。

两个目标的布局相同，此前缺口来自没有消费 NUL tag/children 后的相对 code offset 结构，并非无法兼容的文件格式。target5 的对照 loader 是 `0x452290` / `0x45235e..0x452378`；target4 已用自己的 loader 独立证明，不依赖跨版本地址照搬。

## 新证据揭示的语义冲突

“无CD无蓝耗”控件 `0x160fcb52` 的 event 0 确实在原 offset `0xeacfa` 声明 callback；relative 字段 `0xeacfe = 0xd2a9`，加 code base 后为 `0x40e2ad`。但该 handler 的实际 checked getter 输入是“不会失败”`0x160fcb50`，随后进入已有写通道。故它不是“完全没有实现引用”，也不能据此宣称无CD/无蓝耗已实现：真实事件 owner 与 handler 实际读取输入相矛盾。“不会失败”自己的 callback 则独立为 `0x40ebaa`。

这同时解释为什么只凭精确 ID 的 getter 引用会误认完整功能归属。现将序列 owner、实际读取 control、静态 native 写路径分开保存。`forms/binding-conflicts.json` 和顶层 features.json 有同一冲突。人口限制与解除科技限制仍为零事件对象，没有从相邻开关推定实现。

主窗初始/关闭、展开侧边栏、注入脚本、透明化与变色 timer、作者标签，以及副窗的 timer 和“局域网开图”按钮现在都有真实绑定证据。尤其作者标签 event 0 → `0x411387`，副窗按钮 event 0 → `0x40f209`；这些精确绑定不会自动补齐尚未证明的 OS 热键/运行期交互语义。所有22个 callback的已知API路径另存 `event-native-paths.json`。

## 原先未解码215,936字节的分类

本次没有把整段强行线性解码作为“语义全解”。先精确重建原710,292-byte解码并集，再仅对其补集分配分类；每个区间保留原范围、完整hex与SHA-256，所有分类字节之和必须等于215,936。对已解码 indexed dispatch table 的目标和 materialized-return/SEH continuation 做一次带来源的候选CFG遍历，结果仍只标 code candidate，不并入原可达代码覆盖数。

| 原未解码部分分类 | 字节 | 证据层级 |
|---|---:|---|
| opaque_unclassified_code_or_data | 117,164 | 仍不透明，未强行归为代码或数据 |
| single_byte_jump_bypass | 9,007 | 原解码jmp明确跨过一字节；只声明该edge的边界 |
| constant_branch_bypass | 6,880 | clc/jae或stc/jb等常量carry分支跨过的字节 |
| return_adjust_helper_bypass | 1,744 | 精确call-next/add-return/ret助手跨过的字节 |
| uniform_zero_data_or_alignment | 13,519 | 完整00重复段；数据/对齐候选，不推断不可达 |
| uniform_int3_alignment_candidate | 5,535 | 完整CC重复段；对齐候选 |
| referenced_dispatch_code_candidate | 40,192 | 已解码 indexed dispatch table 指向；静态候选CFG，可达性/语义未证 |
| indexed_code_pointer_table | 2,836 | 已解码带索引内存操作直接使用的连续code pointer表 |
| uniform_nop_alignment_candidate | 17,676 | 完整90重复段；对齐候选 |
| exception_continuation_code_candidate | 607 | 已解码 mov eax, code-address / ret 指向的 continuation；候选 |
| nul_terminated_ascii_data_candidate | 776 | 补集中完整可打印ASCII+NUL；文本数据候选 |

合计 **215,936** 字节。81项 indexed table 证据和异常/continuation候选均完整保存。剩余 **117,164** 字节保持 code/data unknown；即使一些短区间可线性解成普通x86，也未升级为可达代码或已解释功能。详见 `remaining-byte-classification.json` 与 `provenance-code-candidates.json`。

## 收口状态

本次关闭的是序列事件表与callback地址计算的特定未知，保留了实际输入错配。全程序生成载荷的逐功能游戏语义、剩余不透明字节、OS热键完整所有权、overlay含义、运行时游戏成功/当前版本/平台兼容仍未知。原文件完整哈希和身份再次一致，见 `source-verification.json`。一次完整交叉对照已完成；没有新增运行目标或游戏写入。
