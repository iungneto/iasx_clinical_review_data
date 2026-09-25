"""Gera os casos sintéticos da demo (seção 12 do documento) em data/synthetic/:

  pdfs/<case_id>/<document_id>.pdf   PDFs textuais (escritor PDF mínimo, sem dependências)
  cases.json                         registro técnico dos casos (JSON lines)
  gabarito.csv                       achados esperados, usados no benchmark (gold_benchmark)

Caso A — normal: consistente, sem lacunas (nenhum achado esperado).
Caso B — evolução: mesmo exame em três datas (variação temporal + alteração).
Caso C — principal: alteração + conflito + lacunas + página sem texto.

Uso:  python tools/generate_synthetic_cases.py
"""

import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic"
FOOTER = "Documento sintético para demonstração — não contém dados reais."


# --------------------------------------------------------------------------- PDF mínimo
def _pdf_string(text: str) -> str:
    out = []
    for byte in text.encode("cp1252"):
        ch = chr(byte)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= byte < 127:
            out.append(ch)
        else:
            out.append(f"\\{byte:03o}")
    return "(" + "".join(out) + ")"


def _text_stream(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 11 Tf", "15 TL", "50 790 Td"]
    ops += [f"{_pdf_string(line)} Tj T*" for line in lines]
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def _image_like_stream() -> bytes:
    # Página "digitalizada": só gráficos, nenhum texto extraível (OCR está fora do MVP).
    return b"0.85 g 60 420 475 330 re f 0.6 g 90 460 200 12 re f 90 440 320 12 re f"


def write_pdf(path: Path, pages: list[list[str] | None]) -> None:
    """pages: lista de páginas; cada página é uma lista de linhas, ou None para página sem texto."""
    objects: list[bytes] = []
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, lines in enumerate(pages):
        content_id = page_ids[i] + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        stream = _text_stream(lines) if lines is not None else _image_like_stream()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    buf += "".join(f"{off:010d} 00000 n \n" for off in offsets).encode()
    buf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(buf))


# --------------------------------------------------------------------------- casos
def lab_page(title: str, patient: str, cpf: str, date: str, results: list[str]) -> list[str]:
    return [title, f"Paciente: {patient}", f"CPF: {cpf}", f"Data da coleta: {date}", *results, "", FOOTER]


DOCUMENTS = {
    "CASE-A": {
        "A_lab_20260310": [
            lab_page(
                "LABORATÓRIO SINTÉTICO IASX — LAUDO DE EXAMES", "Paciente Sintético A", "111.222.333-44", "10/03/2026",
                [
                    "Hemoglobina: 13,8 g/dL (VR: 12,0 - 16,0)",
                    "Creatinina: 0,9 mg/dL (VR: 0,6 - 1,2)",
                    "Glicemia de jejum: 88 mg/dL (VR: 70 - 99)",
                    "Potássio: 4,2 mEq/L (VR: 3,5 - 5,1)",
                ],
            )
        ],
    },
    "CASE-B": {
        f"B_lab_{d[6:]}{d[3:5]}{d[:2]}": [
            lab_page(
                "LABORATÓRIO SINTÉTICO IASX — LAUDO DE EXAMES", "Paciente Sintético B", "222.333.444-55", d,
                [
                    f"Hemoglobina: {hb} g/dL (VR: 12,0 - 16,0)",
                    f"Creatinina: {cr} mg/dL (VR: 0,6 - 1,2)",
                    f"Glicemia de jejum: {glu} mg/dL (VR: 70 - 99)",
                ],
            )
        ]
        for d, hb, cr, glu in [
            ("05/01/2026", "13,5", "1,0", "92"),
            ("20/02/2026", "13,2", "1,1", "95"),
            ("02/04/2026", "13,4", "1,5", "118"),
        ]
    },
    "CASE-C": {
        "C_laudo_laboratorio": [
            lab_page(
                "LABORATÓRIO SINTÉTICO IASX — LAUDO DE EXAMES", "Paciente Sintético C", "123.456.789-09", "12/03/2026",
                [
                    "Hemoglobina: 10,9 g/dL (VR: 12,0 - 16,0)",
                    "Potássio: 5,9 mEq/L (VR: 3,5 - 5,1)",
                    "Creatinina: 1,1 mg/dL (VR: 0,6 - 1,2)",
                    "Sódio: ilegível mEq/L (VR: 135 - 145)",
                ],
            ),
            None,  # página 2: anexo digitalizado sem texto
        ],
        "C_resumo_alta": [
            [
                "RESUMO DE ALTA (SINTÉTICO)",
                "Paciente: Paciente Sintético C",
                "Exame externo trazido pelo paciente:",
                "Hemoglobina glicada: 6,4 %",
                "Data da coleta: 12/03/2026",
                "Potássio: 4,9 mEq/L (VR: 3,5 - 5,1)",
                "Glicemia de jejum: 105 mg/dL",
                "",
                FOOTER,
            ]
        ],
    },
}

