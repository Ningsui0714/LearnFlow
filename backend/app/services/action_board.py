from dataclasses import dataclass


@dataclass(frozen=True)
class ActionDefinition:
    capability: str
    title: str
    side_effect: str
    confirmation_policy: str
    evidence_target: dict
    next_affordances: tuple[str, ...]


ACTION_BOARD = {
    item.capability: item for item in (
        ActionDefinition(
            "search_projects", "匹配已有学习项目", "none", "none",
            {"structure": "project_match"},
            ("enter_project", "draft_learning_project"),
        ),
        ActionDefinition(
            "draft_learning_project", "起草学习项目", "none", "none",
            {"value": "goal_draft", "practice": "artifact_draft"},
            ("create_project",),
        ),
        ActionDefinition(
            "revise_learning_project_proposal", "更新项目提案", "none", "none",
            {"structure": "proposal_revision", "knowledge": "prerequisite_draft",
             "human": "learning_pace_draft", "value": "goal_draft",
             "practice": "artifact_draft"},
            ("create_project", "search_learning_resources"),
        ),
        ActionDefinition(
            "search_learning_resources", "寻找候选学习来源", "none", "none",
            {"structure": "source_candidates", "practice": "resource_candidates"},
            ("add_source",),
        ),
        ActionDefinition(
            "create_project", "建立学习项目", "write", "explicit_or_card",
            {"structure": "project_selection", "value": "goal_confirmation"},
            ("add_source", "plan_learning_path"),
        ),
        ActionDefinition(
            "bootstrap_project", "建立项目并接入来源", "write", "explicit",
            {"structure": "project_selection", "practice": "source_ingested"},
            ("plan_learning_path",),
        ),
        ActionDefinition(
            "enter_project", "进入学习项目", "context", "click_or_explicit",
            {"structure": "project_selection"},
            ("add_source", "plan_learning_path", "navigate_checkpoint"),
        ),
        ActionDefinition(
            "add_source", "添加并处理来源", "write", "explicit_or_card",
            {"structure": "source_added", "practice": "source_processed"},
            ("plan_learning_path",),
        ),
        ActionDefinition(
            "plan_learning_path", "规划学习路线", "proposal", "explicit_or_card",
            {"structure": "roadmap_proposal"},
            ("apply_learning_path",),
        ),
        ActionDefinition(
            "apply_learning_path", "应用学习路线", "write", "explicit_or_card",
            {"structure": "roadmap_applied"},
            ("navigate_checkpoint",),
        ),
        ActionDefinition(
            "navigate_checkpoint", "进入检查点", "context", "click_or_explicit",
            {"structure": "checkpoint_entered"},
            ("generate_lecture", "generate_assessment"),
        ),
        ActionDefinition(
            "generate_lecture", "生成本关讲义", "artifact", "explicit_or_card",
            {"knowledge": "content_exposure"},
            ("generate_assessment",),
        ),
        ActionDefinition(
            "generate_assessment", "生成验证任务", "artifact", "explicit_or_card",
            {"knowledge": "assessment_attempt", "practice": "independent_attempt"},
            ("evaluate_attempt",),
        ),
        ActionDefinition(
            "evaluate_attempt", "评估本次尝试", "evidence", "explicit",
            {"knowledge": "graded_attempt", "practice": "verified_artifact"},
            ("request_remediation_explanation", "advance_checkpoint"),
        ),
        ActionDefinition(
            "request_remediation_explanation", "请求确定性纠错讲解", "evidence", "explicit",
            {"knowledge": "error_evidence", "human": "explanation_effect"},
            ("retry_attempt",),
        ),
        ActionDefinition(
            "retry_attempt", "重做原任务", "evidence", "explicit",
            {"knowledge": "retry_result", "practice": "assisted_attempt"},
            ("evaluate_transfer_variant", "advance_checkpoint"),
        ),
        ActionDefinition(
            "evaluate_transfer_variant", "完成变式验证", "evidence", "explicit",
            {"knowledge": "transfer_result", "practice": "transfer_attempt"},
            ("advance_checkpoint",),
        ),
        ActionDefinition(
            "explain_selection", "解释选中内容", "none", "explicit",
            {"knowledge": "explanation_exposure"},
            ("generate_assessment",),
        ),
        ActionDefinition(
            "advance_checkpoint", "推进下一关", "context", "explicit_or_click",
            {"structure": "checkpoint_entered"},
            ("generate_lecture", "generate_assessment"),
        ),
        ActionDefinition(
            "link_project_workspace", "关联本地项目目录", "write", "explicit",
            {},
            ("inspect_workspace_files",),
        ),
        ActionDefinition(
            "inspect_workspace_files", "查看项目文件", "none", "none",
            {},
            ("propose_workspace_change",),
        ),
        ActionDefinition(
            "propose_workspace_change", "提出项目文件修改", "proposal", "none",
            {},
            ("apply_workspace_change",),
        ),
        ActionDefinition(
            "apply_workspace_change", "确认并应用项目文件修改", "write", "explicit",
            {},
            ("inspect_workspace_files",),
        ),
        ActionDefinition(
            "open_managed_learning_artifact", "打开讲义/练习播放器", "none", "none",
            {},
            ("annotate_learning_artifact",),
        ),
        ActionDefinition(
            "edit_managed_lecture", "版本化修改讲义", "write", "explicit_or_click",
            {},
            ("open_managed_learning_artifact",),
        ),
        ActionDefinition(
            "annotate_learning_artifact", "批注讲义或练习", "write", "explicit_or_click",
            {},
            ("open_managed_learning_artifact",),
        ),
    )
}


def definition(capability: str) -> ActionDefinition:
    return ACTION_BOARD[capability]
