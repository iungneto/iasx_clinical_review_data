from pyspark import pipelines as dp


@dp.temporary_view()
@dp.expect_or_drop("has_keys", "finding_id IS NOT NULL AND decided_at IS NOT NULL")
# Respostas fora do schema Noul/Choice não são descartadas: viram jev_response_valid = false
# e a regra de segurança na gold força revisão humana com prioridade alta.
@dp.expect("schema_ok", "priority IN ('baixa', 'media', 'alta') AND needs_review IS NOT NULL AND is_clear IS NOT NULL")
def jev_decisions_clean():
    return spark.readStream.table("bronze_jev_decisions").selectExpr(
        "finding_id",
        "review_id",
        "needs_review",
        "lower(priority) AS priority",
        "is_clear",
        "jev_model",
        "jev_request_hash",
        "coalesce(jev_response_valid, false) "
        "  AND lower(priority) IN ('baixa', 'media', 'alta') "
        "  AND needs_review IS NOT NULL AND is_clear IS NOT NULL AS jev_response_valid",
        "decided_at",
    )


dp.create_streaming_table(
    name="silver_jev_decisions",
    comment="Última decisão estruturada do Jev por achado (Noul: precisa de revisão? / Choice: prioridade / Noul: está claro?).",
    table_properties={"iasx.layer": "silver"},
)
dp.create_auto_cdc_flow(
    target="silver_jev_decisions",
    source="jev_decisions_clean",
    keys=["finding_id"],
    sequence_by="decided_at",
    stored_as_scd_type=1,
)
