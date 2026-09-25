"""Feeds JSON gravados na landing pelo portal/backend e pelos jobs (Jev, verificação on-chain).
Contratos detalhados em docs/data_contracts.md."""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = spark.conf.get("iasx.landing_root")

FEEDS = {
    "cases": (
        "Registro técnico de casos/revisões (sem identificação de paciente).",
        "case_id STRING, review_id STRING, scenario STRING, created_at TIMESTAMP, manual_review_seconds_baseline INT",
    ),
    "jev_decisions": (
        "Saída estruturada do Jev (Noul/Choice) por achado, gravada pelo job jev_classify.",
        "finding_id STRING, review_id STRING, needs_review BOOLEAN, priority STRING, is_clear BOOLEAN, "
        "jev_model STRING, jev_request_hash STRING, jev_response_valid BOOLEAN, decided_at TIMESTAMP",
    ),
    "review_decisions": (
        "Ações do profissional no portal: CONFIRM / CORRECT / REJECT por achado e SIGNOFF da revisão.",
        "review_id STRING, scope STRING, finding_id STRING, action STRING, corrected_value DOUBLE, "
        "corrected_unit STRING, reviewer_tech_id STRING, decided_at TIMESTAMP",
    ),
    "attestations": (
        "Transações de atestação enviadas pelo backend ao programa Solana (somente dados técnicos).",
        "review_id STRING, cluster STRING, program_id STRING, pda_address STRING, tx_signature STRING, "
        "input_hash STRING, analysis_hash STRING, reviewed_hash STRING, workflow_version STRING, "
        "model_version STRING, status STRING, reviewer_tech_id STRING, submitted_at TIMESTAMP",
    ),
    "attestation_verifications": (
        "Leitura do estado on-chain (PDA) feita pelo job verify_onchain.",
        "review_id STRING, pda_address STRING, tx_signature STRING, account_found BOOLEAN, tx_confirmed BOOLEAN, "
        "onchain_input_hash STRING, onchain_analysis_hash STRING, onchain_reviewed_hash STRING, "
        "onchain_status STRING, slot BIGINT, error STRING, verified_at TIMESTAMP",
    ),
}


def _define_feed(feed: str, comment: str, schema: str):
    @dp.table(
        name=f"bronze_{feed}",
        comment=comment,
        table_properties={"iasx.layer": "bronze"},
    )
    def _feed():
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .option("pathGlobFilter", "*.json")
            .option("rescuedDataColumn", "_rescued_data")
            # Schema explícito: o contrato é fixo e a pasta pode começar vazia (sem inferência).
            .schema(schema + ", _rescued_data STRING")
            .load(f"{LANDING}/{feed}")
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.current_timestamp())
        )


for _feed_name, (_comment, _schema) in FEEDS.items():
    _define_feed(_feed_name, _comment, _schema)
