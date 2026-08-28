# LearnFlow 图解与动画工具工程说明

## 目标

图解和动画是同一份教学对象的两种呈现，不是两个互不相干的“生成图片”接口。两者先产生可验证的 `VisualSpec`，图解渲染一个稳定状态，动画则重放一组有类型的状态补丁。模型只能提出候选对象；校验、布局、重放与降级由确定性运行时完成。

## 参考实现与取舍

- [Mermaid](https://github.com/mermaid-js/mermaid) 证明了文本/结构化图定义适合版本控制与多类技术图，但 LearnFlow 不直接执行模型生成的 Mermaid 文本，而是先进入受限对象模型。
- [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) 提供图论模型、交互和渲染分层的参考；LearnFlow 同样把节点、边、语义和呈现分开。
- [Eclipse ELK / elkjs](https://github.com/kieler/elkjs) 提供自动布局的参考；当前版本使用内建确定性布局，后续可把 ELK 作为纯布局适配器，不能改变教学语义。
- [Motion Canvas](https://github.com/motion-canvas/motion-canvas) 使用 TypeScript generator 表达可预览动画；LearnFlow 借鉴“时间线可重放”，但不执行模型代码。
- [Manim](https://github.com/3b1b/manim) 适合精确的数学动画。LearnFlow 当前不把自然语言直接编译成 Manim Python，因为生产环境不能安全地执行模型生成代码；数学动画先用有限的几何、函数、矩阵和概率对象表达。

## 统一对象底座

`VisualSpec v2` 包含：

- `domain`：`computer | math | mixed`。
- `scene`：有限节点、关系、标签、坐标与可访问描述。
- `animation`：帧、typed patch、持续时间、解释文字。
- `invariants`：重放过程中必须一直成立的约束。
- `finalState`：重放结果，用于确定性校验。
- `provenance`：输入主题、规划器结果、是否降级、失败原因与版本。
- `quality`：可读性、布局门、重放门和覆盖的抽象。

禁止 `eval`、任意脚本、任意 SVG/HTML、悬空引用、模型臆造的关系以及“动画失败但仍标成动画”。

## 计算机知识抽象

- 调用/消息序列：协议、函数调用、Agent tool loop。
- 状态机：线程、事务、编译器阶段、学习 Skill 子状态。
- 数据流与张量流：网络包、ETL、QKV、计算图。
- 内存与存储布局：栈/堆、页表、缓存、数组与对象。
- 树与图：AST、索引、依赖、搜索、知识图。
- 并发时间线：锁、调度、竞态、生产者消费者。
- 分层系统：网络栈、操作系统、模型/服务架构。

## 数学知识抽象

- 数轴、坐标系、函数图像与参数变化。
- 向量、线性变换、基与投影。
- 矩阵形状、乘法与分块结构。
- 几何构造、约束和不变量。
- 概率质量/密度、条件化与采样过程。
- 极限、导数、积分面积和局部线性化。
- 离散结构、集合关系与证明步骤。

## 成功率与延迟策略

1. 优先命中确定性模板和已有 gold fixture。
2. 模型只补充有限字段，不负责渲染代码。
3. 先校验引用与数量预算，再布局；布局失败降级为线性说明图。
4. 动画必须完整重放并满足 invariants；失败则降级为静态图，并保留 `degradedTo` 和失败原因。
5. 产物与五核隔离：看到图解只代表内容曝光，不代表理解或掌握。

## 验收

- JSON 往返不丢 provenance、quality、replay 或降级信息。
- 同一输入和模板产生稳定图。
- 动画 final state 可由初始状态和 typed patches 重建。
- reduced-motion、键盘操作、文本替代和窄屏均可用。
- 工具失败有真实原因；不能用占位动画冒充成功。
