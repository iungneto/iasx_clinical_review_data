from pyspark import pipelines as dp


@dp.temporary_view()
@dp.expect_all_or_drop(
    {
        "has_keys": "review_id IS NOT NULL AND decided_at IS NOT NULL AND reviewer_tech_id IS NOT NULL",
        "valid_scope_action": "(scope = 'FINDING' AND finding_id IS NOT NULL AND action IN ('CONFIRM', 'CORRECT', 'REJECT'))"
        " OR (scope = 'REVIEW' AND action = 'SIGNOFF')",
        "correction_has_value": "action <> 'CORRECT' OR corrected_value IS NOT NULL OR corrected_unit IS NOT NULL",
    }
)
def review_decisions_clean():
    return (
        spark.readStream.table("bronze_review_decisions")
        .selectExpr(
            "review_id",
            "upper(scope) AS scope",
            # A decisão de fechamento da revisão usa uma chave fixa para caber no mesmo par de chaves.
            "CASE WHEN upper(scope) = 'REVIEW' THEN '__REVIEW__' ELSE finding_id END AS finding_id",
            "upper(action) AS action",
            "corrected_value",
            "corrected_unit",
            "reviewer_tech_id",
            "decided_at",
        )
    )


dp.create_streaming_table(
    name="silver_review_decisions",
    comment="Última ação do profissional por achado (CONFIRM/CORRECT/REJECT) e o SIGNOFF da revisão.",
    table_properties={"iasx.layer": "silver"},
)
dp.create_auto_cdc_flow(
    target="silver_review_decisions",
    source="review_decisions_clean",
    keys=["review_id", "finding_id"],
    sequence_by="decided_at",
    stored_as_scd_type=1,
)
