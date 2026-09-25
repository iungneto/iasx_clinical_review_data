from pyspark import pipelines as dp

_SHA256 = "RLIKE '^[0-9a-f]{64}$'"


@dp.temporary_view()
@dp.expect_all_or_drop(
    {
        "has_keys": "review_id IS NOT NULL AND submitted_at IS NOT NULL",
        "has_tx": "tx_signature IS NOT NULL AND pda_address IS NOT NULL",
        "hashes_are_sha256": f"input_hash {_SHA256} AND analysis_hash {_SHA256} AND reviewed_hash {_SHA256}",
    }
)
def attestations_clean():
    return spark.readStream.table("bronze_attestations").drop("_rescued_data", "_source_file")


dp.create_streaming_table(
    name="silver_attestations",
    comment="Última transação de atestação enviada à Solana por revisão (somente dados técnicos não clínicos).",
    table_properties={"iasx.layer": "silver"},
)
dp.create_auto_cdc_flow(
    target="silver_attestations",
    source="attestations_clean",
    keys=["review_id"],
    sequence_by="submitted_at",
    stored_as_scd_type=1,
)


@dp.temporary_view()
@dp.expect_or_drop("has_keys", "review_id IS NOT NULL AND verified_at IS NOT NULL")
def attestation_verifications_clean():
    return spark.readStream.table("bronze_attestation_verifications").drop("_rescued_data", "_source_file")


dp.create_streaming_table(
    name="silver_attestation_verifications",
    comment="Última leitura do estado on-chain (PDA da revisão) feita pelo job verify_onchain.",
    table_properties={"iasx.layer": "silver"},
)
dp.create_auto_cdc_flow(
    target="silver_attestation_verifications",
    source="attestation_verifications_clean",
    keys=["review_id"],
    sequence_by="verified_at",
    stored_as_scd_type=1,
)
