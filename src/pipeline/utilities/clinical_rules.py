"""Extração determinística de resultados de exames a partir do texto de uma página de PDF.

Regras do MVP aplicadas aqui:
- nada é inventado: valor, unidade, data ou faixa ausentes ficam None e viram lacuna downstream;
- todo resultado carrega o trecho de origem (linha) e os offsets de caractere na página;
- a faixa de referência usada é somente a informada no próprio documento.

Módulo em Python puro (sem Spark) para poder ser testado localmente com pytest.
"""

import re
import unicodedata
from datetime import datetime

EXTRACTOR_VERSION = "extract-rules-1.0.0"

# Dicionário sintético de sinônimos → código técnico do exame (não é base de diretrizes).
TEST_SYNONYMS = {
    "hemoglobina": "HGB",
    "hb": "HGB",
    "hematocrito": "HCT",
    "leucocitos": "WBC",
    "plaquetas": "PLT",
    "creatinina": "CREA",
    "ureia": "UREA",
    "potassio": "K",
    "sodio": "NA",
    "glicemia de jejum": "GLU",
    "glicose": "GLU",
    "hemoglobina glicada": "HBA1C",
    "hba1c": "HBA1C",
    "tsh": "TSH",
    "colesterol total": "CHOL",
    "pcr": "CRP",
    "proteina c reativa": "CRP",
}

ILLEGIBLE_TOKENS = {"ilegivel", "ilegível", "???"}
MISSING_TOKENS = {"n/d", "nd", "---", "-", "nao informado", "não informado", "pendente"}

_NUM = r"\d+(?:[.,]\d+)?"
DATE_RE = re.compile(
    r"(?i)\bdata(?:\s+da\s+coleta|\s+do\s+exame|\s+de\s+coleta)?\s*:\s*(?P<date>\d{2}/\d{2}/\d{4})"
)
RESULT_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 \-/]*?)\s*:\s*"
    r"(?P<value>" + _NUM + r"|ileg[ií]vel|\?\?\?|N/D|ND|---|-|n[aã]o informado|pendente)"
    r"(?:\s+(?P<unit>[A-Za-zµμ%/][A-Za-z0-9µμ%/\^³.]*))?"
    r"(?:\s*\(\s*VR\s*:\s*(?P<low>" + _NUM + r")\s*(?:-|a|–)\s*(?P<high>" + _NUM + r")\s*\))?"
    r"\s*$",
    re.IGNORECASE,
)
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_test_name(name: str) -> tuple[str, bool]:
    """Retorna (test_code, test_known). Exames desconhecidos recebem código derivado do nome."""
    key = re.sub(r"\s+", " ", strip_accents(name).lower()).strip()
    if key in TEST_SYNONYMS:
        return TEST_SYNONYMS[key], True
    return "UNK_" + re.sub(r"[^A-Z0-9]+", "_", key.upper()).strip("_"), False


def to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_date(raw: str) -> str | None:
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None  # data impossível (ex.: 31/02) vira lacuna, não é corrigida


def mask_identifiers(text: str) -> str:
    """Mascara CPF antes de qualquer persistência fora da camada bronze."""
    return CPF_RE.sub("***.***.***-**", text or "")


def parse_page(text: str) -> list[dict]:
    """Extrai resultados de exame de uma página. Uma data "Data da coleta: dd/mm/aaaa"
    vale para as linhas seguintes da mesma página até a próxima data."""
    results = []
    current_date, current_date_text = None, None
    offset = 0
    for line_no, line in enumerate((text or "").splitlines(keepends=True), start=1):
        start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped:
            continue

        date_match = DATE_RE.search(stripped)
        if date_match:
            current_date = parse_date(date_match.group("date"))
            current_date_text = stripped
            continue

        m = RESULT_RE.match(stripped)
        if not m:
            continue
        name = m.group("name").strip()
        if strip_accents(name).lower() in {"paciente", "cpf", "medico", "crm", "convenio"}:
            continue

        value_raw = m.group("value")
        token = strip_accents(value_raw).lower()
        if token in {strip_accents(t) for t in ILLEGIBLE_TOKENS}:
            value_status, value = "ILLEGIBLE", None
        elif token in {strip_accents(t) for t in MISSING_TOKENS}:
            value_status, value = "MISSING", None
        else:
            value_status, value = "OK", to_float(value_raw)

        test_code, test_known = normalize_test_name(name)
        char_start = start + line.index(stripped)
        results.append(
            {
                "line_no": line_no,
                "char_start": char_start,
                "char_end": char_start + len(stripped),
                "source_text": stripped,
                "exam_date": current_date,
                "date_source_text": current_date_text,
                "test_name_raw": name,
                "test_code": test_code,
                "test_known": test_known,
                "value_raw": value_raw,
                "value": value,
                "value_status": value_status,
                "unit": m.group("unit"),
                "ref_low": to_float(m.group("low")),
                "ref_high": to_float(m.group("high")),
                "extractor_version": EXTRACTOR_VERSION,
            }
        )
    return results
