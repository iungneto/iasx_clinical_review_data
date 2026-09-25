from pyspark import pipelines as dp

LANDING = spark.conf.get("iasx.landing_root")


@dp.materialized_view(
    name="bronze_gabarito",
    comment="Gabarito dos casos sintéticos A/B/C: achados que o IASX deve encontrar (benchmark de cobertura).",
    table_properties={"iasx.layer": "bronze"},
)
def bronze_gabarito():
    return (
        spark.read.format("csv")
        .option("header", "true")
        .schema("case_id STRING, finding_type STRING, finding_subtype STRING, test_code STRING, exam_date DATE, expected_page INT, note STRING")
        .load(f"{LANDING}/gabarito")
    )
