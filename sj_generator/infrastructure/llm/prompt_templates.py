from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptField:
    key: str
    title: str
    description: str
    placeholders: tuple[str, ...] = ()


PROMPT_FIELDS: tuple[PromptField, ...] = (
    PromptField(
        key="question_number_list_system",
        title="题号识别 System Prompt",
        description="三模型识别选择题题号列表时使用的系统提示词。",
    ),
    PromptField(
        key="question_number_list_user",
        title="题号识别 User Prompt",
        description="识别题号列表时发送给模型的用户提示词模板。",
        placeholders=("{{source_name}}", "{{chunk_text}}"),
    ),
    PromptField(
        key="question_extract_system",
        title="逐题提取 System Prompt",
        description="按题号与题型从整篇资料文本中提取目标 JSON 时使用的系统提示词。",
    ),
    PromptField(
        key="question_extract_user",
        title="逐题提取 User Prompt",
        description="按题号与题型提取时发送给模型的用户提示词模板。",
        placeholders=("{{source_name}}", "{{requested_number}}", "{{requested_question_type}}", "{{chunk_text}}"),
    ),
    PromptField(
        key="explanation_system",
        title="解析生成 System Prompt",
        description="补解析阶段生成答案解析时使用的系统提示词。",
    ),
    PromptField(
        key="explanation_user",
        title="解析生成 User Prompt",
        description="补解析阶段发送给模型的用户提示词模板。",
        placeholders=("{{question_text}}", "{{answer_text}}", "{{reference_block}}", "{{mistakes_block}}"),
    ),
    PromptField(
        key="explanation_fill_answer_system",
        title="补答案解析 System Prompt",
        description="缺少答案时，先补答案再生成解析使用的系统提示词。",
    ),
    PromptField(
        key="explanation_fill_answer_user",
        title="补答案解析 User Prompt",
        description="缺少答案时发送给模型的用户提示词模板。",
        placeholders=("{{question_text}}", "{{reference_block}}", "{{mistakes_block}}"),
    ),
)


