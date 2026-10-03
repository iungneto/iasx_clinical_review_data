"""Contrato com o Jev (typesafe.ai) usado pelo job jev_classify. Python puro, testável com pytest.

O Jev decide só o fluxo de trabalho (precisa de revisão? qual prioridade de revisão? está claro?), nunca
diagnóstico, tratamento ou prioridade clínica. Toda resposta fica rastreável: versão das perguntas,
modelo, hash do que foi enviado e a resposta bruta.
"""

import hashlib
import json
import time

PRIORITIES = ["baixa", "media", "alta"]

# Critérios do Choice (nome da opção → quando se aplica). As chaves são exatamente PRIORITIES.
PRIORITY_CRITERIA = {
    "baixa": "O achado é simples e consistente; a revisão pode esperar as demais.",
    "media": "O achado merece revisão, mas não tem divergência nem lacuna de dados.",
    "alta": "O achado tem conflito, lacuna, mudança de unidade ou ambiguidade que precisa ser vista primeiro.",
}

QUESTIONS = {
    "needs_review": (
        "noul",
        "Este achado extraído de um documento clínico sintético precisa ser revisado por um profissional "
        "antes de ser apresentado como confirmado? Responda sim ou não. Não faça diagnóstico.",
    ),
    "priority": (
        "choice",
        "Qual a prioridade de revisão deste achado para o fluxo de trabalho (não é prioridade clínica)?",
    ),
    "is_clear": (
        "noul",
        "A informação deste achado está clara e completa o suficiente para ser apresentada ao profissional? "
        "Responda sim ou não.",
    ),
}

# Muda sempre que uma pergunta ou opção muda: permite saber qual versão das perguntas gerou cada saída.
PROMPT_VERSION = "jevq-" + hashlib.sha256(
    json.dumps({"questions": QUESTIONS, "priorities": PRIORITY_CRITERIA}, sort_keys=True, ensure_ascii=False).encode()
).hexdigest()[:12]

# Noul devolve a probabilidade de "sim" (0 a 1). Na faixa incerta a resposta conta como fora do schema
# (None → jev_response_valid = false), e a gold força revisão humana em vez de arriscar um sim/não.
NOUL_YES_MIN = 0.65
NOUL_NO_MAX = 0.35

MAX_RAW_CHARS = 500


def finding_state(finding_type: str, finding_subtype: str, summary: str) -> dict:
    # Minimização: só o necessário para a decisão de workflow. Sem case_id, review_id ou identificadores.
    # Objeto com campos nomeados, como a doc da TypeSafe recomenda (https://docs.typesafe.ai/concepts/state.md).
    return {"achado": {"tipo": finding_type, "subtipo": finding_subtype, "resumo": summary}}


def request_hash(model: str, state: dict) -> str:
    canonical = json.dumps(state, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{PROMPT_VERSION}|{model}|{canonical}".encode()).hexdigest()


def build_request(model: str, state: dict) -> dict:
    """Corpo de POST /v1/systemone (https://docs.typesafe.ai/api.md). As três perguntas vão juntas sobre o mesmo
    state: o Jev as avalia em paralelo e de forma independente, numa única chamada."""
    questions = {}
    for field, (schema, instructions) in QUESTIONS.items():
        q = {"type": schema, "instructions": instructions}
        if schema == "choice":
            q["criteria"] = PRIORITY_CRITERIA
        questions[field] = q
    return {"model": model, "state": state, "questions": questions}


def extract_answer(schema: str, answer):
    """Normaliza uma resposta (`answers[<pergunta>]`) para bool (Noul) ou uma das PRIORITIES (Choice).
    None = fora do schema ou incerta."""
    try:
        if answer.get("type") != schema:
            return None
        if schema == "noul":
            p = float(answer["noul"])
            return True if p >= NOUL_YES_MIN else False if p <= NOUL_NO_MAX else None
        choice = answer["choice"]
        return choice if choice in PRIORITIES else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def classify(jev, finding_type: str, finding_subtype: str, summary: str) -> dict:
    """Faz as três perguntas numa chamada e devolve os campos da decisão (sem chaves nem timestamp).
    Falha de rede ou resposta fora do schema vira None e jev_response_valid = false (a gold força revisão)."""
    state = finding_state(finding_type, finding_subtype, summary)
    try:
        payload = jev.ask(state)
        returned = payload.get("answers", {}) if isinstance(payload, dict) else {}
        answers = {f: extract_answer(schema, returned.get(f)) for f, (schema, _) in QUESTIONS.items()}
        raw_answers = {
            f: json.dumps(returned.get(f), ensure_ascii=False, default=str)[:MAX_RAW_CHARS] for f in QUESTIONS
        }
    except Exception as exc:  # noqa: BLE001 - qualquer falha do Jev vira resposta inválida, não crash
        answers = dict.fromkeys(QUESTIONS)
        raw_answers = dict.fromkeys(QUESTIONS, f"ERROR: {type(exc).__name__}")
    return {
        **answers,
        "jev_model": jev.model,
        "jev_prompt_version": PROMPT_VERSION,
        "jev_request_hash": request_hash(jev.model, state),
        "jev_raw_answers": json.dumps(raw_answers, ensure_ascii=False, sort_keys=True),
        "jev_response_valid": all(v is not None for v in answers.values()),
    }


# 529 = TypeSafe sobrecarregado; a doc pede nova tentativa com backoff, como no 429.
RETRY_STATUS = (429, 500, 502, 503, 504, 529)


class JevClient:
    def __init__(self, base_url: str, api_key: str, model: str = ""):
        import requests  # import local: o módulo é testado sem dependências de rede

        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        self.model = model or self._first_model()

    def _first_model(self) -> str:
        resp = self.session.get(f"{self.base_url}/v1/models", timeout=30)
        resp.raise_for_status()
        return resp.json()["models"][0]["name"]

    def ask(self, state: dict):
        """Retorna o payload bruto da resposta; a normalização fica em extract_answer."""
        body = build_request(self.model, state)
        for attempt in range(3):
            resp = self.session.post(f"{self.base_url}/v1/systemone", json=body, timeout=60)
            if resp.status_code in RETRY_STATUS and attempt < 2:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()


class MockJev:
    """Determinístico, apenas para ensaio da demo sem chave. Sai marcado como mock-jev em toda a cadeia,
    inclusive no model_version da atestação. Responde no mesmo formato da API real."""

    model = "mock-jev"

    def ask(self, state: dict):
        risky = any(t in json.dumps(state) for t in ("CONFLICT", "GAP", "UNIT_CHANGED"))
        priority = "alta" if risky else "media"
        answers = {
            "needs_review": {"type": "noul", "noul": 1.0},
            "priority": {"type": "choice", "choice": priority, "confidence": 1.0,
                         "probabilities": {p: float(p == priority) for p in PRIORITIES}},
            "is_clear": {"type": "noul", "noul": 0.0 if risky else 1.0},
        }
        return {"model": self.model, "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}
