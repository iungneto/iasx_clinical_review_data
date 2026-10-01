"""Travas de conformidade da API do JEV (docs/regulatory/). Sem dependência do Databricks, testável com pytest."""

import io
import unicodedata

# Mesma declaração exigida pela pipeline (src/pipeline/utilities/clinical_rules.py, SYNTHETIC_MARKER).
SYNTHETIC_MARKER = "documento sintetico"

INTENDED_USE = (
    "Demonstração técnica com dados 100% sintéticos. Apoio à revisão e estruturação de informação: "
    "não diagnostica, não prescreve, não recomenda tratamento e não substitui o julgamento do profissional. "
    "Sem finalidade assistencial e sem regularização na Anvisa."
)
INTENDED_USE_HEADER = "synthetic-demo; review-support-only; not-for-clinical-use"


def _normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def declares_synthetic(pdf_bytes: bytes) -> bool:
    """True se o texto de alguma página do PDF traz a declaração de documento sintético.
    PDF ilegível ou sem texto não declara nada e é recusado na entrada."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return any(SYNTHETIC_MARKER in _normalize(page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 - PDF que não abre não prova nada
        return False