DEFAULT_IMPORT_PROMPTS: dict[str, str] = {
    "question_number_list_system": (
        "你是一个题库整理助手。你必须仅输出严格 JSON，不要输出任何解释、markdown、前后缀、代码块或额外文本。\n"
        "任务：从提供的资料文本中识别所有选择题的题号列表。\n"
        "题型范围只包括：”单选“、”多选“、”可转多选“。\n"
        "其中“可转多选”是指：题干或材料先给出 ①②③④ 等若干表述，再给出 A/B/C/D 表示这些表述的不同组合，本质上仍属于单选，但是给出了四种可能的多选，你需要把这种题视为”可转多选“。\n"
        "”可转多选“类型示例：\n"
        "某班同学在学习“中国特色社会主义”时，对以下观点进行讨论，其中正确的观点是（ ）\n"
        "①坚持党的领导是中国特色社会主义最本质的特征；\n"
        "②坚持以人民为中心是中国特色社会主义的根本任务；\n"
        "③坚持依法治国是中国特色社会主义的本质要求；\n"
        "④坚持改革开放是中国特色社会主义的唯一动力。\n"
        "A.①② B.①③ C.②④ D.③④\n"
        "必须输出 JSON 数组，数组每一项都是对象，至少包含 number 和 question_type 两个字段。\n"
        "示例输出：[{\"number\":\"1\",\"question_type\":\"单选\"},{\"number\":\"2\",\"question_type\":\"多选\"},{\"number\":\"5\",\"question_type\":\"可转多选\"}]。\n"
        "保持原始出现顺序，不要重排。\n"
        "如果某题没有明确题号，不要编造。\n"
        "question_type 只能填写“单选”“多选”“可转多选”三者之一；无法确定时不要猜测，跳过该题。\n"
        "如果没有识别到任何带题号的选择题，输出 []。\n"
        "异常情况只返回[错误类型]\n"
        "错误类型包括：题号重复、所给文本无选择题目\n"
    ),
    "question_number_list_user": (
        "来源文件：{{source_name}}\n"
        "资料文本如下：\n"
        "-----\n"
        "{{chunk_text}}\n"
        "-----\n"
        "请输出所有选择题题号列表。"
    ),
    "question_extract_system": (
        "你是一个题库整理助手。你必须仅输出严格 JSON，不要输出任何解释、markdown、前后缀、代码块或额外文本。\n"
        "任务：根据给定的题号和已知选择题类型，从整篇 Word 文本中精确定位并提取目标题目的 JSON 信息。\n"
        "你拿到的是整篇资料文本，而不是只包含目标题目的片段；你必须先在全文中找到与指定题号对应、且与给定题型一致的那一道题，再输出该题的结构化 JSON。\n"
        "如果全文中同一题号出现多个候选内容，优先选择与给定题型一致、题干和选项结构最完整、最像一道独立选择题的那一项。\n"
        "如果找到同题号但题型与给定题型明显不一致，不要强行抽取错误题目；应继续在全文中查找更匹配的候选。\n"
        "如果最终无法在全文中稳定定位到“指定题号 + 指定题型”的目标题，请输出空对象 {}。\n"
        "题目可能是以下三类之一：\n"
        "- 单选：选项标识通常为 A/B/C/D 或 A. / A、 等，答案是单个选项标识。\n"
        "- 多选：答案本身是多个选项标识的组合。\n"
        "- 可转多选：题干或材料中先给出 ①②③④ 等若干表述，再由 A/B/C/D 表示这些表述的不同组合；这类题本质上是组合型选择题。\n"
        "如果原文没有明确答案，answer 允许为空字符串。\n"
        "字段规则必须严格遵守：\n"
        '1. question_type 必须输出且只能是 "单选"、"多选"、"可转多选" 三者之一。\n'
        '2. number 只保留题号本身，例如 "12"；不要保留 "第12题"、"12."、"12、"、括号等；没有明确题号时填空字符串。\n'
        '3. stem 只保留题干正文；不要包含题号、选项、答案、解析、"答案："、"解析：" 等内容。\n'
        '4. 选项必须拆成 option_1、option_2、option_3、option_4 四个字段分别输出；字段值只保留选项正文，不要包含 A/B/C/D/①②③④ 等标识。\n'
        '5. answer 只保留答案标识本身；不要包含 "答案" 二字、冒号、句号、解释文字或空格。\n'
        '6. 普通单选答案统一输出单个标识，如 A / B / C / D。\n'
        '7. 普通多选答案统一输出紧凑组合，不加顿号、逗号、空格或斜杠，例如 ACD、ABD。\n'
        '8. 可转多选题中，若原文先给出 ①②③④ 等表述，再给出 A/B/C/D 代表不同组合，则 option_1 到 option_4 只保留 ①②③④ 对应的四条表述本身，不保留 A/B/C/D 组合项。\n'
        '9. 可转多选题必须额外输出 choice_1、choice_2、choice_3、choice_4 四个字段，分别对应 A、B、C、D 的组合映射；字段值只保留数字序号本身，例如 A 对应 ①②，则 choice_1 输出 "12"。\n'
        '10. 可转多选题的 answer 必须输出正常字母答案 A/B/C/D，不要输出圆圈序号。\n'
        "10.1 结构一致性强约束：如果 question_type 是可转多选，那么必须同时满足“option_1..option_4 为 ①②③④ 表述”“choice_1..choice_4 为数字映射”“answer 为 A/B/C/D”。\n"
        "10.2 如果原文在题干或选项中使用了“（ ）”“( )”“（）”等括号空位来表示待填答案或占位，返回的 stem、option_1、option_2、option_3、option_4 中必须保留这些原有括号空位，不得省略、删除或改写成其他符号。\n"
        "11. 如果原文出现材料、案例或引导语，且该内容属于该题题干的一部分，应保留在 stem 中。\n"
        "12. 不要凭空编造不存在的题目、选项或答案；无法确定时宁可留空，也不要猜测。\n"
        "13. 如遇图片题、表格题或信息缺失题，只提取文本中能够明确确认的内容。\n"
        '14. 所有 JSON 字段值都不允许包含实际换行、字符串 "\\n"、"<br>"、"<br/>"、"<br />" 等换行符号；如原文是多行内容，必须合并成单行，并用普通空格连接。\n'
        "如果题目出现“组合选项”形式（例如先给出 ①②③④ 四个表述，然后给出 A/B/C/D 代表不同组合，如“ A．①② B．①④ … ”），请按以下方式转换：\n"
        "- option_1 到 option_4 只输出 ①②③④ 对应的每条表述（不要包含 A/B/C/D 这些组合项）\n"
        '- question_type 必须输出为 "可转多选"\n'
        '- choice_1 到 choice_4 分别输出 A 到 D 对应的数字映射，例如 A．①② 则 choice_1 输出 "12"\n'
        "- answer 必须输出正确选项字母，例如 B\n"
        "这里的任务是：从提供的整篇资料文本中抽取“指定题号 + 指定题型”的那一题。\n"
        "输出格式：JSON 对象：\n"
        "{\n"
        '  "question_type": "题型(单选/多选/可转多选)",\n'
        '  "number": "编号(必须是请求题号本身)",\n'
        '  "stem": "题干正文",\n'
        '  "option_1": "第1个选项正文",\n'
        '  "option_2": "第2个选项正文",\n'
        '  "option_3": "第3个选项正文",\n'
        '  "option_4": "第4个选项正文",\n'
        '  "choice_1": "可转多选时 A 对应数字映射；否则留空",\n'
        '  "choice_2": "可转多选时 B 对应数字映射；否则留空",\n'
        '  "choice_3": "可转多选时 C 对应数字映射；否则留空",\n'
        '  "choice_4": "可转多选时 D 对应数字映射；否则留空",\n'
        '  "answer": "答案标识"\n'
        "}\n"
        "如果无法确定该题，请输出空对象 {}。不要猜测，不要补全文本。"
    ),
    "question_extract_user": (
        "来源文件：{{source_name}}\n"
        "目标题号：{{requested_number}}\n"
        "目标题型：{{requested_question_type}}\n"
        "请根据“目标题号 + 目标题型”，从下面整篇资料文本中精确定位该题，并只输出这一题的 JSON 对象。\n"
        "资料文本如下：\n"
        "-----\n"
        "{{chunk_text}}\n"
        "-----\n"
    ),
    "explanation_system": (
        "你是一个专业的教育助手，擅长讲解选择题。请严格遵循用户的格式要求。"
    ),
    "explanation_user": (
        "请严格按照以下格式输出解析：\n"
        "如果“答案文本”为空，先根据题目、参考资料与常见错题参考判断最可能的正确答案，并在第一行单独输出“答案：答案标识”。\n"
        "如果“答案文本”不为空，直接基于给定答案输出逐项解析，不要重复输出“答案：...”。\n"
        "每行分析一个选项。\n"
        "必须沿用题目中出现的选项标识（例如 A/B/C/D 或 ①/②/③/④），不要擅自改成另一种编号方式。\n"
        "如果是错误选项：必须先指出“具体的错误原因类型”（可以多个，用中文分号“；”分隔），然后再做详细分析。\n"
        "如果是正确选项：必须标记为“正确”，并说明理由。\n"
        "同一选项允许多个错误原因，需要一并列出。\n"
        "\n"
        "示例格式：\n"
        "答案：AC\n"
        "- A：**知识模块归类错误** ...\n"
        "- B：**正确** ...\n"
        "- C：**偷换概念；范围扩大** ...\n"
        "或：\n"
        "答案：B\n"
        "- ①：**知识模块归类错误** ...\n"
        "- ②：**正确** ...\n"
        "- ③：**偷换概念；范围扩大** ...\n"
        "\n"
        "题目文本：\n"
        "{{question_text}}\n"
        "\n"
        "答案文本：\n"
        "{{answer_text}}\n"
        "{{reference_block}}"
        "{{mistakes_block}}"
    ),
    "explanation_fill_answer_system": (
        "你是一个思政选择题解析助手。"
        "当题目原文没有提供答案时，你需要先根据题干、选项和参考资料判断最可能的正确答案，再输出逐项解析。"
        "你必须仅输出严格 JSON，不要输出 markdown、代码块或额外说明。\n"
        "输出格式固定为："
        '{"answer_text":"答案标识","analysis_text":"逐项解析"}' "\n"
        "answer_text 规则：\n"
        "- 单选输出单个字母，如 A。\n"
        "- 多选输出紧凑字母组合，如 ACD。\n"
        "- 可转多选输出正常字母答案 A/B/C/D，不要输出圆圈序号。\n"
        "- 不要包含“答案”二字、冒号、句号、空格、逗号、顿号或解释文字。\n"
        "analysis_text 规则：\n"
        "- 每行分析一个选项。\n"
        "- 必须沿用题目中出现的选项标识。\n"
        "- 正确选项标记为“正确”并说明理由；错误选项先写错误原因类型，再分析。\n"
        "- 只输出纯文本解析，不要再包一层 JSON 或 markdown。\n"
    ),
    "explanation_fill_answer_user": (
        "请先判断这道题最可能的正确答案，再输出答案和逐项解析。\n"
        "题目文本：\n"
        "{{question_text}}\n"
        "{{reference_block}}"
        "{{mistakes_block}}"
    ),
}


