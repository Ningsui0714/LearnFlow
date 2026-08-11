# Learner State Discovery · Seeded 离线演示

> seed=20260811 · 无外部 API Key、无网络 · 演示数据与真实数据隔离（临时 SQLite，可重复重建）
> 权威链：行为 -> EvidenceEvent -> five_kernel_reducer -> KernelMutation -> KernelState -> Memory Graph

### 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）

- 会话：DISC-23da5f997327
- 学习者：STU-DEMO-001，项目：PROJ-DEMO-001
- 目标候选：想学 Java 面向对象；期望产物：独立完成成绩管理实训
- 策略：{"seed": 20260811, "interaction_budget": 10, "followup_budget": 2, "skip_limit": 2, "complete_coverage": 0.5}

**第 1 轮 · 下一交互 = clarification**
> 目的：确认学习目标与期望产物：目标决定了本轮要降低哪部分不确定性
  - 学习者确认目标：完成 Java 面向对象成绩管理实训
  - 观察[value] 目标已确认：完成 Java 面向对象成绩管理实训

**第 2 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 多态与接口 的掌握
- 题目：以下哪项是多态发生的必要条件？
- 知识点：多态与接口（KN_JAVA_POLYMORPHISM）
  - a. 类必须是 final
  - b. 继承（或实现）并重写方法、父类引用指向子类对象
  - c. 所有字段必须是 public
  - 学习者作答：独立答对
  - 判题：correct=True，答案解析：多态 = 父类引用变量指向子类对象，调用被子类重写的方法，运行期动态绑定。
  - 观察[knowledge] 独立答对：verified_once（1 道不同题）（status=verified_once，confidence=0.65）
  - 观察[practice] 独立完成：独立性 -> applied（status=applied，confidence=0.7）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（尚无评分证据，priority=1.0）

**第 3 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 输入输出流 的掌握
- 题目：Java 字节流的两个抽象基类是？
- 知识点：输入输出流（KN_JAVA_IO）
  - a. Reader 与 Writer
  - b. InputStream 与 OutputStream
  - c. File 与 Path
  - 学习者作答：答错
  - 判题：correct=False，答案解析：字节流基类为 InputStream/OutputStream；Reader/Writer 是字符流。
  - 观察[knowledge] 答错：记录错误证据（IO_STREAM_BASE）（status=candidate，confidence=0.6）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（尚无评分证据，priority=1.0）

**第 4 轮 · 下一交互 = prerequisite_probe**
> 目的：区分误解与前置缺口，降低知识核不确定性
> 追问内容：这道题可能依赖前置知识。你觉得自己是哪里卡住了？
  - 学习者解释：我说不太准，感觉和方法调用有关（matches_rubric=None）
  - 观察[knowledge] 解释无法可靠判定：保留原始回答待复查（need_review）

**第 5 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 继承与方法重写 的掌握
- 题目：子类继承父类使用的关键字是？
- 知识点：继承与方法重写（KN_JAVA_INHERITANCE）
  - a. implements
  - b. extends
  - c. inherits
  - 学习者作答：独立答对
  - 判题：correct=True，答案解析：Java 类继承用 extends；implements 用于实现接口。
  - 观察[knowledge] 独立答对：verified_once（1 道不同题）（status=verified_once，confidence=0.65）
  - 观察[practice] 独立完成：独立性 -> applied（status=applied，confidence=0.7）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（尚无评分证据，priority=1.0）

**第 6 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 类的定义与对象创建 的掌握
- 题目：在 Java 中，定义类的关键字是？
- 知识点：类的定义与对象创建（KN_JAVA_CLASS）
  - a. struct
  - b. class
  - c. interface
  - 学习者作答：辅助答对
  - 判题：correct=True，答案解析：Java 使用 class 关键字定义类；struct 是 C 语言结构体，interface 用于定义接口。
  - 观察[practice] 辅助后成功：支持'在帮助下可以完成'，不视为独立掌握（status=assisted，confidence=0.5）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（只有自述或低置信度证据，priority=0.8）

