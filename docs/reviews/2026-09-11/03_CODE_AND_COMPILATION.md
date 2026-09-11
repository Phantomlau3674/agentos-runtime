# 代码与编译优化：先减少工作，再编译热点

状态：提案。代码审阅基线 `76d73de110436ed907fdb141e6f44d239ed137b5`。本轮上传不修改实现。历史局部观测见 [证据说明](05_EVIDENCE_AND_REPRODUCTION.md)，原实验脚本未找回，数字不得当作本轮重新测得。

## 1. 外部请求与内部不可变计划分离

contracts.py 使用 frozen=True，但 nodes 和 depends_on 是可变 list。历史报告记录 append 成功且计划哈希变化；_preflight 重新校验会拒绝非法计划，因此不是已证实的越权漏洞。

设计：JSON wire model 在外部边界完整校验；受信编译函数生成仅含递归不可变对象的 CompiledPlan。tuple/frozenset/bytes 不足以自动冻结其内部任意对象，必须限制嵌套值类型。规范化序列化、计划哈希和拓扑顺序在真正冻结之后计算。

示意，不是补丁：

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CompiledNode:
    opcode: str
    predecessors: tuple[int, ...]
    input_refs: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CompiledPlan:
    nodes: tuple[CompiledNode, ...]
    canonical_bytes: bytes
    plan_hash: str
```

不能先在当前可变对象上缓存 plan_hash，也不能删掉跨进程/恢复加载的验证和动态权限校验。新的内部类型由独立入口创建，避免外部调用者伪造已编译对象。

## 2. 让分页真正减少工作

gateway.py 的 artifact_read 先调用 task_inspect，成功任务会完整核验全部产物，随后完整读目标文件再截取字符。历史报告中每读1字符仍发生5次逻辑读取、84,554字节；这不是磁盘或耗时测试。

建议分开：task_inspect 返回元数据和最近核验时间；artifact_open 核验指定内容版本并建读取会话；artifact_read 对该快照分段读取。小文件采用有界不可变字节快照，大文件再评估分块校验和索引。权限、任务绑定、内存限额、过期与读取会话关闭都需定义。

公开语义须明确读的是固定快照还是当前磁盘版本。mtime不能代替完整性；Unicode字符偏移不能直接变成UTF-8字节seek。验证改版要更新受影响的错误与完整性测试，不以降低保证换性能。

## 3. 汇总内核

现有 setdefault 每个有效行都先构造默认字典及 Decimal(0)，即使分组已存在。可以改为只在缺失时构造。localcontext 当前逐行进入，可做独立实验评估上下文范围或固定小数契约下的整数分内核。

历史候选报告：62组合成输入对照一致；20,000有效行、7轮局部内核中位数分别为59.89ms（原版）、55.61ms（延迟创建）、39.22ms（整数分加延迟创建）。原始样本和候选源文件缺失，须重建实验，不能直接宣传34.5%的系统提效。

整数分只适用于当前非负、最多两位小数单价和整数数量的规则。价格解析不得先转float；保留前导零、异常分类、文件排序和ID占位语义。允许范围的累计金额分数可能接近10^22，超过int64；原生实现必须证明范围并使用checked arithmetic/更宽整数。汇率、利息和任意舍入需新契约。

## 4. 减少重复转换，不减少必要校验

gateway.call 校验后 dump 成字典，内部方法再次构造参数，runtime 再经 JSON 往返校验。当前部分步骤承担复制隔离，不能直接删除。

目标路径：外部JSON→请求验证→冻结IR→内部类型/产物引用传递→对外序列化。只消除明确同信任域中的冗余转换，保留外部输入、持久化加载、恢复、跨进程和版本变化边界。重用验证器，但不要未经计量宣称其是当前主瓶颈。

## 5. MCP 控制与执行分开限额

基线 mcp_server.py 已通过官方 SDK 暴露工具，将调用交给 anyio.to_thread.run_sync，设置 abandon_on_cancel=True。取消RPC等待不等于停止工作线程。

为长执行与短控制请求提供独立并发额度和有界队列，保证负载饱和时查询/取消有机会执行。业务取消持久化并在安全点检查；明确长计算的取消延迟。不得宣称取消撤回已经发生的外部行为。本轮未做饱和或真实客户端测试。

## 6. 受限任务编译管线

```text
wire request
  -> schema/type validation
  -> immutable logical IR
  -> effects/alias/dependency analysis
  -> guarded optimization passes
  -> physical plan
  -> execution + verification
