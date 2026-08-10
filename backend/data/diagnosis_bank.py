"""诊断题库数据驱动（P1-2）。

将 server.py 内联的 DIAGNOSIS_BANK / DIAGNOSIS_GOALS 抽取为独立数据模块：
- 每题绑定 knowledge_point_id，供「答错 → 归因薄弱点」使用；
- 每题可声明适用目标（goals 缺省 = 全部目标）；
- 取样逻辑收敛为 select_diagnosis_questions(goal)，新增题目/目标只改数据不动逻辑。
"""

from typing import Any

# 诊断题库（mock 模式）：answer 只存在服务端，返回给前端时剔除。
DIAGNOSIS_BANK: list[dict[str, Any]] = [
    {
        "id": "D-CLASS-1", "knowledge_point_id": "KN_JAVA_CLASS",
        "knowledge_point_name": "类的定义与对象创建", "difficulty": 1,
        "title": "在 Java 中，定义类的关键字是？",
        "options": {"a": "struct", "b": "class", "c": "interface"},
        "answer": "b",
        "explanation": "Java 使用 class 关键字定义类；struct 是 C 语言结构体，interface 用于定义接口。",
    },
    {
        "id": "D-CLASS-2", "knowledge_point_id": "KN_JAVA_CLASS",
        "knowledge_point_name": "类的定义与对象创建", "difficulty": 2,
        "title": "创建 Student 对象 st 的正确语句是？",
        "options": {"a": "Student st = new Student();", "b": "Student st = Student();", "c": "new Student st;"},
        "answer": "a",
        "explanation": "new 关键字调用构造器创建对象实例，语法为 new Student()。",
    },
    {
        "id": "D-CERT-1", "knowledge_point_id": "KN_JAVA_CLASS",
        "knowledge_point_name": "类的定义与对象创建", "difficulty": 1,
        "title": "按 Java 命名规范，类名 StudentScore 符合哪条要求？",
        "options": {"a": "类名使用大驼峰命名", "b": "类名必须全大写", "c": "类名只能是小写字母"},
        "answer": "a",
        "explanation": "Java 命名规范要求类名大驼峰（StudentScore）、方法名小驼峰、常量全大写；1+X Java 应用开发证书考核包含命名规范要求。",
        "goals": ["certification"],
    },
    {
        "id": "D-ENCAP-1", "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
        "knowledge_point_name": "封装与访问控制", "difficulty": 2,
        "title": "private 的 scores 字段，外部类应该如何安全读取？",
        "options": {"a": "直接访问 stu.scores", "b": "通过 stu 提供的 getter 方法", "c": "通过反射读取"},
        "answer": "b",
        "explanation": "封装要求私有字段通过公开的 getter 方法访问，外部不得直接触碰内部数据。",
    },
    {
        "id": "D-ENCAP-2", "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
        "knowledge_point_name": "封装与访问控制", "difficulty": 3,
        "title": "getScores() 直接返回内部数组引用，存在什么风险？",
        "options": {"a": "调用方可以绕过校验修改内部数据", "b": "方法无法编译", "c": "数组会自动变成 null"},
        "answer": "a",
        "explanation": "返回内部引用会让外部直接改写数组内容，破坏封装；应返回副本或只读视图。",
    },
    {
        "id": "D-INHERIT-1", "knowledge_point_id": "KN_JAVA_INHERITANCE",
        "knowledge_point_name": "继承与方法重写", "difficulty": 1,
        "title": "子类继承父类使用的关键字是？",
        "options": {"a": "implements", "b": "extends", "c": "inherits"},
        "answer": "b",
        "explanation": "Java 类继承用 extends；implements 用于实现接口。",
    },
    {
        "id": "D-INHERIT-2", "knowledge_point_id": "KN_JAVA_INHERITANCE",
        "knowledge_point_name": "继承与方法重写", "difficulty": 3,
        "title": "子类重写 averageScore() 后，想调用父类被覆盖的版本，应该用？",
        "options": {"a": "super.averageScore()", "b": "this.averageScore()", "c": "父类名.averageScore()"},
        "answer": "a",
        "explanation": "super 关键字调用父类被重写的方法，用于复用父类统计口径。",
    },
    {
        "id": "D-POLY-1", "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
        "knowledge_point_name": "多态与接口", "difficulty": 2,
        "title": "以下哪项是多态发生的必要条件？",
        "options": {"a": "类必须是 final", "b": "继承（或实现）并重写方法、父类引用指向子类对象", "c": "所有字段必须是 public"},
        "answer": "b",
        "explanation": "多态 = 父类引用变量指向子类对象，调用被子类重写的方法，运行期动态绑定。",
    },
    {
        "id": "D-POLY-2", "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
        "knowledge_point_name": "多态与接口", "difficulty": 3,
        "title": "接口可以有多实现，其核心价值是？",
        "options": {"a": "只约定行为契约，实现解耦", "b": "让类拥有多个父类的方法体", "c": "替代继承的所有场景"},
        "answer": "a",
        "explanation": "接口定义行为契约，不同实现可替换；这正是多态解耦的关键。",
    },
    {
        "id": "D-COMP-1", "knowledge_point_id": "KN_JAVA_POLYMORPHISM",
        "knowledge_point_name": "多态与接口", "difficulty": 3,
        "title": "竞赛场景：统计多种成绩计算策略的平均分，最合理的做法是？",
        "options": {"a": "定义 ScoreStrategy 接口，不同策略类实现后按接口引用调用", "b": "用 if/else 在统计类里罗列所有策略", "c": "为每种策略各写一个独立的统计方法"},
        "answer": "a",
        "explanation": "接口定义计算契约，调用方只依赖接口引用，新增策略无需改动统计类——竞赛题常考的多态解耦点。",
        "goals": ["competition"],
    },
    {
        "id": "D-COLL-1", "knowledge_point_id": "KN_JAVA_COLLECTION",
        "knowledge_point_name": "集合与泛型", "difficulty": 1,
        "title": "允许重复元素、按插入顺序访问的集合是？",
        "options": {"a": "HashSet", "b": "ArrayList", "c": "HashMap"},
        "answer": "b",
        "explanation": "ArrayList 允许重复、保持插入顺序；HashSet 去重无序。",
    },
    {
        "id": "D-COLL-2", "knowledge_point_id": "KN_JAVA_COLLECTION",
        "knowledge_point_name": "集合与泛型", "difficulty": 2,
        "title": "需要快速判断元素是否已存在（去重），应使用？",
        "options": {"a": "ArrayList", "b": "LinkedList", "c": "HashSet"},
        "answer": "c",
        "explanation": "HashSet 基于哈希表，contains/去重接近 O(1)；ArrayList 需要线性查找。",
    },
    {
        "id": "D-DAILY-1", "knowledge_point_id": "KN_JAVA_COLLECTION",
        "knowledge_point_name": "集合与泛型", "difficulty": 1,
        "title": "日常开发中，遍历 List<String> 并安全移除元素，推荐做法是？",
        "options": {"a": "用迭代器（Iterator）遍历并调用 remove", "b": "在 for 循环里直接 list.remove(i)", "c": "先转成数组再遍历"},
        "answer": "a",
        "explanation": "for 循环中直接按索引 remove 容易越界或漏元素；Iterator.remove 是遍历删除的标准做法。",
        "goals": ["daily"],
    },
    {
        "id": "D-EXC-1", "knowledge_point_id": "KN_JAVA_EXCEPTION",
        "knowledge_point_name": "异常处理", "difficulty": 2,
        "title": "NullPointerException 属于哪类异常？",
        "options": {"a": "RuntimeException（运行时异常）", "b": "编译期检查异常", "c": "Error 错误"},
        "answer": "a",
        "explanation": "空指针属于非检查的运行时异常 RuntimeException，编译期不强制捕获。",
    },
    {
        "id": "D-EXC-2", "knowledge_point_id": "KN_JAVA_EXCEPTION",
        "knowledge_point_name": "异常处理", "difficulty": 3,
        "title": "自动关闭资源的写法是？",
        "options": {"a": "try { ... } finally { close(); }", "b": "try (BufferedReader r = ...) { ... }", "c": "catch 内手动关闭"},
        "answer": "b",
        "explanation": "try-with-resources 语法 try(...) 会在块结束时自动关闭实现了 AutoCloseable 的资源。",
    },
    {
        "id": "D-IO-1", "knowledge_point_id": "KN_JAVA_IO",
        "knowledge_point_name": "输入输出流", "difficulty": 1,
        "title": "Java 字节流的两个抽象基类是？",
        "options": {"a": "Reader 与 Writer", "b": "InputStream 与 OutputStream", "c": "File 与 Path"},
        "answer": "b",
        "explanation": "字节流基类为 InputStream/OutputStream；Reader/Writer 是字符流。",
    },
    {
        "id": "D-IO-2", "knowledge_point_id": "KN_JAVA_IO",
        "knowledge_point_name": "输入输出流", "difficulty": 2,
        "title": "按行读取文本文件最便捷的类是？",
        "options": {"a": "FileInputStream", "b": "ObjectOutputStream", "c": "BufferedReader"},
        "answer": "c",
        "explanation": "BufferedReader.readLine() 按行读取文本；FileInputStream 只提供字节读取。",
    },
]

