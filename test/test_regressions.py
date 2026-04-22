from __future__ import annotations

from datetime import date
import threading
import time

from openpyxl import Workbook, load_workbook
from sj_generator.io.sqlite_repo import DbQuestionRecord, append_questions, delete_question_by_id, load_all_questions

from sj_generator.ai import balance as balance_mod
from sj_generator.ai import import_questions as iq
from sj_generator.ai.import_questions import ImportResult
from sj_generator.ai.task_runner import run_tasks_in_parallel
from sj_generator.io import batch_ai_import as batch_ai
from sj_generator.io.batch_folderize import process_excel_to_folder_mode
from sj_generator.io.export_md import _normalize_numbers, export_questions_to_markdown
from sj_generator.models import Question
from sj_generator import config as cfg_mod
from sj_generator.ui.compare_highlight import compare_highlight_model_styles
from sj_generator.ui.state import (
    default_repo_parent_dir,
    normalize_default_repo_parent_dir_text,
    normalize_ai_concurrency,
    normalize_analysis_model_name,
    normalize_analysis_provider,
)


def test_normalize_numbers_fill_after_existing_max() -> None:
    questions = [
        Question(number="5", stem="s1", options="", answer="", analysis=""),
        Question(number="", stem="s2", options="", answer="", analysis=""),
        Question(number="7", stem="s3", options="", answer="", analysis=""),
        Question(number="", stem="s4", options="", answer="", analysis=""),
    ]
    normalized = _normalize_numbers(questions)
    assert [q.number for q in normalized] == ["5", "8", "7", "9"]


def test_delete_question_by_id_removes_only_target_record(tmp_path) -> None:
    db_path = tmp_path / "questions.db"
    records = [
        DbQuestionRecord(
            id="q1",
            stem="题目一",
            option_1="甲",
            option_2="乙",
            option_3="丙",
            option_4="丁",
            choice_1="",
            choice_2="",
            choice_3="",
            choice_4="",
            answer="A",
            analysis="解析一",
            question_type="单选",
            textbook_version="必修一",
            source="资料一.docx",
            level_path="1.1",
            difficulty_score=None,
            knowledge_points="",
            abilities="",
            created_at="2026-04-21 10:00:00",
            updated_at="2026-04-21 10:00:00",
        ),
        DbQuestionRecord(
            id="q2",
            stem="题目二",
            option_1="甲",
            option_2="乙",
            option_3="丙",
            option_4="丁",
            choice_1="",
            choice_2="",
            choice_3="",
            choice_4="",
            answer="B",
            analysis="解析二",
            question_type="单选",
            textbook_version="必修一",
            source="资料二.docx",
            level_path="1.1",
            difficulty_score=None,
            knowledge_points="",
            abilities="",
            created_at="2026-04-21 10:01:00",
            updated_at="2026-04-21 10:01:00",
        ),
    ]
    append_questions(db_path, records)

    assert delete_question_by_id(db_path, "q1") == 1
    assert [record.id for record in load_all_questions(db_path)] == ["q2"]


def test_get_question_n_with_fallback_maps_to_local_index(monkeypatch) -> None:
    root_text = "root\n" + ("x" * 2000)

    def fake_split(text: str, *, max_chars_per_chunk: int):
        if text == root_text:
            return ["sub1", "sub2"]
        return [text]

    def fake_count(*, client, source_name: str, chunk_text: str, depth: int) -> int:
        if chunk_text == "sub1":
            return 2
        if chunk_text == "sub2":
            return 1
        return 0

    calls: list[tuple[str, int]] = []

    def fake_get_in_chunk(*, client, source_name: str, chunk_text: str, index: int):
        calls.append((chunk_text, index))
        if chunk_text == root_text:
            raise TimeoutError("timed out")
        if chunk_text == "sub2" and index == 1:
            return {"number": "3", "stem": "ok"}
        return {}

    monkeypatch.setattr(iq, "_split_text", fake_split)
    monkeypatch.setattr(iq, "_count_questions_with_fallback", fake_count)
    monkeypatch.setattr(iq, "_get_question_n_in_chunk", fake_get_in_chunk)

    got = iq._get_question_n_with_fallback(
        client=object(),
        source_name="src",
        chunk_text=root_text,
        index=3,
        depth=2,
    )

    assert got.get("number") == "3"
    assert ("sub2", 1) in calls


