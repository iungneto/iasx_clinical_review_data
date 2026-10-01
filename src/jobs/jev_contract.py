"""Contrato com o Jev (typesafe.ai) usado pelo job jev_classify. Python puro, testável com pytest.

O Jev decide só o fluxo de trabalho (precisa de revisão? qual prioridade de revisão? está claro?), nunca
diagnóstico, tratamento ou prioridade clínica. Toda resposta fica rastreável: versão das perguntas,
modelo, hash do que foi enviado e a resposta bruta.
"""

import hashlib
import json
import time

PRIORITIES = ["baixa", "media", "alta"]

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
    json.dumps({"questions": QUESTIONS, "priorities": PRIORITIES}, sort_keys=True, ensure_ascii=False).encode()
).hexdigest()[:12]

MAX_RAW_CHARS = 500


def finding_context(finding_type: str, finding_subtype: str, summary: str) -> str:
    # Minimização: só o necessário para a decisão de workflow. Sem case_id, review_id ou identificadores.
    return f"Tipo: {finding_type}. Subtipo: {finding_subtype}. Resumo: {summary}"


def request_hash(model: str, context: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{model}|{context}".encode()).hexdigest()


def build_request(model: str, schema: str, question: str, context: str) -> dict:
    """Monta o corpo de POST /v1/systemone. Ajuste aqui se o contrato publicado divergir."""
    body = {"model": model, "schema": schema, "input": f"{question}\n\n{context}"}
    if schema == "choice":
        body["options"] = PRIORITIES
    return body


def extract_answer(schema: str, payload):
    """Normaliza a resposta para bool (Noul) ou uma das PRIORITIES (Choice). None = fora do schema."""
    raw = payload.get("output", payload) if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw = raw.get("answer", raw.get("value", raw.get("choice")))
    if schema == "noul":
        if isinstance(raw, bool):
            return raw
        token = str(raw).strip().lower()
        return {"yes": True, "sim": True, "true": True, "no": False, "nao": False, "não": False, "false": False}.get(token)
    token = str(raw).strip().lower().replace("é", "e")
    return token if token in PRIORITIES else None


def classify(jev, finding_type: str, finding_subtype: str, summary: str) -> dict:
    """Faz as três perguntas e devolve os campos da decisão (sem chaves nem timestamp).
    Falha de rede ou resposta fora do schema vira None e jev_response_valid = false (a gold força revisão)."""
    context = finding_context(finding_type, finding_subtype, summary)
    answers, raw_answers = {}, {}
    for field, (schema, question) in QUESTIONS.items():
        try:
            raw = jev.ask(schema, question, context)
            answers[field] = extract_answer(schema, raw)
            raw_answers[field] = json.dumps(raw, ensure_ascii=False, default=str)[:MAX_RAW_CHARS]
        except Exception as exc:  # noqa: BLE001 - qualquer falha do Jev vira resposta inválida, não crash
            answers[field] = None
            raw_answers[field] = f"ERROR: {type(exc).__name__}"
    return {
        **answers,
        "jev_model": jev.model,
        "jev_prompt_version": PROMPT_VERSION,
        "jev_request_hash": request_hash(jev.model, context),
        "jev_raw_answers": json.dumps(raw_answers, ensure_ascii=False, sort_keys=True),
        "jev_response_valid": all(v is not None for v in answers.values()),
    }


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
        data = resp.json()
        models = data.get("data", data) if isinstance(data, dict) else data
        return models[0]["id"] if isinstance(models[0], dict) else models[0]

    def ask(self, schema: str, question: str, context: str):
        """Retorna o payload bruto da resposta; a normalização fica em extract_answer."""
        body = build_request(self.model, schema, question, context)
        for attempt in range(3):
            resp = self.session.post(f"{self.base_url}/v1/systemone", json=body, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()


class MockJev:
    """Determinístico, apenas para ensaio da demo sem chave. Sai marcado como mock-jev em toda a cadeia,
    inclusive no model_version da atestação."""

    model = "mock-jev"

    def ask(self, schema: str, question: str, context: str):
        risky = any(t in context for t in ("CONFLICT", "GAP", "UNIT_CHANGED"))
        if schema == "choice":
            return {"output": "alta" if risky else "media"}
        return {"output": True if "precisa ser revisado" in question else not risky}
