"""Leitura de PDF textual página a página (OCR fica fora do MVP)."""

import io


def extract_pages(pdf_bytes: bytes) -> dict:
    """Retorna {"pages": [{"page_num", "text"}], "error": str|None}.
    Um PDF ilegível não derruba a pipeline: o erro é registrado e vira lacuna."""
    from pypdf import PdfReader  # import local: só existe no ambiente da pipeline

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [
            {"page_num": i + 1, "text": page.extract_text() or ""}
            for i, page in enumerate(reader.pages)
        ]
        return {"pages": pages, "error": None}
    except Exception as exc:  # noqa: BLE001 - qualquer falha de parsing é tratada como lacuna
        return {"pages": [], "error": f"{type(exc).__name__}: {exc}"[:500]}
