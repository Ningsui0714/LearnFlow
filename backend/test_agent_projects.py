"""项目层（agent 形态）接口集成测试：创建/列表/详情/测评/讲解。

与 test_backend.py 同风格：临时 DB + mock 模式 + 真实 HTTP 请求。
"""

import json
import tempfile
import threading
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
        self.assertIn("project_id", project)

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

    def agent_turn(self, message, project_id=""):
        return self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "agent-test",
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

    # ---------- 生成式题库 ----------

    def test_generated_quiz_goes_through_validation_and_persistence(self):
        """mock 出题走"生成→校验→入库"链路：provider=workflow，题库可查。"""
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/diagnosis/start",
            {"student_id": self.student_id},
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["provider"], "workflow")
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