def test_config_path_defaults_to_appdata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SJ_GENERATOR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("SJ_GENERATOR_KIMI_CONFIG_PATH", raising=False)
    monkeypatch.delenv("SJ_GENERATOR_QWEN_CONFIG_PATH", raising=False)
    monkeypatch.delenv("SJ_GENERATOR_PROGRAM_SETTINGS_PATH", raising=False)

    assert cfg_mod._config_path() == tmp_path / "sj_generator" / "deepseek.json"
    assert cfg_mod._kimi_config_path() == tmp_path / "sj_generator" / "kimi.json"
    assert cfg_mod._qwen_config_path() == tmp_path / "sj_generator" / "qwen.json"
    assert cfg_mod._program_settings_path() == tmp_path / "sj_generator" / "program_settings.json"


def test_program_settings_persist_round_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SJ_GENERATOR_PROGRAM_SETTINGS_PATH", raising=False)

    cfg_mod.save_program_settings(
        {
            "default_repo_parent_dir_text": "C:/repo-root",
            "ai_concurrency": 4,
            "analysis_enabled": False,
            "dedupe_enabled": True,
            "analysis_provider": "kimi",
            "analysis_model_name": "kimi-k2-turbo-preview",
            "export_convertible_multi_mode": "as_multi",
        }
    )

    assert cfg_mod.load_program_settings() == {
        "default_repo_parent_dir_text": "C:/repo-root",
        "ai_concurrency": 4,
        "analysis_enabled": False,
        "dedupe_enabled": True,
        "analysis_provider": "kimi",
        "analysis_model_name": "kimi-k2-turbo-preview",
        "export_convertible_multi_mode": "as_multi",
    }


def test_welcome_table_font_point_size_persists_round_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg_mod.save_welcome_table_font_point_size(15)
    assert cfg_mod.load_welcome_table_font_point_size() == 15


def test_deepseek_analysis_model_defaults_and_persists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SJ_GENERATOR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("DEEPSEEK_ANALYSIS_MODEL", raising=False)

    cfg = cfg_mod.load_deepseek_config()
    assert cfg.analysis_model == "deepseek-reasoner"

    updated = cfg_mod.DeepSeekConfig(
        base_url=cfg.base_url,
        api_key="sk-test",
        model="deepseek-chat",
        analysis_model="deepseek-reasoner",
        timeout_s=cfg.timeout_s,
    )
    cfg_mod.save_deepseek_config(updated)
    reloaded = cfg_mod.load_deepseek_config()
    assert reloaded.analysis_model == "deepseek-reasoner"
    assert reloaded.api_key == ""