_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS: int | None = None
_CACHE_PROMPTS: dict[str, str] | None = None


def import_prompt_config_path() -> Path:
    env = os.getenv("SJ_GENERATOR_IMPORT_PROMPTS_PATH", "").strip()
    if env:
        return Path(env)
    app_data = os.getenv("APPDATA", "").strip()
    if app_data:
        return Path(app_data) / "sj_generator" / "import_prompts.json"
    return Path.home() / ".sj_generator" / "import_prompts.json"


def load_import_prompts(*, force_reload: bool = False) -> dict[str, str]:
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE_PROMPTS

    path = import_prompt_config_path()
    mtime_ns: int | None = None
    if path.exists():
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None

    if (
        not force_reload
        and _CACHE_PROMPTS is not None
        and _CACHE_PATH == path
        and _CACHE_MTIME_NS == mtime_ns
    ):
        return dict(_CACHE_PROMPTS)

    raw: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = {}

    prompts = _normalize_prompt_map(raw)
    _CACHE_PATH = path
    _CACHE_MTIME_NS = mtime_ns
    _CACHE_PROMPTS = dict(prompts)
    return prompts


def save_import_prompts(prompts: dict[str, str]) -> None:
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE_PROMPTS

    path = import_prompt_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_prompt_map(prompts)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    _CACHE_PATH = path
    _CACHE_MTIME_NS = mtime_ns
    _CACHE_PROMPTS = dict(normalized)


def get_import_prompt(key: str) -> str:
    prompts = load_import_prompts()
    if key not in DEFAULT_IMPORT_PROMPTS:
        raise KeyError(f"未知提示词键：{key}")
    return prompts.get(key, DEFAULT_IMPORT_PROMPTS[key])


def render_import_prompt(key: str, **kwargs: object) -> str:
    text = get_import_prompt(key)
    for name, value in kwargs.items():
        text = text.replace("{{" + str(name) + "}}", str(value))
    return text


def default_import_prompts() -> dict[str, str]:
    return dict(DEFAULT_IMPORT_PROMPTS)


def _normalize_prompt_map(data: dict[str, object]) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for key, default_value in DEFAULT_IMPORT_PROMPTS.items():
        raw = data.get(key, default_value)
        prompts[key] = raw if isinstance(raw, str) else default_value
    return prompts
