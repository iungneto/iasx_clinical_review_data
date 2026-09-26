from pyspark import cloudpickle
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql import types as T

import utilities
from utilities.clinical_rules import mask_identifiers
from utilities.pdf_parsing import extract_pages

# Os workers serverless não enxergam o root_path da pipeline: o pacote vai serializado junto com a UDF.
cloudpickle.register_pickle_by_value(utilities)

_PAGES_SCHEMA = T.StructType(
    [
        T.StructField(
            "pages",
            T.ArrayType(
                T.StructType(
                    [
                        T.StructField("page_num", T.IntegerType()),
                        T.StructField("text", T.StringType()),
                    ]
                )
            ),
        ),
        T.StructField("error", T.StringType()),
    ]
)


@F.udf(returnType=_PAGES_SCHEMA)
def _extract_pages_masked(content):
    result = extract_pages(bytes(content))
    for page in result["pages"]:
        page["text"] = mask_identifiers(page["text"])
    return result


@dp.table(
    name="silver_document_pages",
    comment="Texto por página de cada PDF, com identificadores diretos (CPF) mascarados. Base de toda evidência de origem.",
    table_properties={"iasx.layer": "silver"},
    cluster_by=["case_id", "document_id"],
)
@dp.expect_or_drop("valid_document", "case_id <> '' AND document_id <> ''")
def silver_document_pages():
    parsed = (
        spark.readStream.table("bronze_documents")
        .withColumn("parsed", _extract_pages_masked("content"))
    )
    return (
        parsed.select(
            "case_id",
            "document_id",
            "input_hash",
            "ingested_at",
            F.col("parsed.error").alias("parse_error"),
            F.explode_outer("parsed.pages").alias("page"),
        )
        .select(
            "case_id",
            "document_id",
            "input_hash",
            "ingested_at",
            "parse_error",
            F.col("page.page_num").alias("page_num"),
            F.col("page.text").alias("page_text"),
            (F.length(F.trim(F.coalesce("page.text", F.lit("")))) > 0).alias("is_textual"),
            F.current_timestamp().alias("extracted_at"),
        )
    )