# 诊断目标 → 题目数量（mock 取样；难度由目标档位决定）
DIAGNOSIS_GOALS: dict[str, dict[str, Any]] = {
    "competition": {"label": "备战世界职业院校技能大赛", "size": 8, "difficulty": 3},
    "certification": {"label": "1+X Java 应用开发认证", "size": 8, "difficulty": 2},
    "daily": {"label": "日常技能提升", "size": 6, "difficulty": 1},
}


def select_diagnosis_questions(goal: str) -> list[dict[str, Any]]:
    """按目标取样：每知识点先取一题（难度最接近目标档位），再用剩余题补足目标数量。

    未知目标由调用方（server.start_diagnosis）先校验；此处假定 goal 合法。
    """
    goal_config = DIAGNOSIS_GOALS[goal]
    bank = [
        item for item in DIAGNOSIS_BANK
        if not item.get("goals") or goal in item.get("goals")
    ]
    by_kp: dict[str, list[dict[str, Any]]] = {}
    for item in bank:
        by_kp.setdefault(item["knowledge_point_id"], []).append(item)
    picked: list[dict[str, Any]] = []
    for items in by_kp.values():
        # 优先目标专属题，其次难度最接近目标档位
        items_sorted = sorted(
            items,
            key=lambda q: (
                0 if q.get("goals") else 1,
                abs(int(q.get("difficulty", 1)) - goal_config["difficulty"]),
            ),
        )
        picked.append(items_sorted[0])
    picked_ids = {q.get("id") for q in picked}
    remaining = [q for q in bank if q.get("id") not in picked_ids]
    remaining.sort(
        key=lambda q: abs(int(q.get("difficulty", 1)) - goal_config["difficulty"])
    )
    picked.extend(remaining[: max(0, goal_config["size"] - len(picked))])
    return picked[: goal_config["size"]]


