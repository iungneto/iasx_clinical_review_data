import json

import pytest

from jev_contract import (
    PRIORITIES,
    PROMPT_VERSION,
    QUESTIONS,
    MockJev,
    build_request,
    classify,
    extract_answer,
    finding_context,
)


@pytest.mark.parametrize(
    "schema,payload,expected",
    [
        ("noul", {"output": True}, True),
        ("noul", {"output": "Sim"}, True),
        ("noul", {"output": {"answer": "no"}}, False),
        ("noul", {"output": "talvez"}, None),
        ("choice", {"output": "Média"}, "media"),
        ("choice", {"output": {"choice": "alta"}}, "alta"),
        ("choice", {"output": "urgente"}, None),
        ("choice", "baixa", "baixa"),
    ],
)
def test_extract_answer_normalizes_or_rejects(schema, payload, expected):
    assert extract_answer(schema, payload) == expected


def test_choice_request_carries_only_workflow_priorities():
    body = build_request("m", "choice", QUESTIONS["priority"][1], "ctx")
    assert body["options"] == PRIORITIES == ["baixa", "media", "alta"]
    assert "options" not in build_request("m", "noul", QUESTIONS["needs_review"][1], "ctx")


def test_questions_are_about_workflow_never_diagnosis():
    texts = " ".join(q for _, q in QUESTIONS.values()).lower()
    assert "não faça diagnóstico" in texts and "não é prioridade clínica" in texts
    for forbidden in ("tratamento", "prescrev", "medicamento", "conduta"):
        assert forbidden not in texts


def test_context_is_minimal():
    ctx = finding_context("GAP", "MISSING_DATE", "Resultado de Hemoglobina sem data de coleta identificável.")
    assert ctx.startswith("Tipo: GAP. Subtipo: MISSING_DATE.")
    assert "CASE-" not in ctx and "rev-" not in ctx


def test_classify_with_mock_is_traceable():
    out = classify(MockJev(), "CONFLICT", "DIVERGENT_VALUES", "Potássio com 2 versões")
    assert (out["needs_review"], out["priority"], out["is_clear"]) == (True, "alta", False)
    assert out["jev_response_valid"] is True
    assert out["jev_model"] == "mock-jev" and out["jev_prompt_version"] == PROMPT_VERSION
    assert len(out["jev_request_hash"]) == 64
    assert set(json.loads(out["jev_raw_answers"])) == set(QUESTIONS)


class _Broken:
    model = "broken"

    def __init__(self, reply):
        self.reply = reply

    def ask(self, schema, question, context):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.mark.parametrize("reply", [ConnectionError("down"), {"output": "não sei"}])
def test_failure_or_out_of_schema_is_invalid_not_dropped(reply):
    """A gold força revisão humana com prioridade alta quando jev_response_valid = false."""
    out = classify(_Broken(reply), "OUT_OF_DOCUMENT_RANGE", "ABOVE_DOCUMENT_RANGE", "x")
    assert out["jev_response_valid"] is False
    assert out["needs_review"] is None


def test_prompt_version_is_stable_and_short():
    assert PROMPT_VERSION.startswith("jevq-") and len(PROMPT_VERSION) == 17
