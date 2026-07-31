# LearnFlow 通用可视化引擎设计（垂直生图 v2）

> 2026-08-01 · 从"4 个专用组件"走向"通用教学可视化对象语言"。
> 基于 manim / VisuAlgo / Python Tutor / TF playground / PhET / Mathigon
> 的架构共性提炼。

## 一、核心洞察：所有教学可视化的统一抽象

研究了 6 类标杆项目后，它们的架构可以归约到同一个三层模型：

| 项目 | 对象层 | 状态层 | 交互层 |
|---|---|---|---|
| manim | Mathematical Object | Timeline（变换序列） | 参数化生成 |
| VisuAlgo | 数据结构图元 | State + Step 播放 | 输入参数 |
| Python Tutor | 内存帧（栈/堆/对象图） | 执行步骤帧 | 步进 |
| TF playground | 网络图（节点/边） | 训练轮次状态 | 参数滑杆 |
| PhET | 物理对象 | 模拟时钟 | 参数 → 模拟 |
| Mathigon | 几何对象 | 约束更新 | 拖拽 |

**统一模型**：

```
可视化 = 对象场景(Scene) + 状态序列(States) + 交互参数(Params)
         └────────┬─────────┘   └─────┬────┘    └─────┬────┘
            类型化图元            状态间过渡=动画     参数绑定=实时生成状态
```

- **对象层**：场景由**类型化图元**组成（cell/pointer/box/grid/curve/node/edge/arrow/text/group…），每个图元带属性（值/颜色/高亮/标签/尺寸）
- **状态层**：`states: [State0, State1, …]`，每个 State 是对象属性的**增量变化**；动画 = 状态间属性插值过渡
- **交互层**：参数（滑杆/输入）**声明式绑定**到对象属性或表达式 → 参数变化即生成新状态

## 二、为什么这能通用（vs 固定组件清单）

固定组件（现在 4 个）的毛病：新需求 = 新组件 = 新代码。通用化 = **LLM 用"对象语言"组合场景**，渲染引擎只认对象类型：

```
旧：{"type":"array-pointer", ...}  ← 专用组件，每加一种就写一个组件
新：{"objects":[{"id":"arr","type":"array","values":[...]},
                 {"id":"p","type":"pointer","target":"arr"}],
     "states":[...]}               ← 对象语言，组合无限
```

**新增可视化 = 新增对象组合，不是新增代码**。数组指针、内存布局、排序动画、张量、神经网络、损失曲线……全部是同一套对象 + 状态 + 交互。

## 三、DSL 草案（v2）

```json
{
  "title": "冒泡排序",
  "scene": {
    "objects": [
      {"id": "arr", "type": "array", "values": [5, 3, 8, 1]},
      {"id": "i",   "type": "pointer", "target": "arr", "index": 0, "label": "i"},
      {"id": "j",   "type": "pointer", "target": "arr", "index": 0, "label": "j"}
    ]
  },
  "states": [
    {"note": "比较 5 和 3", "highlight": {"arr": [0, 1]}},
    {"note": "交换", "swap": {"arr": [0, 1]}, "set": {"j.index": 1}}
  ],
  "interact": [
    {"param": "speed", "min": 0.2, "max": 3, "default": 1}
  ]
}
```

```json
{
  "title": "损失曲面与梯度下降",
  "scene": {
    "objects": [
      {"id": "loss", "type": "curve", "fn": "x^2", "range": [-4, 4]},
      {"id": "w", "type": "point", "on": "loss", "x": 3, "y": 9, "label": "w=3"}
    ]
  },
  "states": [
    {"note": "初始 w=3", "set": {"w.x": 3, "w.y": 9}},
    {"note": "梯度下降一步", "set": {"w.x": 1.2, "w.y": 1.44}}
  ],
  "interact": [
    {"param": "lr", "min": 0.01, "max": 1, "default": 0.1,
     "bind": "w.x = w.x - lr * 2 * w.x"}
  ]
}
```

**同一套 DSL 表达两种完全不同的教学场景**——这就是通用化。

## 四、渲染引擎架构

```
VizRenderer
 ├─ SceneEngine（SVG 坐标系 + 缩放/平移）
 ├─ ObjectRegistry：{type → renderer}（图元渲染器注册表，可扩展）
 │    array / pointer / grid / curve / point / node / edge / arrow /
 │    text / shape / memory-frame / tree-node ...
 ├─ Layouters（自动布局，LLM 不需要给坐标！）
 │    array→横排 / grid→网格 / graph→分层或力导向 / curve→坐标映射
 ├─ StateMachine（states 播放/步进/回退 + 属性过渡动画）
 └─ InteractPanel（参数滑杆 → 绑定表达式实时求值）
```

**关键设计决策**：
1. **自动布局**：LLM 声明对象，引擎负责排版——LLM 算不准像素坐标，这是可用性的命门
2. **图元渲染器是增量扩展点**：新对象类型 = 一个渲染函数，对象语言自动获得新能力
3. **表达式安全**：interact 绑定和白名单（复用 function-plot 的 safeExpr）
4. **状态增量而非全量**：states 只描述变化，减少 LLM 输出量
5. **分组对象**：`{"type":"group","children":[...]}` 支持复杂组合（内存帧=标题+若干 cell+箭头）

## 五、渐进路径（从现有 P0 平滑迁移）

| 阶段 | 内容 |
|---|---|
| **P1 对象引擎** | SceneEngine + ObjectRegistry + 自动布局 + StateMachine；把 4 个专用组件**重写为对象组合**（array+pointer / curve+point / grid / node+edge）——验证模型覆盖现有功能 |
| **P2 交互** | InteractPanel + 参数绑定表达式 |
| **P3 高级对象** | memory-frame（栈/堆）、tree、graph 力导向、3D（three.js 渲染器） |
| **P4 组件市场** | 用户/社区可加图元渲染器 |

## 六、验证标准

P1 完成后，用同一套引擎**不加新代码**实现：
- [ ] 冒泡排序动画（array + pointer + states）✅ 现有
- [ ] 函数曲线（curve + point）✅ 现有
- [ ] 矩阵乘法（grid + highlight）✅ 现有
- [ ] 神经网络（node + edge）✅ 现有
- [ ] **栈帧内存图**（memory-frame + arrow）——之前需要新组件
- [ ] **二叉搜索树插入**（tree-node + pointer）——之前需要新组件
- [ ] **梯度下降实时演示**（curve + point + interact）——之前需要新组件

> 能不加代码覆盖最后三行，通用化才算成立。
