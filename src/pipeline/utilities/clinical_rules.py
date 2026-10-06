"""Extração determinística de resultados de exames a partir do texto de uma página de PDF.

Regras do MVP aplicadas aqui:
- nada é inventado: valor, unidade, data ou faixa ausentes ficam None e viram lacuna downstream;
- todo resultado carrega o trecho de origem (linha) e os offsets de caractere na página;
- a faixa de referência usada é somente a informada no próprio documento;
- valor que não é um número simples (ex.: "< 0,5", "1,0 ou 1,3") vira AMBIGUOUS, nunca um número escolhido;
- identificadores diretos são mascarados preservando o comprimento, para que os offsets continuem válidos.

Módulo em Python puro (sem Spark) para poder ser testado localmente com pytest.
"""

import re
import unicodedata
from datetime import datetime

EXTRACTOR_VERSION = "extract-rules-1.2.0"

# O MVP aceita somente documentos sintéticos (LGPD): o PDF precisa declarar isso no próprio texto.
SYNTHETIC_MARKER = "documento sintetico"

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
    "ldl-colesterol": "LDL",
    "ldl colesterol": "LDL",
    "colesterol ldl": "LDL",
    "hdl-colesterol": "HDL",
    "hdl colesterol": "HDL",
    "colesterol hdl": "HDL",
    "triglicerideos": "TG",
    "triglicerides": "TG",
    "pcr": "CRP",
    "proteina c reativa": "CRP",
}

ILLEGIBLE_TOKENS = {"ilegivel", "ilegível", "???"}
MISSING_TOKENS = {"n/d", "nd", "---", "-", "nao informado", "não informado", "pendente"}

_NUM = r"\d+(?:[.,]\d+)?"
_VALUE_TOKENS = _NUM + r"|ileg[ií]vel|\?\?\?|N/D|ND|---|-|n[aã]o informado|pendente"
_UNIT = r"[A-Za-zµμ%/][A-Za-z0-9µμ%/\^³.]*"
_DATE_LABEL = r"data(?:\s+da\s+coleta|\s+do\s+exame|\s+de\s+coleta)?"
DATE_RE = re.compile(r"(?i)\b" + _DATE_LABEL + r"\s*:\s*(?P<date>\d{2}/\d{2}/\d{4})")
RESULT_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 \-/]*?)\s*:\s*"
    r"(?P<value>" + _VALUE_TOKENS + r")"
    r"(?:\s+(?P<unit>" + _UNIT + r"))?"
    r"(?:\s*\(\s*VR\s*:\s*(?P<low>" + _NUM + r")\s*(?:-|a|–)\s*(?P<high>" + _NUM + r")\s*\))?"
    r"\s*$",
    re.IGNORECASE,
)
# Linha "Nome: resto" que não casou com RESULT_RE: se o nome for de um exame conhecido, o valor é ambíguo.
LOOSE_RESULT_RE = re.compile(r"^(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 \-/]*?)\s*:\s*(?P<rest>\S.*)$")

# Laudo em tabela (o texto do PDF chega com uma célula por linha):
#   Exame / Resultado / Unidade / Valor de referência  →  Hemoglobina / 12,8 / g/dL / 12,0–16,0
TABLE_HEADER = ("exame", "resultado", "unidade")
TABLE_REF_HEADERS = {"valor de referencia", "valores de referencia", "referencia", "vr"}
CELL_NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 \-/()]*$")
CELL_VALUE_RE = re.compile(r"^(?:" + _VALUE_TOKENS + r")$", re.IGNORECASE)
# Unidade em célula própria: aceita "10³/µL", mas não um número solto nem uma faixa.
CELL_UNIT_RE = re.compile(r"^(?=.*[A-Za-zµμ%/])[A-Za-z0-9µμ%/\^³.]+$")
CELL_RANGE_RE = re.compile(r"^(?P<low>" + _NUM + r")\s*(?:-|a|–|—)\s*(?P<high>" + _NUM + r")$")
# Faixa de um lado só, como o documento informa: "<190" (normal abaixo de 190), ">40" (normal acima de 40).
CELL_BOUND_RE = re.compile(r"^(?P<op><=?|>=?|≤|≥)\s*(?P<num>" + _NUM + r")$")
DATE_LABEL_LINE_RE = re.compile(r"(?i)^" + _DATE_LABEL + r"$")
DATE_ONLY_RE = re.compile(r"^(?P<date>\d{2}/\d{2}/\d{4})$")

