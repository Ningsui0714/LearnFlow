# 学习路径生成相关源码

本包对应当前项目中“目标理解 → 知识图谱/候选节点 → 依赖排序 → 学习者自述个性化 → 学习地图与计划投影”的源码和测试。

## 核心生成链路

1. `backend/server.py`
   - 项目创建、目标解析和正式/候选路径分流。
   - `_build_custom_learning_path`：为未绑定正式能力包的目标生成候选路径。
   - `_personalize_initial_learning_path`：根据基础自述调整节奏和重点，不把自述当作掌握度。
   - `project_assessment_intake`：完成基础问卷后生成面向用户的路径。
2. `backend/goal_engine.py`
   - 正式目标归一化、知识点依赖拓扑排序和基础路径生成。
3. `backend/data/goal_graph.py`
   - 正式目标、知识点元数据和前置依赖关系。

## 相关投影与理解模块

- `backend/dialogue_understanding.py`：识别学习目标、主题范围和用户自述。
- `backend/plan_context.py`：基于正式证据构建计划上下文。
- `backend/learning_map.py`：将当前路径投影为学习地图。
- `backend/plan_brief.py`：生成面向用户的计划说明。
- `frontend/agent.html`：问卷、路径、学习地图和计划的页面交互展示。

## 测试与文档

- `backend/test_agent_projects.py`
- `backend/test_dialogue_understanding.py`
- `backend/数据传递说明.md`
- `docs/知行课径项目改进交接文档.md`

## 说明

- 包内源码是从项目当前工作区复制的快照，不包含 `backend/.env`、数据库、日志或密钥。
- 修改路径生成时，优先检查 `server.py` 与 `goal_engine.py` 的调用关系，再同步相关测试和数据传递文档。
