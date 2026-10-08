"""Emulador do envio à Solana, usado enquanto o programa de atestação não está publicado (solana_mode = emulated).

Gera um recibo no mesmo formato do real (AttestationIn), com cluster = "emulated" e endereços base58 válidos,
mas nenhuma transação é enviada. A conta "on-chain" é reconstruída a partir deste recibo pelo verify_onchain
(onchain_layout.encode_account), e a gold marca a revisão como ATTESTED_EMULATED, nunca como ATTESTED.
"""

import hashlib

from models import EmulatedAttestationIn

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def _sha(*parts: str) -> bytes:
    return hashlib.sha256("\x1f".join(parts).encode()).digest()


# Endereço fixo e reconhecível do "programa" emulado: não existe em nenhum cluster.
EMULATOR_PROGRAM_ID = b58encode(_sha("iasx-solana-emulator", "program"))


def receipt(payload: dict, submitted_at: str) -> dict:
    """Recibo emulado a partir de uma linha de gold_attestation_payload."""
    review_id = payload["review_id"]
    hashes = (payload["input_hash"], payload["analysis_hash"], payload["reviewed_hash"])
    signature = _sha("tx", review_id, submitted_at, *hashes) + _sha("tx2", review_id, submitted_at, *hashes)
    return EmulatedAttestationIn(
        review_id=review_id,
        program_id=EMULATOR_PROGRAM_ID,
        pda_address=b58encode(_sha("pda", review_id)),
        tx_signature=b58encode(signature),
        input_hash=hashes[0],
        analysis_hash=hashes[1],
        reviewed_hash=hashes[2],
        workflow_version=payload["workflow_version"],
        model_version=payload["model_version"],
        reviewer_tech_id=payload["reviewer_tech_id"],
    ).model_dump()