# Identificadores diretos (titular e profissional), mascarados antes de qualquer persistência fora da bronze.
_IDENTIFIER_LABELS = (
    r"(?:paciente|nome(?:\s+do\s+paciente|\s+da\s+m[aã]e)?|m[aã]e|data\s+de\s+nascimento|"
    r"nascimento|rg|cns|cart[aã]o\s+sus|prontu[aá]rio|telefone|celular|endere[cç]o|e-?mail|"
    r"m[eé]dico(?:\s+solicitante|\s+respons[aá]vel)?|crm|respons[aá]vel\s+t[eé]cnico|conv[eê]nio)"
)
IDENTIFIER_LABEL_RE = re.compile(
    r"(?im)^(?P<label>[ \t]*" + _IDENTIFIER_LABELS + r"[ \t]*:[ \t]*)(?P<value>[^\r\n]*)"
)
# Laudo em formulário: o rótulo ocupa a linha inteira e o valor vem na linha seguinte.
IDENTIFIER_LABEL_LINE_RE = re.compile(
    r"(?im)^(?P<label>[ \t]*" + _IDENTIFIER_LABELS + r"[ \t]*\r?\n)(?P<value>[^\r\n]*)"
)
CRM_RE = re.compile(r"(?i)\bCRM[\s\-/]*(?:[A-Z]{2}[\s\-/]*)?\d{4,}(?:[\s\-/]*[A-Z]{2}\b)?")
# Um identificador já encontrado num rótulo também é mascarado onde mais aparecer (ex.: assinatura no rodapé).
MIN_REPEATED_IDENTIFIER = 4
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNS_RE = re.compile(r"\b\d{3}\s?\d{4}\s?\d{4}\s?\d{4}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?:\(\d{2}\)\s?)?\b9?\d{4}-\d{4}\b")


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


def _stars(match: re.Match) -> str:
    # Preserva comprimento e pontuação: os offsets das evidências continuam apontando para a mesma linha.
    return re.sub(r"[^\s.\-/()]", "*", match.group(0))


def mask_identifiers(text: str) -> str:
    """Mascara identificadores diretos (nome, nascimento, documentos, contato, profissional) preservando o
    comprimento do texto. Roda antes de qualquer persistência fora da camada bronze."""
    text = text or ""
    found = set()

    def by_label(m: re.Match) -> str:
        value = m.group("value")
        if len(value.strip()) >= MIN_REPEATED_IDENTIFIER:
            found.add(value.strip())
        return m.group("label") + re.sub(r"\S", "*", value)

    text = IDENTIFIER_LABEL_RE.sub(by_label, text)
    text = IDENTIFIER_LABEL_LINE_RE.sub(by_label, text)
    for value in sorted(found, key=len, reverse=True):
        text = re.sub(re.escape(value), lambda m: re.sub(r"\S", "*", m.group(0)), text)
    for pattern in (CPF_RE, CNS_RE, EMAIL_RE, PHONE_RE, CRM_RE):
        text = pattern.sub(_stars, text)
    return text


def is_synthetic_declared(texts: list[str]) -> bool:
    """True se alguma página declara que o documento é sintético. É uma trava contra envio acidental de
    documento real, não uma prova de que o conteúdo é sintético."""
    return any(SYNTHETIC_MARKER in strip_accents(t or "").lower() for t in texts)


def _reference(low: float | None, high: float | None) -> str | None:
    return "RANGE" if low is not None and high is not None else None


def _parse_cell_reference(cell: str) -> tuple[float | None, float | None, str] | None:
    """Faixa de referência numa célula: "12,0–16,0", "<190", ">40". None se a célula não for uma faixa."""
    m = CELL_RANGE_RE.match(cell)
    if m:
        return to_float(m.group("low")), to_float(m.group("high")), "RANGE"
    m = CELL_BOUND_RE.match(cell)
    if m:
        op = {"<": "LT", "<=": "LE", "≤": "LE", ">": "GT", ">=": "GE", "≥": "GE"}[m.group("op")]
        bound = to_float(m.group("num"))
        return (None, bound, op) if op in ("LT", "LE") else (bound, None, op)
    return None


def _is_table_header(cells: list[str]) -> bool:
    return tuple(strip_accents(c).lower() for c in cells[: len(TABLE_HEADER)]) == TABLE_HEADER


def _value_status(value_raw: str) -> tuple[str, float | None]:
    token = strip_accents(value_raw).lower()
    if token in {strip_accents(t) for t in ILLEGIBLE_TOKENS}:
        return "ILLEGIBLE", None
    if token in {strip_accents(t) for t in MISSING_TOKENS}:
        return "MISSING", None
    return "OK", to_float(value_raw)