CASES = [
    {"case_id": "CASE-A", "review_id": "rev-a-0001", "scenario": "A_normal"},
    {"case_id": "CASE-B", "review_id": "rev-b-0001", "scenario": "B_evolucao"},
    {"case_id": "CASE-C", "review_id": "rev-c-0001", "scenario": "C_principal"},
]

# case_id, finding_type, finding_subtype, test_code, exam_date, expected_page, note
GABARITO = [
    ("CASE-B", "OUT_OF_DOCUMENT_RANGE", "ABOVE_DOCUMENT_RANGE", "CREA", "2026-04-02", 1, "Creatinina 1,5 > 1,2"),
    ("CASE-B", "OUT_OF_DOCUMENT_RANGE", "ABOVE_DOCUMENT_RANGE", "GLU", "2026-04-02", 1, "Glicemia 118 > 99"),
    ("CASE-B", "TEMPORAL_VARIATION", "UP", "CREA", "2026-04-02", 1, "1,1 -> 1,5 (+36%)"),
    ("CASE-B", "TEMPORAL_VARIATION", "UP", "GLU", "2026-04-02", 1, "95 -> 118 (+24%)"),
    ("CASE-C", "OUT_OF_DOCUMENT_RANGE", "BELOW_DOCUMENT_RANGE", "HGB", "2026-03-12", 1, "Hemoglobina 10,9 < 12,0"),
    ("CASE-C", "OUT_OF_DOCUMENT_RANGE", "ABOVE_DOCUMENT_RANGE", "K", "2026-03-12", 1, "Potássio 5,9 > 5,1 (laudo)"),
    ("CASE-C", "CONFLICT", "DIVERGENT_VALUES", "K", "2026-03-12", 1, "5,9 (laudo) vs 4,9 (resumo de alta)"),
    ("CASE-C", "GAP", "ILLEGIBLE_VALUE", "NA", "2026-03-12", 1, "Sódio ilegível"),
    ("CASE-C", "GAP", "NON_TEXTUAL_PAGE", "", "", 2, "Anexo digitalizado"),
    ("CASE-C", "GAP", "MISSING_DATE", "HBA1C", "", 1, "HbA1c sem data"),
    ("CASE-C", "GAP", "MISSING_REFERENCE_RANGE", "HBA1C", "", 1, "HbA1c sem VR"),
    ("CASE-C", "GAP", "MISSING_REFERENCE_RANGE", "GLU", "2026-03-12", 1, "Glicemia sem VR no resumo"),
]


def main() -> None:
    for case_id, docs in DOCUMENTS.items():
        for document_id, pages in docs.items():
            write_pdf(OUT / "pdfs" / case_id / f"{document_id}.pdf", pages)

    with open(OUT / "cases.json", "w", encoding="utf-8") as fh:
        for case in CASES:
            # manual_review_seconds_baseline: preencher com o tempo MEDIDO de revisão manual de cada caso.
            fh.write(json.dumps({**case, "created_at": "2026-09-20T12:00:00Z", "manual_review_seconds_baseline": None}) + "\n")

    with open(OUT / "gabarito.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "finding_type", "finding_subtype", "test_code", "exam_date", "expected_page", "note"])
        writer.writerows(GABARITO)

    print(f"Casos sintéticos gerados em {OUT}")


if __name__ == "__main__":
    main()
