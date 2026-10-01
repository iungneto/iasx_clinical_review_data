"""Itens do checklist regulatório do MVP verificáveis no próprio repositório (docs/regulatory/risk_and_compliance.md)."""

import re
import subprocess
from pathlib import Path

from conftest import ROOT

SECRET_PATTERNS = {
    "token pessoal Databricks": re.compile(r"\bdapi[0-9a-f]{32}\b"),
    "secret OAuth Databricks": re.compile(r"\bdose[0-9a-f]{32}\b"),
    "chave privada PEM": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "client_secret literal": re.compile(r"client_secret\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{16,}"),
    "keypair Solana (64 bytes)": re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]"),
}
BINARY = {".pdf", ".png", ".jpg", ".lock"}


def _repo_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / f for f in out.splitlines() if (ROOT / f).is_file() and (ROOT / f).suffix not in BINARY]


def test_no_secrets_in_tracked_files():
    found = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in _repo_files()
        for name, pattern in SECRET_PATTERNS.items()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not found, found


def test_all_python_sources_compile():
    """Notebooks e transformações não são importados pelos testes; ao menos precisam compilar."""
    for path in _repo_files():
        if path.suffix == ".py":
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_attestation_payload_has_no_clinical_columns():
    """O payload que vai para a Solana só pode ter hashes, versões, status e IDs técnicos."""
    sql = (ROOT / "src/pipeline/transformations/gold/gold_attestation_payload.sql").read_text(encoding="utf-8")
    for column in ("source_text", "summary", "evidence", "test_name_raw", "value_raw", "page_text", "test_code", "exam_date"):
        assert column not in sql, column


# §5, §14 e §16 da matriz: alegações que o MVP não pode fazer (README, docs, telas, mensagens da API).
FORBIDDEN_CLAIMS = re.compile(
    r"aprovad[oa] pela anvisa|registrad[oa] na anvisa|notificad[oa] na anvisa|certificad[oa] (?:iso|iec|na iso)"
    r"|evita(?:r)? mortes?|previne mortes?|reduz(?:ir)? (?:o |os )?erros? m[ée]dicos?|garante (?:a )?seguran[cç]a"
    r"|(?:iasx|jev|sistema) (?:diagnostica|prescreve|recomenda tratamento)",
    re.IGNORECASE,
)
# A alegação pode aparecer quando está negada ou na lista do que é proibido dizer.
NEGATION = re.compile(r"\bn[ãa]o\b|\bnunca\b|\bproibid|\bsem\b|dizer que|alegar|afirmar", re.IGNORECASE)


def test_no_forbidden_claims():
    found = []
    for path in _repo_files():
        if path.resolve() == Path(__file__).resolve():  # a própria lista de padrões
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for m in FORBIDDEN_CLAIMS.finditer(line):
                if not NEGATION.search(line[: m.start()]):
                    found.append(f"{path.relative_to(ROOT)}:{n}: {m.group(0)}")
    assert not found, found


def test_regulatory_documents_exist_and_are_linked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for doc in ("docs/regulatory/intended_use.md", "docs/regulatory/risk_and_compliance.md"):
        assert (ROOT / doc).is_file() and doc in readme
