from pyspark import cloudpickle
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql import types as T

import utilities
from utilities.clinical_rules import parse_page

# Os workers serverless não enxergam o root_path da pipeline: o pacote vai serializado junto com a UDF.
cloudpickle.register_pickle_by_value(utilities)

_RESULT_SCHEMA = T.ArrayType(
    T.StructType(
        [
            T.StructField("line_no", T.IntegerType()),
            T.StructField("char_start", T.IntegerType()),
            T.StructField("char_end", T.IntegerType()),
            T.StructField("source_text", T.StringType()),
            T.StructField("exam_date", T.StringType()),
            T.StructField("date_source_text", T.StringType()),
            T.StructField("test_name_raw", T.StringType()),
            T.StructField("test_code", T.StringType()),
            T.StructField("test_known", T.BooleanType()),
            T.StructField("value_raw", T.StringType()),
            T.StructField("value", T.DoubleType()),
            T.StructField("value_status", T.StringType()),
            T.StructField("unit", T.StringType()),
            T.StructField("ref_low", T.DoubleType()),
            T.StructField("ref_high", T.DoubleType()),
            T.StructField("extractor_version", T.StringType()),
        ]
    )
)

_parse_page_udf = F.udf(parse_page, _RESULT_SCHEMA)


@dp.table(
    name="silver_lab_results",
    comment="Resultados de exame extraídos com fonte (documento, página, linha, offsets e trecho). Ausências não são preenchidas.",
    table_properties={"iasx.layer": "silver"},
    cluster_by=["case_id", "test_code"],
)
@dp.expect_all_or_drop(
    {
        "has_source": "source_text IS NOT NULL AND page_num IS NOT NULL",
        "valid_status": "value_status IN ('OK', 'ILLEGIBLE', 'MISSING')",
    }
)
@dp.expect("value_present_when_ok", "value_status <> 'OK' OR value IS NOT NULL")
def silver_lab_results():
    return (
        spark.readStream.table("silver_document_pages")
        .where("is_textual")
        .select(
            "case_id",
            "document_id",
            "page_num",
            "ingested_at",
            F.explode(_parse_page_udf("page_text")).alias("r"),
        )
        .select("case_id", "document_id", "page_num", "ingested_at", "r.*")
        .withColumn("exam_date", F.to_date("exam_date"))
        .withColumn(
            "measurement_id",
            F.sha2(F.concat_ws("|", "document_id", "page_num", "char_start"), 256),
        )
        .withColumn("processed_at", F.current_timestamp())
    )