```

逻辑IR表达做什么，物理计划表达用什么适配器、批次与资源执行。采用版本化结果引用，避免隐藏全局状态。保留结构到源码节点的映射，便于回执和故障定位。

```text
%input    = snapshot(dataset@v12)
%rows     = parse_csv(%input, schema=v1)
%resolved = resolve_duplicate_ids(%rows, order=filename_then_row)
%summary  = aggregate(%resolved.valid_rows)
%errors   = collect_errors(%resolved)
%report   = verify(%summary, %errors, expectations)
publish(%summary, %errors, %report)
```

每个值代表明确版本。解析可独立批量执行，不得未经证明重排全局ID裁决。

## 7. 第一批优化规则

| 规则 | 应用 | 约束 |
|---|---|---|
| 常量绑定/特化 | 固定schema、金额精度、字段映射后选择内核 | 输入必须持续满足已声明契约 |
| 公共纯计算复用 | 相同快照的相同解析复用 | 完整依赖、参数、实现及环境一致 |
| 算子融合 | 合并兼容的连续变换 | 保留验收、恢复、安全点和外部效果边界 |
| 批量接口合并 | 兼容应用调用组合 | 顺序、错误、部分失败语义等价 |
| 生命周期分析 | 释放不再有消费者的内存数据 | 不删除恢复仍需的持久产物 |
| 无用纯计算消除 | 删除不影响交付及验收的计算 | 异常、审计、终止性等可观察行为不变 |

适配器声明的读写集、异常与可重试语义由受信代码提供。结果无人读取不等于可删除该动作；验收、授权与审计不能被优化器消除。

## 8. Guard、退出与缓存

每段快路径保留进入条件、动态检查点和退出结果映射。执行前不满足条件可以选择参考路径；外部动作发出后效果未知，必须先对账，不能直接换实现再执行。

分开编译缓存和结果缓存：前者绑定计划结构、契约、编译器和后端能力；后者绑定动作实现、完整输入依赖、参数和相关环境。缓存命中不继承旧权限，执行时重新检查授权和撤销。

一次编译成本C、每次节约D、重复R次，只有R×D>C才有时间净收益。一次性小任务采用简单解释执行；不强制复杂优化。

## 9. 机器码编译路线

打包解决交付，任务编译解决减少工作，原生编译解决剩余计算速度，三者分开。

保留Python的协议、权限、状态和协调；把纯计算内核整理为有界批处理接口。先测类型明确模块的mypyc兼容性，再按需求评估Cython或Rust/PyO3，不同时引入多条重写路线。释放GIL不是单线程加速按钮。

跨语言按批次传数据，不每行Python→原生→Python。净收益要扣掉复制、转换、调用与启动成本。限制批次内存和取消延迟。原生整数范围、编码、错误序和取消语义必须与参考实现一致。

热点稳定后再评估PGO/LTO，保存编译器版本、选项、目标平台和训练负载。使用代表性数据与未见变体，避免只为一个示例调参。生成exe或wheel不等于运行更快。

## 10. 优化器的验收

保留少优化、容易理解的参考解释器。每条pass可单独关闭并输出explain：复用了什么、为何能融合/重排、依赖什么条件、失效后如何退出。

从相同初始状态分别执行参考与优化路径，比输出、错误、顺序、外部效果、取消、预算和可恢复位置。不能只比较最后文件字节而忽略额外远端写入。采用差分、极值、性质测试、故障注入和消融；局部计算节约与端到端收益分别报告。

## 原讨论参考

- Pydantic模型：https://docs.pydantic.dev/latest/concepts/models/
- Pydantic性能：https://docs.pydantic.dev/latest/concepts/performance/
- AnyIO线程：https://anyio.readthedocs.io/en/stable/threads.html
- MLIR高层优化：https://mlir.llvm.org/docs/Tutorials/Toy/Ch-3/
- MLIR副作用：https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/
- mypyc：https://mypyc.readthedocs.io/en/latest/introduction.html
- Cython/GIL：https://docs.cython.org/en/latest/src/userguide/nogil.html
- PyO3：https://pyo3.rs/main/performance
- Clang构建优化：https://clang.llvm.org/docs/UsersManual.html

来源保留前轮讨论入口；本次不安装这些编译器、不声称原生编译试验通过。
