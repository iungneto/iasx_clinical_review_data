"""Contratos de entrada da API do JEV. Espelham docs/data_contracts.md (feeds da landing)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# IDs técnicos viram nomes de pasta/arquivo na landing: nada de "/", "..", espaços etc.
TECH_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"


class CaseIn(BaseModel):
    case_id: str = Field(pattern=TECH_ID)
    review_id: str = Field(pattern=TECH_ID)
    scenario: Optional[str] = None
    manual_review_seconds_baseline: Optional[int] = Field(default=None, ge=0)


class ReviewDecisionIn(BaseModel):
    review_id: str = Field(pattern=TECH_ID)
    scope: Literal["FINDING", "REVIEW"]
    finding_id: Optional[str] = Field(default=None, pattern=TECH_ID)
    action: Literal["CONFIRM", "CORRECT", "REJECT", "SIGNOFF"]
    corrected_value: Optional[float] = None
    corrected_unit: Optional[str] = None
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
    review_id: str = Field(pattern=TECH_ID)
    cluster: str = "devnet"
    program_id: str
    pda_address: str
    tx_signature: str
    input_hash: str
    analysis_hash: str
    reviewed_hash: str
    workflow_version: str
    model_version: str
    status: str = "SUBMITTED"
    reviewer_tech_id: str = Field(pattern=TECH_ID)
