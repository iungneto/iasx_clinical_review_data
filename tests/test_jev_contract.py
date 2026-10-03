import json

import pytest

from jev_contract import (
    PRIORITIES,
    PRIORITY_CRITERIA,
    PROMPT_VERSION,
    QUESTIONS,
    RETRY_STATUS,
    MockJev,
    build_request,
    classify,
    extract_answer,
    finding_state,
)

NOUL = lambda p: {"type": "noul", "noul": p}  # noqa: E731
CHOICE = lambda c: {"type": "choice", "choice": c, "confidence": 0.9, "probabilities": {c: 0.9}}  # noqa: E731


def _resp(needs_review=NOUL(0.98), priority=CHOICE("alta"), is_clear=NOUL(0.1)):
    answers = {"needs_review": needs_review, "priority": priority, "is_clear": is_clear}
    return {"model": "jev-latest", "answers": answers, "usage": {"input_tokens": 300, "output_tokens": 3}}


@pytest.mark.parametrize(
    "schema,answer,expected",
    [
        ("noul", NOUL(0.98), True),
        ("noul", NOUL(0.65), True),
        ("noul", NOUL(0.02), False),
        ("noul", NOUL(0.5), None),  # incerta → revisão humana
        ("noul", NOUL("x"), None),
        ("noul", CHOICE("alta"), None),  # tipo trocado
        ("choice", CHOICE("alta"), "alta"),
        ("choice", CHOICE("urgente"), None),
        ("choice", None, None),
        ("choice", "baixa", None),
    ],
)
def test_extract_answer_normalizes_or_rejects(schema, answer, expected):
    assert extract_answer(schema, answer) == expected


def test_request_sends_all_questions_together_over_one_state():
    state = finding_state("GAP", "MISSING_DATE", "x")
    body = build_request("m", state)
    assert set(body) == {"model", "state", "questions"} and body["state"] == state
    assert set(body["questions"]) == set(QUESTIONS)
    prio = body["questions"]["priority"]
    assert prio["type"] == "choice" and prio["instructions"] == QUESTIONS["priority"][1]
    assert list(prio["criteria"]) == PRIORITIES == ["baixa", "media", "alta"]
    for f in ("needs_review", "is_clear"):
        assert body["questions"][f]["type"] == "noul" and "criteria" not in body["questions"][f]


def test_overloaded_is_retried():
    assert 529 in RETRY_STATUS and 429 in RETRY_STATUS


def test_questions_are_about_workflow_never_diagnosis():
    texts = " ".join([q for _, q in QUESTIONS.values()] + list(PRIORITY_CRITERIA.values())).lower()
    assert "não faça diagnóstico" in texts and "não é prioridade clínica" in texts
    for forbidden in ("tratamento", "prescrev", "medicamento", "conduta"):
        assert forbidden not in texts


def test_state_is_minimal():
    state = finding_state("GAP", "MISSING_DATE", "Resultado de Hemoglobina sem data de coleta identificável.")
    assert state == {"achado": {"tipo": "GAP", "subtipo": "MISSING_DATE",
                                "resumo": "Resultado de Hemoglobina sem data de coleta identificável."}}
    assert "CASE-" not in json.dumps(state) and "rev-" not in json.dumps(state)


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

    def ask(self, state):
        self.calls = getattr(self, "calls", 0) + 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_one_call_per_finding():
    jev = _Broken(_resp())
    out = classify(jev, "CONFLICT", "DIVERGENT_VALUES", "x")
    assert jev.calls == 1 and out["jev_response_valid"] is True
    assert (out["needs_review"], out["priority"], out["is_clear"]) == (True, "alta", False)


@pytest.mark.parametrize(
    "reply", [ConnectionError("down"), {"output": "não sei"}, _resp(needs_review=NOUL(0.5)), _resp(priority=None)]
)
def test_failure_or_out_of_schema_is_invalid_not_dropped(reply):
    """A gold força revisão humana com prioridade alta quando jev_response_valid = false."""
    out = classify(_Broken(reply), "OUT_OF_DOCUMENT_RANGE", "ABOVE_DOCUMENT_RANGE", "x")
    assert out["jev_response_valid"] is False
    assert None in (out["needs_review"], out["priority"], out["is_clear"])
    assert set(json.loads(out["jev_raw_answers"])) == set(QUESTIONS)


def test_prompt_version_is_stable_and_short():
    assert PROMPT_VERSION.startswith("jevq-") and len(PROMPT_VERSION) == 17