def test_deepseek_api_key_only_reads_from_env_and_is_not_saved(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SJ_GENERATOR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    cfg = cfg_mod.DeepSeekConfig(
        base_url="https://api.deepseek.com",
        api_key="sk-file",
        model="deepseek-chat",
        analysis_model="deepseek-reasoner",
        timeout_s=60.0,
    )
    cfg_mod.save_deepseek_config(cfg)

    saved = cfg_mod._read_json_dict(cfg_mod._config_path())
    assert "api_key" not in saved
    assert cfg_mod.load_deepseek_config().api_key == ""

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert cfg_mod.load_deepseek_config().api_key == "sk-env"


def test_qwen_account_balance_credentials_only_read_from_env_and_not_saved(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SJ_GENERATOR_QWEN_CONFIG_PATH", raising=False)
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_MODEL", raising=False)
    monkeypatch.delenv("QWEN_TIMEOUT_S", raising=False)
    monkeypatch.delenv("QWEN_ACCOUNT_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("QWEN_ACCOUNT_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)

    cfg = cfg_mod.QwenConfig(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model="qwen-max",
        account_access_key_id="akid",
        account_access_key_secret="aksecret",
        timeout_s=60.0,
    )
    cfg_mod.save_qwen_config(cfg)

    saved = cfg_mod._read_json_dict(cfg_mod._qwen_config_path())
    assert "api_key" not in saved
    assert "account_access_key_id" not in saved
    assert "account_access_key_secret" not in saved

    reloaded = cfg_mod.load_qwen_config()
    assert reloaded.api_key == ""
    assert reloaded.account_access_key_id == ""
    assert reloaded.account_access_key_secret == ""
    assert reloaded.has_account_balance_credentials() is False

    monkeypatch.setenv("QWEN_API_KEY", "dashscope-env")
    monkeypatch.setenv("QWEN_ACCOUNT_ACCESS_KEY_ID", "akid-env")
    monkeypatch.setenv("QWEN_ACCOUNT_ACCESS_KEY_SECRET", "aksecret-env")
    reloaded = cfg_mod.load_qwen_config()
    assert reloaded.api_key == "dashscope-env"
    assert reloaded.account_access_key_id == "akid-env"
    assert reloaded.account_access_key_secret == "aksecret-env"
    assert reloaded.has_account_balance_credentials() is True


def test_compare_highlight_marks_minority_model() -> None:
    got = compare_highlight_model_styles(
        model_sigs={"deepseek": '{"answer":"A"}', "kimi": '{"answer":"A"}', "qwen": '{"answer":"B"}'},
        round_no=1,
        round_matched_count=2,
    )
    assert got == {"qwen": "red"}


def test_compare_highlight_marks_all_when_first_round_failed() -> None:
    got = compare_highlight_model_styles(
        model_sigs={"deepseek": '{"answer":"A"}', "kimi": "", "qwen": '{"answer":"B"}'},
        round_no=1,
        round_matched_count=1,
    )
    assert got == {"deepseek": "red", "kimi": "yellow", "qwen": "red"}


def test_compare_highlight_skips_when_first_round_all_passed() -> None:
    got = compare_highlight_model_styles(
        model_sigs={"deepseek": '{"answer":"A"}', "kimi": '{"answer":"A"}', "qwen": '{"answer":"A"}'},
        round_no=1,
        round_matched_count=3,
    )
    assert got == {}


def test_compare_highlight_marks_non_first_round_minority_model() -> None:
    got = compare_highlight_model_styles(
        model_sigs={"deepseek": '{"answer":"A"}', "kimi": "", "qwen": '{"answer":"A"}'},
        round_no=2,
        round_matched_count=2,
    )
    assert got == {"kimi": "yellow"}


def test_compare_highlight_marks_all_non_empty_models_red_when_all_different() -> None:
    got = compare_highlight_model_styles(
        model_sigs={"deepseek": '{"answer":"A"}', "kimi": '{"answer":"B"}', "qwen": '{"answer":"C"}'},
        round_no=2,
        round_matched_count=1,
    )
    assert got == {"deepseek": "red", "kimi": "red", "qwen": "red"}


def test_compare_highlight_uses_same_fingerprint_semantics_as_verdict() -> None:
    deepseek = iq._normalize_question_obj_for_view(
        {"number": "1", "stem": "1. 题目一", "options": "A.甲\nB.乙", "answer": "a"}
    )
    kimi = iq._normalize_question_obj_for_view(
        {"number": "", "stem": "题目一", "options": "A.甲\nB.乙", "answer": "A"}
    )
    qwen = iq._normalize_question_obj_for_view(
        {"number": "3", "stem": "题目一", "options": "A. 丙\nB. 丁", "answer": "B"}
    )
    got = compare_highlight_model_styles(
        model_sigs={
            "deepseek": iq._fingerprint_question_obj(deepseek),
            "kimi": iq._fingerprint_question_obj(kimi),
            "qwen": iq._fingerprint_question_obj(qwen),
        },
        round_no=1,
        round_matched_count=2,
    )
    assert got == {"qwen": "red"}


def test_normalize_question_obj_for_view_splits_legacy_options_into_option_fields() -> None:
    got = iq._normalize_question_obj_for_view(
        {
            "question_type": "单选",
            "number": "2",
            "stem": "题目二",
            "options": "A.甲 B.乙 C.丙 D.丁",
            "answer": "D",
        }
    )
    assert "options" not in got
    assert got["option_1"] == "甲"
    assert got["option_2"] == "乙"
    assert got["option_3"] == "丙"
    assert got["option_4"] == "丁"


def test_fingerprint_question_obj_treats_option_fields_same_as_legacy_options() -> None:
    legacy = {
        "question_type": "单选",
        "number": "2",
        "stem": "题目二",
        "options": "A.甲\nB.乙\nC.丙\nD.丁",
        "answer": "D",
    }
    structured = {
        "question_type": "单选",
        "number": "2",
        "stem": "题目二",
        "option_1": "甲",
        "option_2": "乙",
        "option_3": "丙",
        "option_4": "丁",
        "answer": "D",
    }
    assert iq._fingerprint_question_obj(legacy) == iq._fingerprint_question_obj(structured)


def test_build_deepseek_balance_url_supports_common_base_url_forms() -> None:
    assert balance_mod._build_deepseek_balance_url("https://api.deepseek.com") == "https://api.deepseek.com/user/balance"
    assert balance_mod._build_deepseek_balance_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/user/balance"
    assert (
        balance_mod._build_deepseek_balance_url("https://api.deepseek.com/v1/chat/completions")
        == "https://api.deepseek.com/user/balance"
    )


def test_format_deepseek_balance_infos_formats_currency_and_breakdown() -> None:
    got = balance_mod._format_deepseek_balance_infos(
        [
            {
                "currency": "CNY",
                "total_balance": "110",
                "granted_balance": "10",
                "topped_up_balance": "100",
            }
        ]
    )
    assert got == ["CNY ¥110.00（赠送 ¥10.00，充值 ¥100.00）"]


def test_build_kimi_balance_url_supports_common_base_url_forms() -> None:
    assert balance_mod._build_kimi_balance_url("https://api.moonshot.cn") == "https://api.moonshot.cn/v1/users/me/balance"
    assert balance_mod._build_kimi_balance_url("https://api.moonshot.cn/v1") == "https://api.moonshot.cn/v1/users/me/balance"
    assert (
        balance_mod._build_kimi_balance_url("https://api.moonshot.cn/v1/chat/completions")
        == "https://api.moonshot.cn/v1/users/me/balance"
    )


def test_describe_kimi_balance_payload_supports_direct_balance_field() -> None:
    got = balance_mod._describe_kimi_balance_payload({"balance": "15.5", "currency": "CNY"})
    assert got == "已配置，余额 CNY ¥15.50"


def test_describe_aliyun_account_balance_payload_supports_available_amount() -> None:
    got = balance_mod._describe_aliyun_account_balance_payload({"Data": {"AvailableAmount": "123.4", "Currency": "CNY"}})
    assert got == "已配置，阿里云账户余额 CNY ¥123.40"


def test_run_analysis_tasks_supports_three_way_concurrency() -> None:
    tasks = [(i, f"题目{i}", "A") for i in range(5)]
    lock = threading.Lock()
    active = 0
    max_active = 0
    started: list[int] = []
    completed: list[int] = []

    def run_one(task: tuple[int, str, str]) -> int:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return task[0]

    run_tasks_in_parallel(
        tasks=tasks,
        max_workers=3,
        stop_cb=lambda: False,
        on_task_start=lambda current, total, task: started.append(current),
        on_task_done=lambda task, result: completed.append(result),
        on_task_failed=lambda task, exc: (_ for _ in ()).throw(exc),
        run_one=run_one,
    )

    assert started == [1, 2, 3, 4, 5]
    assert sorted(completed) == [0, 1, 2, 3, 4]
    assert max_active == 3


def test_normalize_ai_concurrency_keeps_allowed_values_and_falls_back() -> None:
    assert normalize_ai_concurrency(1) == 1
    assert normalize_ai_concurrency(2) == 2
    assert normalize_ai_concurrency(3) == 3
    assert normalize_ai_concurrency(4) == 4
    assert normalize_ai_concurrency(5) == 5
    assert normalize_ai_concurrency(6) == 3
    assert normalize_ai_concurrency(None) == 3


def test_normalize_analysis_provider_keeps_allowed_values_and_falls_back() -> None:
    assert normalize_analysis_provider("deepseek") == "deepseek"
    assert normalize_analysis_provider("kimi") == "kimi"
    assert normalize_analysis_provider("qwen") == "qwen"
    assert normalize_analysis_provider("other") == "deepseek"
    assert normalize_analysis_provider(None) == "deepseek"


def test_normalize_analysis_model_name_keeps_input_and_falls_back() -> None:
    assert normalize_analysis_model_name("deepseek-reasoner") == "deepseek-reasoner"
    assert normalize_analysis_model_name("custom-model") == "custom-model"
    assert normalize_analysis_model_name("") == "deepseek-reasoner"
    assert normalize_analysis_model_name(None) == "deepseek-reasoner"


def test_normalize_default_repo_parent_dir_text_keeps_input_and_falls_back() -> None:
    assert normalize_default_repo_parent_dir_text("C:/repo-root") == "C:/repo-root"
    assert normalize_default_repo_parent_dir_text("") == str(default_repo_parent_dir())
    assert normalize_default_repo_parent_dir_text(None) == str(default_repo_parent_dir())


def test_process_excel_to_folder_mode_supports_legacy_headers(tmp_path) -> None:
    src = tmp_path / "1.1.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "questions"
    ws.append(["编号", "题目", "答案", "解析", "提取日期"])
    ws.append([1, "题目一\nA. 甲\nB. 乙", "A", "解析一", "2026-03-31"])
    wb.save(src)

    result = process_excel_to_folder_mode(src, export_date=date(2026, 3, 31))

    assert result.target_dir == tmp_path / "1.1"
    assert result.target_xlsx.exists()
    assert result.target_md.exists()

    saved = load_workbook(result.target_xlsx)
    ws2 = saved["questions"]
    assert [c.value for c in next(ws2.iter_rows(min_row=1, max_row=1))] == ["编号", "题目", "选项", "答案", "解析"]
    assert ws2.cell(2, 3).value in ("", None)


def test_process_source_files_to_folders_outputs_xlsx_and_md(monkeypatch, tmp_path) -> None:
    src = tmp_path / "资料一.txt"
    src.write_text("原始资料", encoding="utf-8")

    monkeypatch.setattr(batch_ai, "read_source_text", lambda path: "资料正文")
    monkeypatch.setattr(batch_ai, "generate_explanation", lambda client, inp: "解析一")
    monkeypatch.setattr(
        batch_ai,
        "import_questions_from_sources",
        lambda **kwargs: ImportResult(
            questions=[Question(number="1", stem="题目一", options="A.甲\nB.乙", answer="A", analysis="")],
            raw_items=[],
        ),
    )

    messages: list[str] = []
    results = batch_ai.process_source_files_to_folders(
        paths=[src],
        client=object(),
        kimi_client=object(),
        qwen_client=object(),
        export_date=date(2026, 3, 31),
        progress_cb=messages.append,
    )

    assert len(results) == 1
    result = results[0]
    assert result.target_dir == tmp_path / "资料一"
    assert result.target_xlsx.exists()
    assert result.target_md.exists()
    assert result.question_count == 1
    assert any("AI 解析准备中" in msg or "统计题数" in msg for msg in messages)
    saved = load_workbook(result.target_xlsx)
    ws = saved["questions"]
    assert ws.cell(2, 5).value == "解析一"

    progress_events: list[batch_ai.BatchAiProgress] = []
    batch_ai.process_source_files_to_folders(
        paths=[src],
        client=object(),
        kimi_client=object(),
        qwen_client=object(),
        export_date=date(2026, 3, 31),
        progress_info_cb=progress_events.append,
    )
    assert any(event.stage == "reading" for event in progress_events)
    assert any(event.stage == "generating_analysis" for event in progress_events)
    assert any(event.stage == "done" and event.question_count == 1 for event in progress_events)


def test_export_markdown_removes_extra_blank_line_for_convertible_multi_options() -> None:
    md = export_questions_to_markdown(
        excel_file_name="示例题库",
        export_date=date(2026, 3, 31),
        questions=[
            Question(
                number="1",
                stem="题目一",
                options="①. 甲\n②. 乙\n③. 丙\n④. 丁\n\nA. ①③\nB. ①②\nC. ②④\nD. ①④",
                answer="B",
                analysis="解析一",
            )
        ],
    )
    assert "④. 丁\n\nA. ①③" not in md
    assert "④. 丁\nA. ①③  B. ①②  C. ②④  D. ①④" in md


def test_export_markdown_orders_convertible_multi_statements_before_combo_lines() -> None:
    md = export_questions_to_markdown(
        excel_file_name="示例题库",
        export_date=date(2026, 3, 31),
        questions=[
            Question(
                number="1",
                stem="题目一",
                options="A. ①③\n①. 甲\nB. ①②\n②. 乙\n③. 丙\nD. ①④\n④. 丁\nC. ②④",
                answer="B",
                analysis="解析一",
            )
        ],
    )
    combo_line = "A. ①③  B. ①②  C. ②④  D. ①④"
    assert combo_line in md
    assert md.index("①. 甲") < md.index(combo_line)
    assert md.index("②. 乙") < md.index(combo_line)
    assert md.index("③. 丙") < md.index(combo_line)
    assert md.index("④. 丁") < md.index(combo_line)


def test_export_markdown_supports_convertible_multi_as_multi_mode() -> None:
    md = export_questions_to_markdown(
        excel_file_name="示例题库",
        export_date=date(2026, 3, 31),
        questions=[
            Question(
                number="1",
                stem="题目一",
                options="①. 甲\n②. 乙\n③. 丙\n④. 丁\nA. ①③\nB. ①②\nC. ②④\nD. ①④",
                answer="B",
                analysis="解析一",
            )
        ],
        convertible_multi_mode="as_multi",
    )
    assert "①. 甲" in md
    assert "②. 乙" in md
    assert "③. 丙" in md
    assert "④. 丁" in md
    assert "A. ①③" not in md
    assert "B. ①②" not in md


def test_process_source_files_to_folders_supports_controlled_concurrency(monkeypatch, tmp_path) -> None:
    src1 = tmp_path / "资料一.txt"
    src2 = tmp_path / "资料二.txt"
    src1.write_text("原始资料一", encoding="utf-8")
    src2.write_text("原始资料二", encoding="utf-8")

    monkeypatch.setattr(batch_ai, "read_source_text", lambda path: f"{path.stem} 正文")
    monkeypatch.setattr(batch_ai, "generate_explanation", lambda client, inp: "解析一")
    monkeypatch.setattr(
        batch_ai,
        "import_questions_from_sources",
        lambda **kwargs: ImportResult(
            questions=[Question(number="1", stem="题目一", options="A.甲\nB.乙", answer="A", analysis="")],
            raw_items=[],
        ),
    )

    created: list[str] = []

    def make_client(tag: str):
        def factory():
            created.append(tag)
            return object()

        return factory

    results = batch_ai.process_source_files_to_folders(
        paths=[src1, src2],
        client_factory=make_client("deepseek"),
        analysis_client_factory=make_client("analysis"),
        kimi_client_factory=make_client("kimi"),
        qwen_client_factory=make_client("qwen"),
        max_workers=2,
        export_date=date(2026, 3, 31),
    )

    assert [item.target_dir.name for item in results] == ["资料一", "资料二"]
    assert len(created) == 8


def test_process_source_files_to_folders_supports_analysis_concurrency(monkeypatch, tmp_path) -> None:
    src = tmp_path / "资料一.txt"
    src.write_text("原始资料", encoding="utf-8")

    monkeypatch.setattr(batch_ai, "read_source_text", lambda path: "资料正文")
    monkeypatch.setattr(
        batch_ai,
        "import_questions_from_sources",
        lambda **kwargs: ImportResult(
            questions=[
                Question(number="1", stem="题目一", options="A.甲\nB.乙", answer="A", analysis=""),
                Question(number="2", stem="题目二", options="A.甲\nB.乙", answer="B", analysis=""),
            ],
            raw_items=[],
        ),
    )
    monkeypatch.setattr(batch_ai, "generate_explanation", lambda client, inp: f"解析-{inp.answer_text}")

    created: list[str] = []

    def make_client():
        created.append("deepseek")
        return object()

    results = batch_ai.process_source_files_to_folders(
        paths=[src],
        client=object(),
        kimi_client=object(),
        qwen_client=object(),
        client_factory=make_client,
        max_analysis_workers=2,
        export_date=date(2026, 3, 31),
    )

    assert len(results) == 1
    saved = load_workbook(results[0].target_xlsx)
    ws = saved["questions"]
    assert ws.cell(2, 5).value == "解析-A"
    assert ws.cell(3, 5).value == "解析-B"
    assert len(created) == 2


def test_import_questions_from_sources_supports_question_level_concurrency(monkeypatch, tmp_path) -> None:
    src = tmp_path / "资料一.txt"
    src.write_text("原始资料", encoding="utf-8")

    monkeypatch.setattr(iq, "_count_questions_with_fallback", lambda **kwargs: 3)
    monkeypatch.setattr(
        iq,
        "_process_one_question",
        lambda **kwargs: (
            {"number": str(kwargs["index"]), "stem": f"题目{kwargs['index']}", "options": "", "answer": "A"},
            False,
            {},
        ),
    )

    created: list[str] = []

    def make_client(tag: str):
        def factory():
            created.append(tag)
            return object()

        return factory

    result = iq.import_questions_from_sources(
        client=object(),
        kimi_client=object(),
        qwen_client=object(),
        client_factory=make_client("deepseek"),
        kimi_client_factory=make_client("kimi"),
        qwen_client_factory=make_client("qwen"),
        sources=[(src, "资料正文")],
        strategy="per_question",
        max_question_workers=2,
    )

    assert [q.number for q in result.questions] == ["1", "2", "3"]
    assert len(created) == 9
