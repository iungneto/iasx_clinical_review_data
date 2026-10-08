"""Sobe a API do JEV (src/app/app.py) localmente sobre a base mockada, sem Databricks nem token.

    uv run python tools/mock_db/serve.py            # http://127.0.0.1:8000/docs

As escritas ficam só em memória e somem ao encerrar. Para ensaiar o frontend; não substitui o app publicado.
"""

import os
import sys
from pathlib import Path

import uvicorn

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "src/app")]

import mock_backend  # noqa: E402

sys.modules["backend"] = mock_backend  # app.py faz "import backend": passa a usar o mock
os.environ.setdefault("IASX_SOLANA_MODE", "emulated")  # como o target dev, sem programa publicado

from app import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
