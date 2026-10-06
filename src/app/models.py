"""Contratos de entrada da API do JEV. Espelham docs/data_contracts.md (feeds da landing)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# IDs técnicos viram nomes de pasta/arquivo na landing: nada de "/", "..", espaços etc.
# Também impedem texto livre (nome, diagnóstico) em campos que deveriam ser só identificadores técnicos.
TECH_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
SHA256 = r"^[0-9a-f]{64}$"
BASE58_PUBKEY = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
BASE58_SIGNATURE = r"^[1-9A-HJ-NP-Za-km-z]{64,88}$"
UNIT = r"^[A-Za-z0-9µμ%/^³.]{1,20}$"
# Campos de 32 bytes na conta on-chain (docs/onchain_account_layout.md).
ONCHAIN_VERSION = r"^[A-Za-z0-9._+,-]{1,32}$"


class CaseIn(BaseModel):
    case_id: str = Field(pattern=TECH_ID)
    review_id: str = Field(pattern=TECH_ID)
    # MVP: somente dados sintéticos (LGPD). Quem registra o caso declara isso explicitamente.
    data_classification: Literal["SYNTHETIC"]
    scenario: Optional[str] = Field(default=None, pattern=TECH_ID)
    manual_review_seconds_baseline: Optional[int] = Field(default=None, ge=0)


class ReviewCycleIn(BaseModel):
    # decisions_only: só chegaram decisões/signoff; o job pula a extração e o Jev (iasx_orchestration.job.yml).
    mode: Literal["full", "decisions_only"] = "full"


class ReviewDecisionIn(BaseModel):
    review_id: str = Field(pattern=TECH_ID)
    scope: Literal["FINDING", "REVIEW"]
    finding_id: Optional[str] = Field(default=None, pattern=TECH_ID)
    action: Literal["CONFIRM", "CORRECT", "REJECT", "SIGNOFF"]
    corrected_value: Optional[float] = None
    corrected_unit: Optional[str] = Field(default=None, pattern=UNIT)
    reviewer_tech_id: str = Field(pattern=TECH_ID)  # identificador técnico, nunca dado clínico/pessoal

    @model_validator(mode="after")
    def _check_scope(self):
        if self.scope == "FINDING":
            if not self.finding_id:
                raise ValueError("finding_id é obrigatório quando scope = FINDING")
            if self.action == "SIGNOFF":
                raise ValueError("SIGNOFF só vale para scope = REVIEW")
            if self.action == "CORRECT" and self.corrected_value is None and not self.corrected_unit:
                raise ValueError("CORRECT exige corrected_value e/ou corrected_unit")
        elif self.action != "SIGNOFF" or self.finding_id:
            raise ValueError("scope = REVIEW aceita apenas action = SIGNOFF, sem finding_id")
        return self


class AttestationIn(BaseModel):
    """Recibo da transação: somente dados técnicos, nunca dado clínico. MVP restrito à Devnet."""

    review_id: str = Field(pattern=TECH_ID)
    cluster: Literal["devnet"] = "devnet"
    program_id: str = Field(pattern=BASE58_PUBKEY)
    pda_address: str = Field(pattern=BASE58_PUBKEY)
    tx_signature: str = Field(pattern=BASE58_SIGNATURE)
    input_hash: str = Field(pattern=SHA256)
    analysis_hash: str = Field(pattern=SHA256)
    reviewed_hash: str = Field(pattern=SHA256)
    workflow_version: str = Field(pattern=ONCHAIN_VERSION)
    model_version: str = Field(pattern=ONCHAIN_VERSION)
    status: Literal["SUBMITTED"] = "SUBMITTED"
    reviewer_tech_id: str = Field(pattern=TECH_ID)
