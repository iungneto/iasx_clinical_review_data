"""Contrato com o programa Solana de atestação (docs/onchain_account_layout.md). Python puro, testável com pytest.

A conta guarda só hashes, versões, status e a carteira técnica do revisor: nenhum dado clínico ou pessoal.
"""

import hashlib
import struct
from urllib.parse import urlparse

STATUS = {0: "CREATED", 1: "PROCESSING", 2: "AI_REVIEW_READY", 3: "HUMAN_REVIEW_REQUIRED",
          4: "CONFIRMED", 5: "CORRECTED", 6: "ATTESTED"}
# discriminator + review_id_hash + 3 hashes + workflow_version + model_version + status + reviewer + attested_at + bump
ACCOUNT_SIZE = 8 + 32 * 4 + 32 + 32 + 1 + 32 + 8 + 1


def assert_devnet(rpc_url: str) -> None:
    """O MVP só atesta na Devnet. Qualquer outro cluster (mainnet, testnet) é recusado antes de qualquer chamada."""
    host = (urlparse(rpc_url).hostname or "").lower()
    if "devnet" not in host:
        raise ValueError(f"RPC fora da Devnet recusado no MVP: {host or rpc_url!r}")


def review_id_hash(review_id: str) -> str:
    # Seed da PDA: o review_id em texto não vai para a cadeia.
    return hashlib.sha256(review_id.encode()).hexdigest()


def decode_account(data: bytes) -> dict:
    if len(data) < ACCOUNT_SIZE:
        raise ValueError(f"conta com {len(data)} bytes, esperado >= {ACCOUNT_SIZE}")
    o = 8  # discriminator Anchor
    rid_hash, input_hash, analysis_hash, reviewed_hash = (data[o + 32 * i : o + 32 * (i + 1)].hex() for i in range(4))
    o += 128
    workflow_version = data[o : o + 32].rstrip(b"\0").decode()
    model_version = data[o + 32 : o + 64].rstrip(b"\0").decode()
    o += 64
    status = STATUS.get(data[o], f"UNKNOWN_{data[o]}")
    o += 1 + 32  # status + reviewer pubkey
    (attested_at,) = struct.unpack_from("<q", data, o)
    return {
        "review_id_hash": rid_hash,
        "input_hash": input_hash,
        "analysis_hash": analysis_hash,
        "reviewed_hash": reviewed_hash,
        "workflow_version": workflow_version,
        "model_version": model_version,
        "status": status,
        "attested_at": attested_at,
    }
