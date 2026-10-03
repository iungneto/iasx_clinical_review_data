from pyspark import cloudpickle
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql import types as T

import utilities
from utilities.clinical_rules import is_synthetic_declared, mask_identifiers
from utilities.pdf_parsing import extract_pages

# Os workers serverless não enxergam o root_path da pipeline: o pacote vai serializado junto com a UDF.
cloudpickle.register_pickle_by_value(utilities)

POLICY = spark.conf.get("iasx.policy_schema")  # funções de column mask (src/sql/access_policies.sql)

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
        T.StructField("synthetic_declared", T.BooleanType()),
    ]
)


@F.udf(returnType=_PAGES_SCHEMA)
def _extract_pages_masked(content):
    result = extract_pages(bytes(content))
    # MVP só com dados sintéticos: documento sem a declaração no texto não tem o conteúdo propagado.
    result["synthetic_declared"] = is_synthetic_declared([p["text"] for p in result["pages"]])
    for page in result["pages"]:
        page["text"] = mask_identifiers(page["text"]) if result["synthetic_declared"] else None
    return result


@dp.table(
    name="silver_document_pages",
    comment="Texto por página de cada PDF sintético, com identificadores diretos mascarados. Base de toda evidência de origem. "
    "Documento sem declaração de dado sintético fica sem texto (synthetic_declared = false) e vira lacuna.",
    table_properties={"iasx.layer": "silver"},
    cluster_by=["case_id", "document_id"],
    # Column mask: texto do documento só para iasx_clinical_text_readers.
    schema=(
        "case_id STRING, document_id STRING, input_hash STRING, ingested_at TIMESTAMP, parse_error STRING, "
        f"synthetic_declared BOOLEAN, page_num INT, page_text STRING MASK {POLICY}.iasx_mask_document_text, "
        "is_textual BOOLEAN, extracted_at TIMESTAMP"
    ),
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
            F.col("parsed.synthetic_declared").alias("synthetic_declared"),
            F.explode_outer("parsed.pages").alias("page"),
        )
        .select(
            "case_id",
            "document_id",
            "input_hash",
            "ingested_at",
            "parse_error",
            "synthetic_declared",
            F.col("page.page_num").alias("page_num"),
            F.col("page.text").alias("page_text"),
            (F.length(F.trim(F.coalesce("page.text", F.lit("")))) > 0).alias("is_textual"),
            F.current_timestamp().alias("extracted_at"),
        )
    )
