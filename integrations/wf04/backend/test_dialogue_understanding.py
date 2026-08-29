import unittest

from backend.dialogue_understanding import recent_subject, understand_turn


class DialogueUnderstandingTests(unittest.TestCase):
    def test_mixed_question_goal_and_self_report_are_preserved(self):
        result = understand_turn(
            "我零基础，先解释一下 Python 变量，再帮我规划 Python 学习"
        )
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertIn("goal_discovery", result["secondary_intents"])
        self.assertEqual(result["topic"]["subject"], "python")
        self.assertTrue(result["learner_claims"])
        self.assertEqual(
            result["learner_claims"][0]["verification_state"], "unverified"
        )

    def test_data_type_is_foundation_not_data_analysis(self):
        result = understand_turn("我想学习 Python 数据类型基础")
        self.assertEqual(result["topic"]["subject"], "python")
        self.assertEqual(result["topic"]["learning_scope"], "foundation")

    def test_explicit_data_analysis_stays_data_analysis(self):
        result = understand_turn("我想用 Python 和 Pandas 完成销售数据分析看板")
        self.assertEqual(result["topic"]["learning_scope"], "data_analysis")

    def test_project_goal_extracts_outcome_and_time(self):
        result = understand_turn("我想用 Python 做销售数据看板，每周 6 小时，准备 3 个月完成")
        self.assertEqual(result["primary_intent"], "create_project")
        self.assertEqual(result["goal"]["goal_type"], "project")
        self.assertEqual(result["goal"]["target_outcome"], "销售数据看板")
        self.assertEqual(result["goal"]["application_scenario"], "data_analysis")
        self.assertEqual(result["goal"]["constraints"]["weekly_time"], "6小时")
        self.assertEqual(result["goal"]["constraints"]["duration"], "3个月")

    def test_job_goal_is_distinct_from_course_learning(self):
        result = understand_turn("我想转行做后端开发，半年内找到工作")
        self.assertEqual(result["goal"]["goal_type"], "job")
        self.assertEqual(result["goal"]["target_outcome"], "后端开发，半年内找到工作")
        self.assertIn("current_level", result["goal"]["missing_information"])

    def test_certification_and_competition_are_separate_goal_types(self):
        certification = understand_turn("我准备考软考，想系统学习 Java")
        competition = understand_turn("我想参加程序设计竞赛，提升算法能力")
        self.assertEqual(certification["goal"]["goal_type"], "certification")
        self.assertEqual(competition["goal"]["goal_type"], "competition")

    def test_remedial_goal_is_not_treated_as_new_course(self):
        result = understand_turn("我想补 Python 循环和函数基础，总是做错题")
        self.assertEqual(result["goal"]["goal_type"], "remedial")
        self.assertEqual(result["topic"]["subject"], "python")

    def test_knowledge_question_has_no_false_target_outcome(self):
        result = understand_turn("Python 的列表和元组有什么区别？")
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertEqual(result["goal"]["target_outcome"], "")
        self.assertEqual(result["goal"]["missing_information"], [])

    def test_common_subjects_and_job_deadline_are_normalized(self):
        result = understand_turn("我想转行做后端开发，半年内找到工作")
        self.assertEqual(result["topic"]["subject"], "")
        self.assertEqual(result["goal"]["constraints"]["duration"], "半年")
        sql = understand_turn("我想系统学习 SQL，之后能独立设计数据库")
        self.assertEqual(sql["topic"]["subject"], "sql")
        self.assertEqual(sql["goal"]["goal_type"], "course")

    def test_project_markers_cover_build_and_training_requests(self):
        result = understand_turn("我需要用机器学习训练一个图像分类模型")
        self.assertEqual(result["primary_intent"], "create_project")
        self.assertEqual(result["goal"]["goal_type"], "project")
        self.assertEqual(result["goal"]["application_scenario"], "machine_learning")

    def test_professional_group_questions_route_to_knowledge(self):
        cases = (
            ("软件技术都学什么", "software_technology"),
            ("计算机应用技术主要包含什么", "computer_application"),
            ("计算机网络技术方向有哪些内容", "computer_network"),
            ("大数据技术都包含什么", "big_data"),
            ("人工智能技术应用学什么", "ai_application"),
        )
        for message, subject in cases:
            with self.subTest(message=message):
                result = understand_turn(message)
                self.assertEqual(result["primary_intent"], "knowledge_question")
                self.assertEqual(result["topic"]["subject"], subject)

    # ---- 教育优先 + 历史感知（模块①）----

    def test_anaphoric_followup_inherits_previous_subject(self):
        # 「前端是什么」→「都包含什么内容」：无主题追问继承上轮主题，保持教育辅导
        result = understand_turn("都包含什么内容", previous_subject="javascript")
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertEqual(result["topic"]["subject"], "javascript")
        self.assertTrue(result["topic"]["inherited"])

    def test_anaphoric_followup_with_history_but_no_subject_is_clarified(self):
        # 有来龙去脉但连主题都没接上：教育式澄清，而不是静默降级通用助手
        result = understand_turn("都包含什么内容", has_history=True)
        self.assertEqual(result["primary_intent"], "clarify_intent")

    def test_full_question_with_history_stays_general_assistant(self):
        # 12 字完整独立提问，有历史也不该被误判为指代追问
        result = understand_turn("番茄工作法有什么优缺点？", has_history=True)
        self.assertEqual(result["primary_intent"], "general_assistant")

    def test_default_params_keep_original_behavior(self):
        # 不传 previous_subject/has_history → 与改动前行为一致
        result = understand_turn("都包含什么内容")
        self.assertEqual(result["primary_intent"], "general_assistant")
        self.assertNotIn("inherited", result["topic"])

    def test_project_starting_point_question_routes_to_learning_path(self):
        for message in ("要从哪里开始学", "我应该从哪学起", "先学什么"):
            with self.subTest(message=message):
                result = understand_turn(message, has_project=True)
                self.assertEqual(result["primary_intent"], "show_path")

    def test_recent_subject_scans_last_user_message_with_subject(self):
        messages = [
            {"role": "user", "content": "前端是什么"},
            {"role": "assistant", "content": "前端就是网页里我们看到和交互的部分…"},
            {"role": "user", "content": "都包含什么内容"},
        ]
        self.assertEqual(recent_subject(messages), "javascript")
        self.assertEqual(recent_subject([]), "")
        self.assertEqual(recent_subject([{"role": "assistant", "content": "前端"}]), "")

    # ---- F5/F6 收紧修复（审查回归）----

    def test_short_complete_question_does_not_inherit_previous_subject(self):
        # F5 收紧：≤6 字完整独立提问（「番茄钟是什么」）不是指代，不继承上轮主题
        result = understand_turn("番茄钟是什么", previous_subject="java", has_history=True)
        self.assertNotIn("inherited", result["topic"])
        self.assertNotEqual(result["topic"]["subject"], "java")

    def test_ne_particle_followup_routes_to_knowledge_question(self):
        # F6 修复：「那 getter 方法呢」继承主题并走知识问答
        result = understand_turn("那 getter 方法呢", previous_subject="java")
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertEqual(result["topic"]["subject"], "java")
        self.assertTrue(result["topic"]["inherited"])

    def test_anaphoric_continuation_without_marker_is_knowledge_question(self):
        # F6 兜底：已继承主题的续接（「再讲一下」）走知识问答而非通用助手
        result = understand_turn("再讲一下", previous_subject="java")
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertEqual(result["topic"]["subject"], "java")
        self.assertTrue(result["topic"]["inherited"])