**第 7 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 集合与泛型 的掌握
- 题目：允许重复元素、按插入顺序访问的集合是？
- 知识点：集合与泛型（KN_JAVA_COLLECTION）
  - a. HashSet
  - b. ArrayList
  - c. HashMap
  - 学习者作答：独立答对
  - 判题：correct=True，答案解析：ArrayList 允许重复、保持插入顺序；HashSet 去重无序。
  - 观察[knowledge] 独立答对：verified_once（1 道不同题）（status=verified_once，confidence=0.65）
  - 观察[practice] 独立完成：独立性 -> applied（status=applied，confidence=0.7）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（只有自述或低置信度证据，priority=0.8）

**第 8 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 封装与访问控制 的掌握
- 题目：private 的 scores 字段，外部类应该如何安全读取？
- 知识点：封装与访问控制（KN_JAVA_ENCAPSULATION）
  - a. 直接访问 stu.scores
  - b. 通过 stu 提供的 getter 方法
  - c. 通过反射读取
  - 学习者作答：独立答对
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（只有自述或低置信度证据，priority=0.8）

### 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束） · 结束
- 会话状态：completed；recommended_next_action：start_remediation

**五核投影（knowledge 摘要）**
- KN_JAVA_POLYMORPHISM: status=verified_once confidence=0.65 evidence={'distinct_independent_correct': 1, 'wrong': 0, 'skipped': 0, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': ['D-POLY-1'], 'correct_question_ids': ['D-POLY-1']}
- KN_JAVA_IO: status=candidate confidence=0.3 evidence={'distinct_independent_correct': 0, 'wrong': 1, 'skipped': 0, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 1, 'distinct_question_ids': ['D-IO-1']}
- KN_JAVA_INHERITANCE: status=verified_once confidence=0.65 evidence={'distinct_independent_correct': 1, 'wrong': 0, 'skipped': 0, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': ['D-INHERIT-1'], 'correct_question_ids': ['D-INHERIT-1']}
- KN_JAVA_CLASS: status=candidate confidence=0.5 evidence={'distinct_independent_correct': 0, 'wrong': 0, 'skipped': 0, 'hazy': 0, 'assisted': 1, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': ['D-CLASS-1']}
- KN_JAVA_COLLECTION: status=verified_once confidence=0.65 evidence={'distinct_independent_correct': 1, 'wrong': 0, 'skipped': 0, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': ['D-COLL-1'], 'correct_question_ids': ['D-COLL-1']}
- KN_JAVA_ENCAPSULATION: status=verified_once confidence=0.65 evidence={'distinct_independent_correct': 1, 'wrong': 0, 'skipped': 0, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': ['D-ENCAP-1'], 'correct_question_ids': ['D-ENCAP-1']}

**Memory Graph 摘要**
- Module[knowledge]: {'fact_count': 7, 'top_claims': ['知识点 KN_JAVA_POLYMORPHISM 当前状态为 verified_once：1 道不同题独立正确、0 次答错、0 次辅助成功', '知识点 KN_JAVA_IO 当前状态为 candidate：0 道不同题独立正确、1 次答错、0 次辅助成功', '误解候选 IO_STREAM_BASE：出现 1 次'], 'avg_confidence': 0.571}
- Module[practice]: {'fact_count': 5, 'top_claims': ['知识点 KN_JAVA_POLYMORPHISM 独立性为 applied', '知识点 KN_JAVA_INHERITANCE 独立性为 applied', '知识点 KN_JAVA_CLASS 独立性为 assisted'], 'avg_confidence': 0.66}
- Module[value]: {'fact_count': 1, 'top_claims': ['已确认学习目标 GOAL-JAVA-001（完成 Java 面向对象成绩管理实训）'], 'avg_confidence': 0.8}
- Claim[knowledge] 检测到误解候选（1 个知识点），建议先纠错再继续。（status=active）
- Claim[practice] 1 个知识点仅在辅助下成功，未达到独立实践水平。（status=active）


### 场景二 · 连续跳过（证据不足 / 未知状态）

- 会话：DISC-8aeb323bf74b
- 学习者：STU-DEMO-002，项目：PROJ-DEMO-002
- 目标候选：想学 Java 面向对象；期望产物：先看看
- 策略：{"seed": 20260811, "interaction_budget": 6, "followup_budget": 1, "skip_limit": 2, "complete_coverage": 0.5}

**第 1 轮 · 下一交互 = clarification**
> 目的：确认学习目标与期望产物：目标决定了本轮要降低哪部分不确定性
  - 学习者确认目标：完成 Java 面向对象成绩管理实训
  - 观察[value] 目标已确认：完成 Java 面向对象成绩管理实训

**第 2 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 多态与接口 的掌握
- 题目：以下哪项是多态发生的必要条件？
- 知识点：多态与接口（KN_JAVA_POLYMORPHISM）
  - a. 类必须是 final
  - b. 继承（或实现）并重写方法、父类引用指向子类对象
  - c. 所有字段必须是 public
  - 学习者跳过本题（不视为知识错误）
  - 观察[knowledge] 跳过本题：记录未作答，不视为知识错误（status=unknown，confidence=0.0）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（尚无评分证据，priority=1.0）

**第 3 轮 · 下一交互 = question**
> 目的：该知识点尚无评分证据，优先级最高；本问用于确认或排除对 多态与接口 的掌握
- 题目：接口可以有多实现，其核心价值是？
- 知识点：多态与接口（KN_JAVA_POLYMORPHISM）
  - a. 只约定行为契约，实现解耦
  - b. 让类拥有多个父类的方法体
  - c. 替代继承的所有场景
  - 学习者跳过本题（不视为知识错误）
  - 剩余不确定性示例：knowledge/KN_JAVA_CLASS（尚无评分证据，priority=1.0）

### 场景二 · 连续跳过（证据不足 / 未知状态） · 结束
- 会话状态：insufficient_evidence；recommended_next_action：continue_discovery

**五核投影（knowledge 摘要）**
- KN_JAVA_POLYMORPHISM: status=untested confidence=0.0 evidence={'distinct_independent_correct': 0, 'wrong': 0, 'skipped': 2, 'hazy': 0, 'assisted': 0, 'explained_ok': 0, 'need_review': 0, 'distinct_question_ids': []}

**Memory Graph 摘要**
- Module[value]: {'fact_count': 1, 'top_claims': ['已确认学习目标 GOAL-JAVA-001（完成 Java 面向对象成绩管理实训）'], 'avg_confidence': 0.8}


## 证据账本（Evidence Ledger 导出）

STU-DEMO-001 共 17 条事件：

| 时间 | 类型 | 目标 Kernel | 角色 | client_event_id |
|---|---|---|---|---|
| 05:51:53 | discovery_session_started | structure | interaction_log | start-DISC-23da5f997327 |
| 05:51:53 | goal_candidate_stated | value | self_reported | candidate-DISC-23da5f997327 |
| 05:51:53 | goal_confirmed | value,structure | self_reported | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-confirm |
| 05:51:53 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-POLY-1 |
| 05:51:53 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q2 |
| 05:51:53 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-IO-1 |
| 05:51:53 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q3 |
| 05:51:53 | reasoning_explained | knowledge | self_reported | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-probe4 |
| 05:51:53 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-INHERIT-1 |
| 05:51:53 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q5 |
| 05:51:53 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-CLASS-1 |
| 05:51:53 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q6 |
| 05:51:53 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-COLL-1 |
| 05:51:53 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q7 |
| 05:51:54 | question_presented | structure | interaction_log | present-DISC-23da5f997327-D-ENCAP-1 |
| 05:51:54 | answer_submitted | knowledge,practice | graded_attempt | 场景一 · 综合学习者（动态选题 + 追问 + 辅助 + 提前结束）-q8 |
| 05:51:54 | discovery_session_completed | structure | interaction_log | complete-DISC-23da5f997327-completed |