def _parse_table_row(lines: list[tuple[int, int, str]], i: int) -> tuple[dict, int] | None:
    """Uma linha da tabela a partir da célula do nome em lines[i]: nome, valor, unidade (opcional) e faixa
    (opcional). Devolve (campos, índice da próxima célula) ou None quando lines[i] não abre uma linha."""
    name = lines[i][2]
    if not CELL_NAME_RE.match(name) or i + 1 >= len(lines):
        return None
    value_raw = lines[i + 1][2]
    j = i + 2
    if CELL_VALUE_RE.match(value_raw):
        value_status, value = _value_status(value_raw)
    elif normalize_test_name(name)[1] and not CELL_NAME_RE.match(value_raw):
        value_status, value = "AMBIGUOUS", None  # exame conhecido com valor fora do formato simples
    else:
        return None
    unit, low, high, ref_kind = None, None, None, None
    if j < len(lines) and CELL_UNIT_RE.match(lines[j][2]) and not normalize_test_name(lines[j][2])[1]:
        unit = lines[j][2]
        j += 1
    if j < len(lines):
        reference = _parse_cell_reference(lines[j][2])
        if reference:
            low, high, ref_kind = reference
            j += 1
    if value_status == "AMBIGUOUS":
        unit, low, high, ref_kind = None, None, None, None
    return {
        "name": name, "value_raw": value_raw, "value_status": value_status, "value": value,
        "unit": unit, "ref_low": low, "ref_high": high, "ref_kind": ref_kind,
    }, j


def parse_page(text: str) -> list[dict]:
    """Extrai resultados de exame de uma página. Uma data "Data da coleta: dd/mm/aaaa" (ou o rótulo numa
    linha e a data na seguinte) vale para os resultados seguintes da mesma página até a próxima data.
    Aceita uma linha por resultado ("Exame: valor unidade (VR: a - b)") e laudos em tabela, em que o texto
    do PDF chega com uma célula por linha depois do cabeçalho Exame / Resultado / Unidade."""
    text = text or ""
    lines = []  # (line_no, char_start, stripped)
    offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if stripped:
            lines.append((line_no, offset + line.index(stripped), stripped))
        offset += len(line)

    results = []
    current_date, current_date_text = None, None
    in_table = False
    i = 0
    while i < len(lines):
        line_no, char_start, stripped = lines[i]

        date_match = DATE_RE.search(stripped)
        if date_match:
            current_date, current_date_text = parse_date(date_match.group("date")), stripped
            i += 1
            continue
        if DATE_LABEL_LINE_RE.match(stripped) and i + 1 < len(lines) and DATE_ONLY_RE.match(lines[i + 1][2]):
            current_date = parse_date(lines[i + 1][2])
            current_date_text = text[char_start : lines[i + 1][1] + len(lines[i + 1][2])]
            i += 2
            continue

        if _is_table_header([c for _, _, c in lines[i : i + len(TABLE_HEADER)]]):
            in_table = True
            i += len(TABLE_HEADER)
            if i < len(lines) and strip_accents(lines[i][2]).lower() in TABLE_REF_HEADERS:
                i += 1
            continue

        row = _parse_table_row(lines, i) if in_table else None
        if row:
            fields, next_i = row
            _, last_start, last_text = lines[next_i - 1]
            span_end = last_start + len(last_text)
            i = next_i
        else:
            in_table = False  # a tabela termina na primeira célula que não abre uma linha de resultado
            m = RESULT_RE.match(stripped)
            if m:
                value_status, value = _value_status(m.group("value"))
                low, high = to_float(m.group("low")), to_float(m.group("high"))
                fields = {
                    "name": m.group("name").strip(), "value_raw": m.group("value"), "value_status": value_status,
                    "value": value, "unit": m.group("unit"), "ref_low": low, "ref_high": high,
                    "ref_kind": _reference(low, high),
                }
            else:
                loose = LOOSE_RESULT_RE.match(stripped)
                if not loose or not normalize_test_name(loose.group("name").strip())[1]:
                    i += 1
                    continue  # cabeçalho, rodapé ou texto livre: não é resultado de exame
                # Exame conhecido com valor fora do formato simples: registrado como está, sem escolher número.
                fields = {
                    "name": loose.group("name").strip(), "value_raw": loose.group("rest"), "value_status": "AMBIGUOUS",
                    "value": None, "unit": None, "ref_low": None, "ref_high": None, "ref_kind": None,
                }
            span_end = char_start + len(stripped)
            i += 1

        name = fields["name"]
        if strip_accents(name).lower() in {"paciente", "cpf", "medico", "crm", "convenio"}:
            continue
        test_code, test_known = normalize_test_name(name)
        results.append(
            {
                "line_no": line_no,
                "char_start": char_start,
                "char_end": span_end,
                "source_text": text[char_start:span_end],
                "exam_date": current_date,
                "date_source_text": current_date_text,
                "test_name_raw": name,
                "test_code": test_code,
                "test_known": test_known,
                "value_raw": fields["value_raw"],
                "value": fields["value"],
                "value_status": fields["value_status"],
                "unit": fields["unit"],
                "ref_low": fields["ref_low"],
                "ref_high": fields["ref_high"],
                "ref_kind": fields["ref_kind"],
                "extractor_version": EXTRACTOR_VERSION,
            }
        )
    return results