def bank_questions(knowledge_point_id: str = "") -> list[dict[str, Any]]:
    """题库页用：返回题库公开字段（剔除 answer/explanation），可按知识点过滤。

    与 start_diagnosis 的私有返回不同，这里不含答案，供前端浏览/练习。
    """
    bank = DIAGNOSIS_BANK
    if knowledge_point_id:
        bank = [
            item for item in bank
            if item.get("knowledge_point_id") == knowledge_point_id
        ]
    return [
        {
            "question_id": item["id"],
            "knowledge_point_id": item["knowledge_point_id"],
            "knowledge_point_name": item["knowledge_point_name"],
            "title": item["title"],
            "options": item["options"],
            "difficulty": item["difficulty"],
            "goals": item.get("goals", []),
        }
        for item in bank
    ]


def bank_question_by_id(question_id: str) -> dict[str, Any] | None:
    """按 id 返回完整题库题目（含答案/解析）；未命中返回 None。"""
    for item in DIAGNOSIS_BANK:
        if item.get("id") == question_id:
            return item
    return None


def check_bank_answer(question_id: str, answer: str) -> dict[str, Any]:
    """题库页作答判定：按 id 查题并比对答案，返回结果（含解析，不含整卷状态）。"""
    for item in DIAGNOSIS_BANK:
        if item.get("id") == question_id:
            correct = str(answer).strip().lower() == str(item.get("answer", "")).strip().lower()
            return {
                "status": "ok",
                "correct": correct,
                "question_id": question_id,
                "knowledge_point_id": item.get("knowledge_point_id", ""),
                "knowledge_point_name": item.get("knowledge_point_name", ""),
                "explanation": item.get("explanation", ""),
                "correct_answer": item.get("answer", ""),
            }
    raise ValueError(f"未知题目：{question_id}")
