import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Módulos em Python puro de cada parte do bundle: pipeline (utilities), jobs, app, gerador sintético e base mockada.
for sub in ("src/pipeline", "src/jobs", "src/app", "tools", "tools/mock_db"):
    sys.path.insert(0, str(ROOT / sub))


@pytest.fixture(scope="session")
def synthetic():
    """Gera data/synthetic/ uma vez por sessão e devolve o módulo gerador."""
    import generate_synthetic_cases as gen

    gen.main()
    return gen


@pytest.fixture
def mock_db():
    """Backend mockado (tools/mock_db): tabelas exportadas do workspace e landing em memória, zerada por teste."""
    import mock_backend

    mock_backend.reset()
    return mock_backend


@pytest.fixture
def api(mock_db):
    """Cliente HTTP da API do JEV (src/app/app.py) rodando sobre a base mockada."""
    from fastapi.testclient import TestClient

    sys.modules["backend"] = mock_db  # app.py faz "import backend"
    from app import app

    return TestClient(app)
