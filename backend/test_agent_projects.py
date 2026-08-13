"""项目层（agent 形态）接口集成测试：创建/列表/详情/测评/讲解。

与 test_backend.py 同风格：临时 DB + mock 模式 + 真实 HTTP 请求。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.server import Settings, create_server


class AgentProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "test.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
        )
        self.server = create_server(settings)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.student_id = "STU-AGENT-001"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request_json(self, method, path, payload=None, timeout=5):
        import urllib.request

        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_project(self, text):
        return self.request_json(
            "POST", "/api/projects", {"student_id": self.student_id, "text": text}
        )

    def test_create_project_matches_graph_goal(self):
        result = self.create_project("我想系统掌握 Java 面向对象编程")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        self.assertEqual(project["status"], "created")
        self.assertEqual(project["diagnosis_state"], "not_started")
        self.assertEqual(project["planning_state"], "ready")
        self.assertIn("project_id", project)

    def test_supported_goal_preserves_user_constraints(self):
        result = self.create_project(
            "我想在两个月内掌握 Java 面向对象，并能独立完成学生成绩管理系统"
        )
        project = result["project"]
        self.assertIn("两个月内", project["goal_name"])
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["goal_constraints"]["estimated_days"], 60)
        self.assertIn("学生成绩管理系统", project["goal_constraints"]["target_outcome"])

    def test_clear_cross_domain_goal_creates_candidate_path(self):
        result = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        self.assertIn("Python 数据分析", project["goal_name"])
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["support_level"], "generated_scaffold")
        self.assertEqual(project["assessment_state"], "question_sources_pending")
        self.assertEqual(project["goal_constraints"]["estimated_days"], 42)
        detail = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertGreaterEqual(len(detail["learning_path"]["items"]), 3)
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("Pandas" in name for name in names))
        self.assertTrue(any("看板" in name for name in names))
        center = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/assessments?student_id={self.student_id}",
        )
        self.assertTrue(center["assessment_available"])
        self.assertFalse(center["formal_assessment_available"])
        self.assertEqual(
            [item["assessment_type"] for item in center["catalog"]],
            ["provisional_self_check"],
        )
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/assessments/start",
                {"student_id": self.student_id, "assessment_type": "initial_diagnostic"},
            )

    def test_candidate_project_provisional_self_check_never_updates_profile(self):
        project = self.create_project(
            "六周内掌握 Python 数据分析并完成销售数据看板"
        )["project"]
        project_id = project["project_id"]
        before = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        mastery_before = [item["mastery"] for item in before["learning_path"]["items"]]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "provisional_self_check",
            },
        )
        self.assertEqual(started["stakes"], "low")
        self.assertTrue(started["questions"])
        self.assertTrue(
            all(question["quality_status"] == "unverified" for question in started["questions"])
        )
        completed = None
        for _question in started["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "selected": "c",
                },
            )
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["summary"]["formal_evidence"])
        self.assertEqual(completed["summary"]["evidence_count"], 0)
        evidence = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments/{started['assessment_id']}/evidence?student_id={self.student_id}",
        )["events"]
        self.assertEqual(evidence, [])
        after = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(
            [item["mastery"] for item in after["learning_path"]["items"]],
            mastery_before,
        )

    def test_clear_certification_goal_is_not_forced_to_java(self):
        result = self.create_project("三个月内通过大学英语四级考试")
        project = result["project"]
        self.assertIn("英语四级", project["goal_name"])
        self.assertEqual(project["goal_type"], "certification")
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["support_level"], "generated_scaffold")

    def test_named_non_java_certification_does_not_use_java_graph(self):
        project = self.create_project("两个月内通过 PMP 项目管理认证")["project"]
        self.assertEqual(project["goal_type"], "certification")
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertFalse(any("Java" in name or "类与对象" in name for name in names))
        self.assertTrue(any("绩效域" in name for name in names))
        self.assertTrue(any("敏捷" in name for name in names))

    def test_named_non_java_competition_does_not_use_java_graph(self):
        project = self.create_project("备战全国职业院校短视频创作大赛")["project"]
        self.assertEqual(project["goal_type"], "competition")
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("分镜" in name for name in names))
        self.assertTrue(any("剪辑" in name for name in names))
        self.assertTrue(any("参赛作品" in name for name in names))
        self.assertFalse(any("Java" in name or "类与对象" in name for name in names))
        self.assertNotIn("target_outcome", project["goal_constraints"])

    def test_unknown_learning_domain_keeps_goal_topic_in_path(self):
        project = self.create_project("掌握无人机航拍并完成校园宣传片")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("无人机航拍" in name for name in names))
        self.assertTrue(any("校园宣传片" in name for name in names))

    def test_create_project_matches_competition_keyword(self):
        result = self.create_project("备战世界职业院校技能大赛")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        detail = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(detail["goal_type"], "competition")

    def test_create_project_unmatched_returns_clarification(self):
        result = self.create_project("随便学点什么")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("clarification", result)

    def test_non_learning_request_returns_scope_boundary(self):
        result = self.create_project("帮我订机票去北京")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["reason"], "outside_learning_scope")
        self.assertIn("学习", result["clarification"])

    def test_list_projects_and_detail(self):
        self.assertEqual(self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"], [])
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]

        listed = self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["project_id"], project_id)

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        path = detail["learning_path"]
        self.assertEqual(len(path["items"]), 7)
        self.assertEqual(path["items"][0]["status"], "current")
        self.assertEqual(detail["diagnosis_state"], "not_started")

    def test_portrait_reserves_graph_contract_only_for_job_goals(self):
        course = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        portrait = self.request_json(
            "GET", f"/api/students/{self.student_id}/portrait"
        )
        self.assertEqual(portrait["job_competency_graphs"], [])

        job = self.create_project("我想达到 Java 后端开发岗位要求")["project"]
        self.assertEqual(job["goal_type"], "job")
        portrait = self.request_json(
            "GET", f"/api/students/{self.student_id}/portrait"
        )
        graphs = portrait["job_competency_graphs"]
        self.assertEqual(len(graphs), 1)
        self.assertEqual(graphs[0]["project_id"], job["project_id"])
        self.assertEqual(graphs[0]["status"], "not_connected")
        self.assertEqual(graphs[0]["nodes"], [])
        self.assertEqual(graphs[0]["edges"], [])
        self.assertNotEqual(graphs[0]["project_id"], course["project_id"])

    def test_project_diagnosis_full_flow(self):
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/diagnosis/start",
            {"student_id": self.student_id},
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["goal"], "competition")
        questions = started["questions"]
        self.assertTrue(len(questions) >= 1)
        for question in questions:
            self.assertNotIn("answer", question)
            self.assertNotIn("explanation", question)

        summary = None
        for index, question in enumerate(questions):
            # 全部答错，确保产生薄弱点归因
            answer = self.request_json(
                "POST",
                f"/api/projects/{project_id}/diagnosis/answer",
                {"student_id": self.student_id, "selected": "a"},
            )
            if answer["status"] == "completed":
                summary = answer["summary"]
        self.assertIsNotNone(summary)
        self.assertIn("weak_points", summary)
        self.assertTrue(len(summary["weak_points"]) >= 1)

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["diagnosis_state"], "done")
        self.assertEqual(detail["weak_points"], summary["weak_points"])

    def test_project_diagnosis_rejects_unknown_project(self):
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                "/api/projects/PROJ-UNKNOWN/diagnosis/start",
                {"student_id": self.student_id},
            )

    def test_assessment_center_lists_three_types_and_history(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        self.assertEqual(
            {item["assessment_type"] for item in center["catalog"]},
            {"initial_diagnostic", "stage_check", "self_check"},
        )
        self.assertEqual(center["history"], [])

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        knowledge_point_id = detail["learning_path"]["items"][0]["knowledge_point_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "self_check",
                "knowledge_point_id": knowledge_point_id,
            },
        )
        self.assertEqual(started["assessment_type"], "self_check")
        self.assertEqual(started["stakes"], "low")
        self.assertTrue(started["source_policy"])
        for question in started["questions"]:
            self.assertEqual(question["quality_status"], "reviewed")
            self.assertIn("source_type", question)
            self.assertNotIn("answer", question)

        completed = None
        for _question in started["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "selected": "a",
                },
            )
        self.assertEqual(completed["status"], "completed")

        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        self.assertEqual(len(center["history"]), 1)
        self.assertEqual(center["history"][0]["status"], "completed")
        evidence = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments/{started['assessment_id']}/evidence"
            f"?student_id={self.student_id}",
        )
        self.assertEqual(len(evidence["events"]), len(started["questions"]))
        self.assertTrue(all(event["evidence_role"] == "practice" for event in evidence["events"]))

    def test_stage_check_uses_distinct_evidence_to_unlock_path(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "stage_check",
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]
        self.assertGreaterEqual(len(session["questions"]), 2)
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "selected": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        update = next(
            item
            for item in completed["summary"]["knowledge_updates"]
            if item["knowledge_point_id"] == target["knowledge_point_id"]
        )
        self.assertEqual(update["evidence_status"], "verified_once")
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        updated_target = detail["learning_path"]["items"][0]
        self.assertEqual(updated_target["status"], "completed")
        self.assertEqual(updated_target["mastery_model"], "evidence_rule_v1")
        self.assertTrue(updated_target["mastery_is_estimated"])

    def test_project_explain_returns_teaching_package(self):
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        first = detail["learning_path"]["items"][0]
        explanation = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(explanation["status"], "ok")
        self.assertTrue(explanation["lesson_title"])
        self.assertTrue(len(explanation["content_blocks"]) >= 1)
        self.assertEqual(explanation["knowledge_point_id"], first["knowledge_point_id"])
        self.assertTrue(explanation["generated_with_path"])

    def test_project_creation_pregenerates_every_lesson_before_click(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        items = detail["learning_path"]["items"]
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(item["lesson_generation_status"] == "ready" for item in items))
        application = self.server.RequestHandlerClass.application
        for item in items:
            cached = application.store.get_project_lesson(
                project["project_id"], self.student_id, item["knowledge_point_id"]
            )
            self.assertEqual(cached["status"], "ready")
            self.assertTrue(cached["lesson"]["content_blocks"])

    def test_clicking_ready_lesson_only_reads_pregenerated_cache(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        application = self.server.RequestHandlerClass.application
        original = application._generate_project_lesson
        application._generate_project_lesson = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("点击章节时不应生成讲解")
        )
        try:
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": target["knowledge_point_id"],
                },
            )
        finally:
            application._generate_project_lesson = original
        self.assertEqual(explanation["status"], "ok")
        self.assertTrue(explanation["generated_with_path"])

    def test_video_candidates_filter_relevance_then_sort_by_play_count(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "current_knowledge_point": {
                "knowledge_point_id": "KN_PANDAS_CLEAN",
                "knowledge_point_name": "Pandas 数据清洗",
            },
            "web_search_context": {
                "status": "ok",
                "provider": "bilibili",
                "results": [
                    {
                        "type": "video",
                        "title": "Pandas 数据清洗入门",
                        "url": "https://www.bilibili.com/video/BV1LowPlay",
                        "play_count": 1200,
                        "play_count_text": "1200",
                    },
                    {
                        "type": "video",
                        "title": "Pandas 数据清洗完整教程",
                        "url": "https://www.bilibili.com/video/BV1HighPlay",
                        "play_count": 86000,
                        "play_count_text": "8.6万",
                    },
                    {
                        "type": "video",
                        "title": "热门游戏直播回放",
                        "url": "https://www.bilibili.com/video/BV1Irrelevant",
                        "play_count": 9_000_000,
                        "play_count_text": "900万",
                    },
                ],
            },
        }
        result = {"resources": []}
        application._merge_video_resources(result, context)
        videos = [item for item in result["resources"] if item["type"] == "video"]
        self.assertEqual(
            [item["url"] for item in videos],
            [
                "https://www.bilibili.com/video/BV1HighPlay",
                "https://www.bilibili.com/video/BV1LowPlay",
            ],
        )

    def test_bilibili_popularity_parser_and_cross_domain_filter(self):
        application = self.server.RequestHandlerClass.application
        search = application.video_search
        self.assertEqual(search._parse_count_text("168.6万"), 1_686_000)
        self.assertEqual(search._parse_count_text("6949"), 6949)
        self.assertIsNone(search._parse_count_text("播放量未知"))
        self.assertTrue(search._bilibili_title_relevant(
            "2026 最新 HTML 标签入门教程", "HTML 页面结构 教学 教程"
        ))
        self.assertTrue(search._bilibili_title_relevant(
            "Pandas 数据读取与清洗完整教程", "Pandas 数据读取与清洗 教学 教程"
        ))
        self.assertFalse(search._bilibili_title_relevant(
            "王者荣耀 HTML 活动页", "HTML 页面结构 教学 教程"
        ))

    def test_custom_goal_explain_uses_labeled_candidate_fallback(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        first = detail["learning_path"]["items"][0]
        explanation = self.request_json(
            "POST",
            f"/api/projects/{project['project_id']}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(explanation["status"], "ok")
        self.assertEqual(explanation["source_status"], "candidate_unverified")
        self.assertIn("Python", explanation["lesson_title"])
        content = json.dumps(explanation["content_blocks"], ensure_ascii=False)
        self.assertIn("待权威来源复核", content)
        self.assertNotIn("Java 封装", content)

    def test_custom_goal_remote_explain_returns_ai_markdown_body(self):
        gateway = self.server.RequestHandlerClass.application.gateway
        gateway.settings = Settings(
            **{**gateway.settings.__dict__, "xingchen_mode": "remote"}
        )
        original_invoke = gateway.invoke_chat_workflow
        gateway.invoke_chat_workflow = lambda payload: {
            "status": "ok",
            "answer": (
                "### 核心概念\n\nPython 数据处理先要区分原始数据、转换过程和输出结果，"
                "并为缺失值和类型转换建立明确规则。\n\n"
                "### 最小示例\n\n```python\nrows = [1, None, 3]\n"
                "clean = [value for value in rows if value is not None]\nprint(clean)\n```\n\n"
                "### 常见误区\n\n不要把缺失值直接当成零；两者表达的业务含义不同。\n\n"
                "### 动手练习\n\n读取一组包含空值的数据，清洗后输出有效记录数量。"
            ),
        }
        try:
            project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            first = detail["learning_path"]["items"][0]
            application = self.server.RequestHandlerClass.application
            deadline = time.time() + 5
            while time.time() < deadline:
                cached = application.store.get_project_lesson(
                    project["project_id"], self.student_id, first["knowledge_point_id"]
                )
                if cached and cached["status"] == "ready":
                    break
                time.sleep(0.02)
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": first["knowledge_point_id"],
                },
            )
        finally:
            gateway.invoke_chat_workflow = original_invoke

        self.assertEqual(explanation["source_status"], "candidate_unverified")
        self.assertTrue(explanation["ai_generated"])
        self.assertEqual(explanation["workflow_mode"], "candidate_ai_generation")
        knowledge_block = next(
            block for block in explanation["content_blocks"]
            if block["type"] == "concept"
        )
        self.assertIn("```python", knowledge_block["markdown"])
        self.assertIn("AI 生成候选内容", knowledge_block["source"])

    def test_custom_goal_short_remote_explain_falls_back_honestly(self):
        gateway = self.server.RequestHandlerClass.application.gateway
        gateway.settings = Settings(
            **{**gateway.settings.__dict__, "xingchen_mode": "remote"}
        )
        original_invoke = gateway.invoke_chat_workflow
        gateway.invoke_chat_workflow = lambda payload: {"status": "ok", "answer": "内容生成中"}
        try:
            project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            first = detail["learning_path"]["items"][0]
            application = self.server.RequestHandlerClass.application
            deadline = time.time() + 5
            while time.time() < deadline:
                cached = application.store.get_project_lesson(
                    project["project_id"], self.student_id, first["knowledge_point_id"]
                )
                if cached and cached["status"] == "ready":
                    break
                time.sleep(0.02)
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": first["knowledge_point_id"],
                },
            )
        finally:
            gateway.invoke_chat_workflow = original_invoke

        self.assertTrue(explanation["fallback_used"])
        self.assertIn("仅展示导学框架", explanation["source_notice"])
        self.assertEqual(explanation["source_status"], "candidate_unverified")

    def test_project_explain_unknown_knowledge_point(self):
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/explain",
                {"student_id": self.student_id, "knowledge_point_id": "KN_UNKNOWN"},
            )

    def test_multiple_projects_are_isolated(self):
        first = self.create_project("备战世界职业院校技能大赛")["project"]
        second = self.create_project("完成 Java 面向对象成绩管理实训")["project"]
        self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/diagnosis/start",
            {"student_id": self.student_id},
        )
        listed = self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"]
        by_id = {item["project_id"]: item for item in listed}
        self.assertEqual(by_id[first["project_id"]]["diagnosis_state"], "in_progress")
        self.assertEqual(by_id[second["project_id"]]["diagnosis_state"], "not_started")

    # ---------- Tutor Agent 统一编排 ----------

    def agent_turn(self, message, project_id="", session_id="agent-test"):
        return self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": session_id,
                "project_id": project_id,
                "message": message,
            },
        )

    def test_agent_turn_creates_project_and_recommends_assessment(self):
        result = self.agent_turn("我想系统掌握 Java 面向对象编程")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "create_project")
        self.assertEqual(result["action"], "project_created")
        self.assertIn("project_id", result["project"])
        self.assertEqual(result["next_interaction"]["type"], "choice")

    def test_agent_turn_routes_cross_domain_goal_to_knowledge_planning(self):
        result = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")
        self.assertEqual(result["intent"], "create_project")
        self.assertEqual(result["action"], "project_created")
        self.assertEqual(result["project"]["planning_state"], "ready")
        self.assertEqual(result["project"]["assessment_state"], "question_sources_pending")
        self.assertEqual(result["next_interaction"]["type"], "status")
        self.assertIn("候选学习路径", result["message"])

    def test_agent_turn_builds_goal_from_multiturn_intake(self):
        first = self.agent_turn("我想学 Python，我是零基础，每天只能学半小时")
        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(first["intent"], "clarify_goal")
        self.assertIn("可验收", first["message"])

        second = self.agent_turn("想做销售数据看板")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["action"], "project_created")
        constraints = second["project"]["goal_constraints"]
        self.assertIn("销售数据看板", constraints["target_outcome"])
        self.assertEqual(constraints["daily_minutes"], 30)
        self.assertEqual(constraints["current_level"], "zero_foundation")
        self.assertTrue(constraints["duration_assumption"])
        self.assertNotIn("零基础", second["project"]["goal_name"])
        self.assertNotIn("半小时", second["project"]["goal_name"])

        detail = self.request_json(
            "GET",
            f"/api/projects/{second['project']['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(detail["learner_preferences"]["daily_minutes"], 30)
        self.assertEqual(
            detail["learner_self_reports"][0]["verification_state"], "unverified"
        )
        messages = self.request_json(
            "GET",
            f"/api/projects/{second['project']['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        self.assertTrue(any("我想学 Python" in item["content"] for item in messages))
        self.assertTrue(any("销售数据看板" in item["content"] for item in messages))

    def test_goal_draft_is_isolated_by_session(self):
        first = self.agent_turn("我想学 Python", session_id="goal-session-a")
        self.assertEqual(first["intent"], "clarify_goal")

        unrelated = self.agent_turn("想做销售数据看板", session_id="goal-session-b")
        self.assertNotEqual(unrelated.get("action"), "project_created")

        completed = self.agent_turn("想做销售数据看板", session_id="goal-session-a")
        self.assertEqual(completed["action"], "project_created")

    def test_goal_question_does_not_consume_pending_draft(self):
        self.agent_turn("我想学 Python", session_id="goal-question")
        question = self.agent_turn("Python 是什么？", session_id="goal-question")
        self.assertEqual(question["intent"], "knowledge_question")
        completed = self.agent_turn("想做办公自动化", session_id="goal-question")
        self.assertEqual(completed["action"], "project_created")

    def test_general_assistant_request_does_not_consume_pending_goal(self):
        self.agent_turn("我想学 Python", session_id="goal-interrupt")
        interruption = self.agent_turn(
            "帮我解释一下 Java 封装", session_id="goal-interrupt"
        )
        self.assertEqual(interruption["intent"], "knowledge_question")
        completed = self.agent_turn("想做数据看板", session_id="goal-interrupt")
        self.assertEqual(completed["action"], "project_created")

    def test_general_assistant_routes_translation_without_creating_project(self):
        application = self.server.RequestHandlerClass.application
        original_settings = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **application.gateway.settings.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        captured = {}

        def answer_general(payload):
            captured.update(payload)
            return {"status": "ok", "answer": "Learning can begin today."}

        application.gateway.invoke_chat_workflow = answer_general
        try:
            result = self.agent_turn("请把‘今天可以开始学习’翻译成英文")
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_settings
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer_mode"], "general_generation")
        self.assertEqual(result["answer"], "Learning can begin today.")
        self.assertEqual(captured["assistant_mode"], "general")
        self.assertEqual(captured["source_kind"], "none")

    def test_unknown_general_question_routes_to_general_assistant(self):
        application = self.server.RequestHandlerClass.application
        original_mode = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **original_mode.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        application.gateway.invoke_chat_workflow = lambda _payload: {
            "status": "ok",
            "answer": "番茄工作法用专注时段与短休息交替管理注意力。",
        }
        try:
            result = self.agent_turn("番茄工作法有什么优缺点？")
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_mode
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["answer_mode"], "general_generation")

    def test_chat_defensively_upgrades_unknown_question_to_general_mode(self):
        application = self.server.RequestHandlerClass.application
        original_settings = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **original_settings.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        captured = {}

        def answer_general(payload):
            captured.update(payload)
            return {"status": "ok", "answer": "它有助于聚焦，但固定时段可能打断深度工作。"}

        application.gateway.invoke_chat_workflow = answer_general
        try:
            result = self.request_json(
                "POST",
                "/api/chat",
                {
                    "student_id": self.student_id,
                    "session_id": "defensive-general",
                    "message": "番茄工作法有什么优缺点？",
                    "assistant_mode": "education",
                    "allow_web_search": False,
                },
            )
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_settings
        self.assertEqual(captured["assistant_mode"], "general")
        self.assertEqual(result["answer_mode"], "general_generation")

    def test_explicit_web_search_is_not_misclassified_as_project(self):
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "web-search-test",
                "project_id": "",
                "message": "帮我上网搜索 Python 最新官方教程",
                "allow_web_search": True,
                "force_web_search": True,
            },
        )
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["web_searched"])
        self.assertNotEqual(result.get("action"), "project_created")

    def test_agent_turn_answers_knowledge_question_with_sources(self):
        result = self.agent_turn("什么是 Java 封装？")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "knowledge_question")
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["answer"])
        self.assertTrue(result["sources"])

    def test_agent_turn_clarifies_unknown_intent(self):
        result = self.agent_turn("随便来点")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["action"], "ask_clarification")
        self.assertTrue(result["clarify_options"])

    def test_agent_turn_clarifies_broad_learning_goal(self):
        result = self.agent_turn("随便学点什么")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["action"], "ask_clarification")
        self.assertIn("具体学什么", result["message"])

    def test_agent_turn_discloses_unavailable_external_action(self):
        result = self.agent_turn("帮我订机票去北京")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer_mode"], "tool_unavailable")
        self.assertIn("没有接入机票预订工具", result["answer"])

    def test_agent_turn_starts_assessment_in_current_project(self):
        project = self.agent_turn("备战世界职业院校技能大赛")["project"]
        result = self.agent_turn("开始能力测评", project["project_id"])
        self.assertEqual(result["action"], "show_assessment")
        self.assertEqual(result["artifact"]["type"], "assessment")
        self.assertGreaterEqual(result["artifact"]["data"]["total"], 1)

    def test_agent_turn_opens_named_lesson(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        result = self.agent_turn("开始学习类的定义与对象创建", project["project_id"])
        self.assertEqual(result["action"], "open_lesson")
        self.assertEqual(result["artifact"]["type"], "lesson")
        self.assertTrue(result["artifact"]["data"]["content_blocks"])

    def test_project_lesson_falls_back_when_workflow_fails(self):
        application = self.server.RequestHandlerClass.application
        original = application.gateway.invoke_learning_workflow

        def fail_workflow(_payload):
            raise RuntimeError("temporary workflow failure")

        application.gateway.invoke_learning_workflow = fail_workflow
        try:
            project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            target = detail["learning_path"]["items"][0]
            result = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": target["knowledge_point_id"],
                },
            )
        finally:
            application.gateway.invoke_learning_workflow = original
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["source_status"], "verified_local_fallback")
        self.assertTrue(result["content_blocks"])
        self.assertTrue(result["content_version"])
        self.assertTrue(
            all(block.get("block_id") for block in result["content_blocks"])
        )
        self.assertTrue(
            all("markdown" in block for block in result["content_blocks"])
        )

    def test_agent_turn_understands_learning_time_and_self_report(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        result = self.agent_turn(
            "我每天只能学半小时，而且类和对象已经会了", project["project_id"]
        )
        self.assertEqual(result["intent"], "update_learning_context")
        self.assertEqual(result["action"], "context_updated")
        self.assertEqual(result["context_update"]["learner_preferences"]["daily_minutes"], 30)
        self.assertEqual(result["context_update"]["verification_state"], "unverified")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["learner_preferences"]["daily_minutes"], 30)
        first = detail["learning_path"]["items"][0]
        self.assertEqual(first["mastery"], 0)
        self.assertTrue(detail["learner_self_reports"])

    def test_project_messages_are_persisted_and_isolated(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        self.agent_turn("我每天可以学习 30 分钟", first["project_id"])
        self.agent_turn("我喜欢先看案例，再解释原理", second["project_id"])
        first_messages = self.request_json(
            "GET",
            f"/api/projects/{first['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        second_messages = self.request_json(
            "GET",
            f"/api/projects/{second['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        first_text = " ".join(item["content"] for item in first_messages)
        second_text = " ".join(item["content"] for item in second_messages)
        self.assertIn("30 分钟", first_text)
        self.assertNotIn("先看案例", first_text)
        self.assertIn("先看案例", second_text)
        self.assertNotIn("30 分钟", second_text)

    def test_project_notes_are_scoped_editable_and_deletable(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{first['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        lesson = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        block = lesson["content_blocks"][0]
        created = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
                "knowledge_point_name": target["knowledge_point_name"],
                "content_version": lesson["content_version"],
                "block_id": block["block_id"],
                "block_title": block.get("title") or "讲解内容",
                "quote_text": "稳定锚点",
                "quote_prefix": "前文",
                "quote_suffix": "后文",
                "note_markdown": "**第一条**笔记",
            },
        )["note"]
        listed = self.request_json(
            "GET",
            f"/api/projects/{first['project_id']}/notes?student_id={self.student_id}"
            f"&knowledge_point_id={target['knowledge_point_id']}",
        )["notes"]
        self.assertEqual([item["note_id"] for item in listed], [created["note_id"]])
        self.assertEqual(listed[0]["content_version"], lesson["content_version"])
        self.assertEqual(
            self.request_json(
                "GET",
                f"/api/projects/{second['project_id']}/notes?student_id={self.student_id}",
            )["notes"],
            [],
        )

        updated_payload = {
            **created,
            "student_id": self.student_id,
            "note_markdown": "更新后的笔记",
        }
        updated = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            updated_payload,
        )["note"]
        self.assertEqual(updated["note_id"], created["note_id"])
        self.assertEqual(updated["note_markdown"], "更新后的笔记")
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{second['project_id']}/notes",
                {**updated_payload, "note_markdown": "跨项目篡改"},
            )
        deleted = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes/delete",
            {"student_id": self.student_id, "note_id": created["note_id"]},
        )
        self.assertEqual(deleted["deleted_note_id"], created["note_id"])
        self.assertEqual(
            self.request_json(
                "GET",
                f"/api/projects/{first['project_id']}/notes?student_id={self.student_id}",
            )["notes"],
            [],
        )

    def test_project_delete_checks_owner_and_removes_project_scoped_data(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        project_id = first["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        lesson = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/notes",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
                "knowledge_point_name": target["knowledge_point_name"],
                "content_version": lesson["content_version"],
                "block_id": lesson["content_blocks"][0]["block_id"],
                "block_title": "讲解内容",
                "note_markdown": "删除项目时应一并删除",
            },
        )
        assessment = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "initial_diagnostic",
            },
        )
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/answer",
            {
                "student_id": self.student_id,
                "assessment_id": assessment["assessment_id"],
                "selected": "a",
            },
        )
        discovery = self.request_json(
            "POST",
            "/api/discovery/sessions",
            {
                "learner_id": self.student_id,
                "project_id": project_id,
                "goal_candidate": first["goal_name"],
            },
        )
        self.assertTrue(discovery["session"]["session_id"])

        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/delete",
                {"student_id": "STU-OTHER"},
            )

        deleted = self.request_json(
            "POST",
            f"/api/projects/{project_id}/delete",
            {"student_id": self.student_id},
        )
        self.assertEqual(deleted["deleted_project_id"], project_id)
        self.assertGreaterEqual(deleted["deleted_records"]["project_messages"], 1)
        self.assertEqual(deleted["deleted_records"]["project_notes"], 1)
        self.assertEqual(deleted["deleted_records"]["assessment_runs"], 1)
        self.assertGreaterEqual(deleted["deleted_records"]["assessment_evidence"], 1)
        self.assertEqual(deleted["deleted_records"]["ld_discovery_sessions"], 1)

        listed = self.request_json(
            "GET", f"/api/projects?student_id={self.student_id}"
        )["projects"]
        self.assertEqual([item["project_id"] for item in listed], [second["project_id"]])
        with self.assertRaises(Exception):
            self.request_json(
                "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
            )

    def test_selected_lesson_excerpt_drives_answer_and_message_context(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][1]
        selected_text = "对象的状态应该通过受控方法访问"
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "selected-lesson-test",
                "project_id": project["project_id"],
                "message": "为什么要这样设计？",
                "workspace_context": {"view": "blank"},
                "selection_context": {
                    "selected_text": selected_text,
                    "block_id": "BLOCK-TEST",
                    "block_title": "核心概念",
                    "knowledge_point_id": target["knowledge_point_id"],
                    "knowledge_point_name": target["knowledge_point_name"],
                },
            },
        )
        self.assertEqual(result["action"], "reply")
        self.assertIn(selected_text, result["answer"])
        messages = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        user_message = next(
            item for item in reversed(messages) if item["role"] == "user"
        )
        self.assertEqual(
            user_message["context"]["selection_context"]["selected_text"],
            selected_text,
        )

    def test_agent_turn_records_preferred_topic_without_skipping_prerequisites(self):
        project = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        result = self.agent_turn("我想先学 Pandas", project["project_id"])
        self.assertEqual(result["action"], "context_updated")
        self.assertIn("优先学习", result["message"])
        self.assertIn("前置知识", result["message"])
        self.assertEqual(result["context_update"]["verification_state"], "unverified")

    def test_candidate_project_question_never_uses_java_knowledge(self):
        project = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        result = self.agent_turn("Pandas 怎么清洗缺失值？", project["project_id"])
        self.assertEqual(result["intent"], "knowledge_question")
        self.assertEqual(result["action"], "reply")
        self.assertIn("还没有绑定", result["answer"])
        self.assertNotIn("Java", result["answer"])

    def test_chat_prefers_active_lesson_knowledge_context(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][1]
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "agent-test",
                "project_id": project["project_id"],
                "message": "为什么要这么设计？",
                "workspace_context": {
                    "view": "lesson",
                    "project_id": project["project_id"],
                    "knowledge_point_id": target["knowledge_point_id"],
                    "knowledge_point_name": target["knowledge_point_name"],
                },
            },
        )
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["answer"])
        self.assertTrue(result["sources"])

    # ---------- 生成式题库 ----------

    def test_generated_quiz_goes_through_validation_and_persistence(self):
        """mock 出题走"生成→校验→入库"链路：provider=mock_bank（如实标注），题库可查。"""
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/diagnosis/start",
            {"student_id": self.student_id},
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["provider"], "mock_bank")
        self.assertGreaterEqual(len(started["questions"]), 1)
        # 生成的题已入库（幂等写入，可复用）
        application = self.server.RequestHandlerClass.application
        persisted = application.domain.recent_generated_questions(limit=50)
        self.assertGreaterEqual(len(persisted), len(started["questions"]))
        persisted_ids = {q["question_id"] for q in persisted}
        for question in started["questions"]:
            self.assertIn(question["question_id"], persisted_ids)

    def test_quiz_validation_filters_invalid_questions(self):
        """校验器：答案不在选项 / 选项不足 / 缺字段的生成题被丢弃。"""
        application = self.server.RequestHandlerClass.application
        questions = [
            {"question_id": "Q-OK-1", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "合法题", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "b", "explanation": "解析", "difficulty": 2},
            {"question_id": "Q-BAD-1", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "答案不在选项", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "z", "explanation": "解析", "difficulty": 1},
            {"question_id": "Q-BAD-2", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "选项不足", "options": {"a": "1", "b": "2"},
             "answer": "a", "explanation": "解析", "difficulty": 1},
            {"question_id": "Q-BAD-3", "knowledge_point_id": "",
             "title": "无知识点绑定", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "a", "explanation": "解析", "difficulty": 1},
            "not-a-dict",
        ]
        valid, dropped = application._validate_quiz_questions(questions)
        self.assertEqual(len(valid), 1)
        self.assertEqual(dropped, 4)
        self.assertEqual(valid[0]["question_id"], "Q-OK-1")

    def test_quiz_generation_falls_back_to_local_bank(self):
        """工作流出题异常 → 自动回落本地取样，诊断流程不中断。"""
        from unittest.mock import patch

        application = self.server.RequestHandlerClass.application
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        with patch.object(
            application.gateway, "invoke_quiz_workflow", side_effect=RuntimeError("platform down")
        ):
            started = self.request_json(
                "POST",
                f"/api/projects/{project_id}/diagnosis/start",
                {"student_id": self.student_id},
            )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["provider"], "local_fallback")
        self.assertGreaterEqual(len(started["questions"]), 1)


if __name__ == "__main__":
    unittest.main()
