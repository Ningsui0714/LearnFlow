# Learner State Discovery · 最小 Eval 集报告

> seed=20260811 · 离线可重复 · 通过 8/8

| # | 场景 | 结果 | 详情 |
|---|---|---|---|
| 1 | 1.基础明显（全对 -> 提前结束） | ✅ | status=completed, recommended_next_action=begin_learning, 轮次=4 |
| 2 | 2.知识分布不均（对错混合 -> 分布可区分） | ✅ | KC 状态分布={'KN_JAVA_POLYMORPHISM': 'candidate', 'KN_JAVA_IO': 'verified_once', 'KN_JAVA_INHERITANCE': 'verified_once', 'KN_JAVA_CLASS': 'candidate'} |
| 3 | 3.连续跳过 -> 证据不足 | ✅ | 下一交互=complete, status=insufficient_evidence |
| 4 | 4.含糊回答 -> 澄清追问后恢复 | ✅ | 澄清后下一交互=question |
| 5 | 5.辅助后答对（不视为独立掌握） | ✅ | knowledge=['candidate'], practice=['assisted'] |
| 6 | 6.开放题无法可靠评分（need_review，不强行二分） | ✅ | matches_rubric=None -> need_review 记录保留原始回答 |
| 7 | 7.重复提交（幂等） | ✅ | answer_submitted 事件数=1 |
| 8 | 8.状态被后续证据纠正（verified_once -> 纠正 -> 重算） | ✅ | 纠正前=verified_once，纠正后=untested |
