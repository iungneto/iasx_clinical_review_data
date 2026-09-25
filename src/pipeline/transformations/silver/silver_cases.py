from pyspark import pipelines as dp


@dp.temporary_view()
@dp.expect_all_or_drop(
    {
        "has_keys": "case_id IS NOT NULL AND review_id IS NOT NULL",
        "has_ts": "created_at IS NOT NULL",
    }
)
def cases_clean():
    return spark.readStream.table("bronze_cases").drop("_rescued_data", "_source_file")


dp.create_streaming_table(
    name="silver_cases",
    comment="Casos/revisões (último estado por case_id). review_id é o identificador técnico usado on-chain.",
    table_properties={"iasx.layer": "silver"},
)
dp.create_auto_cdc_flow(
    target="silver_cases",
    source="cases_clean",
    keys=["case_id"],
    sequence_by="created_at",
    stored_as_scd_type=1,
)
