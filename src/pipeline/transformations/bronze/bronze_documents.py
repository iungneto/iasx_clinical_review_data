from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = spark.conf.get("iasx.landing_root")
POLICY = spark.conf.get("iasx.policy_schema")  # funções de column mask (src/sql/access_policies.sql)


@dp.table(
    name="bronze_documents",
    comment="PDFs sintéticos recebidos pelo portal (binário bruto). Acesso restrito: única camada com o conteúdo original.",
    table_properties={"iasx.layer": "bronze", "iasx.contains_clinical_content": "true"},
    # Column mask: o PDF bruto só aparece para iasx_raw_document_readers (a identidade que roda a pipeline).
    schema=(
        "case_id STRING, document_id STRING, source_path STRING, size_bytes BIGINT, uploaded_at TIMESTAMP, "
        f"input_hash STRING, content BINARY MASK {POLICY}.iasx_mask_raw_document, ingested_at TIMESTAMP"
    ),
)
@dp.expect("is_pdf", "substring(hex(content), 1, 8) = '25504446'")  # magic bytes %PDF
@dp.expect("has_case_id", "case_id IS NOT NULL AND case_id <> ''")
def bronze_documents():
    # Convenção de caminho: landing/pdfs/<case_id>/<document_id>.pdf
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .option("pathGlobFilter", "*.pdf")
        .option("recursiveFileLookup", "true")
        .load(f"{LANDING}/pdfs")
        .select(
            F.regexp_extract("path", r"/pdfs/([^/]+)/[^/]+\.pdf$", 1).alias("case_id"),
            F.regexp_extract("path", r"/([^/]+)\.pdf$", 1).alias("document_id"),
            F.col("path").alias("source_path"),
            F.col("length").alias("size_bytes"),
            F.col("modificationTime").alias("uploaded_at"),
            F.sha2(F.col("content"), 256).alias("input_hash"),
            "content",
            F.current_timestamp().alias("ingested_at"),
        )
    )
