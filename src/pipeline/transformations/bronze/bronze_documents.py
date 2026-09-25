from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = spark.conf.get("iasx.landing_root")


@dp.table(
    name="bronze_documents",
    comment="PDFs sintéticos recebidos pelo portal (binário bruto). Acesso restrito: única camada com o conteúdo original.",
    table_properties={"iasx.layer": "bronze", "iasx.contains_clinical_content": "true"},
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
