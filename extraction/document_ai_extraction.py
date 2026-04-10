
import os
import argparse
from typing import Optional
from pathlib import Path
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.cloud import storage
import json
import re

# --- Configuration ---
PROJECT_ID = os.environ.get("GCP_PROJECT", "vitaai")
LOCATION = os.environ.get("GCP_LOCATION", "asia-south1")
PROCESSOR_ID = os.environ.get("DOCAI_PROCESSOR_ID", "5aa648e762ba8704")
GCS_BUCKET = os.environ.get("GCP_BUCKET", "edu-materials")

def process_document(
    file_path: str,
    project_id: str,
    location: str,
    processor_id: str,
    mime_type: str = "application/pdf",
) -> str:
    """Processes a document using the Document AI Online (Synchronous) API."""
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    )
    name = client.processor_path(project_id, location, processor_id)

    with open(file_path, "rb") as image:
        image_content = image.read()

    raw_document = documentai.RawDocument(content=image_content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    result = client.process_document(request=request)

    return result.document.text

def batch_process_document(
    gcs_input_uri: str,
    gcs_output_uri: str,
    project_id: str,
    location: str,
    processor_id: str,
):
    """Processes a large document using the Document AI Batch (Asynchronous) API."""
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    )
    name = client.processor_path(project_id, location, processor_id)

    input_config = documentai.BatchDocumentsInputConfig(
        gcs_documents=documentai.GcsDocuments(
            documents=[documentai.GcsDocument(gcs_uri=gcs_input_uri, mime_type="application/pdf")]
        )
    )

    output_config = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=gcs_output_uri
        )
    )

    request = documentai.BatchProcessRequest(
        name=name,
        input_configs=[input_config],
        output_config=output_config,
    )

    print(f"[DocAI] Starting batch process. This may take a few minutes...")
    operation = client.batch_process_documents(request=request)
    operation.result(timeout=600)
    print(f"[SUCCESS] Batch process complete.")

def upload_to_gcs(local_path: str, bucket_name: str, destination_blob_name: str):
    """Uploads a file to the bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    print(f"[GCS] Uploading {local_path} to gs://{bucket_name}/{destination_blob_name}...")
    blob.upload_from_filename(local_path)

def download_and_parse_results(bucket_name: str, output_prefix: str) -> str:
    """Downloads the JSON results from GCS and concatenates the text."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    # Batch processing creates subfolders. We need to find the JSON files.
    blobs = storage_client.list_blobs(bucket_name, prefix=output_prefix)
    
    full_text = []
    for blob in blobs:
        if blob.name.endswith(".json"):
            print(f"[GCS] Downloading and parsing result: {blob.name}")
            content = blob.download_as_string()
            doc_data = json.loads(content)
            full_text.append(doc_data.get("text", ""))
            
    return "".join(full_text)

def main():
    parser = argparse.ArgumentParser(description="Extract text from PDF using Google Cloud Document AI.")
    parser.add_argument("pdf_path", nargs="?", help="Path to the local PDF file.")
    parser.add_argument("--batch", action="store_true", help="Use Batch processing (required for large PDFs)")
    parser.add_argument("--bucket", help="GCS Bucket name for batch processing")
    parser.add_argument("--gcs_input", help="GCS URI for input PDF (direct mode)")
    parser.add_argument("--project", default=PROJECT_ID, help="GCP Project ID.")
    parser.add_argument("--location", default=LOCATION, help="GCP Location (us/eu).")
    parser.add_argument("--processor", default=PROCESSOR_ID, help="Document AI Processor ID.")
    parser.add_argument("--out", help="Output text file path.")

    args = parser.parse_args()

    if not args.processor:
        print("[ERROR] Document AI Processor ID is required.")
        return

    try:
        if args.batch:
            bucket = args.bucket or GCS_BUCKET
            if not bucket:
                print("[ERROR] A GCS bucket is required for batch processing. Use --bucket or set GCP_BUCKET env var.")
                return
            
            # Automated Flow
            pdf_name = Path(args.pdf_path).name
            input_uri = f"gs://{bucket}/input/{pdf_name}"
            output_uri = f"gs://{bucket}/output/{pdf_name}/" # Must end with /
            
            # 1. Upload
            upload_to_gcs(args.pdf_path, bucket, f"input/{pdf_name}")
            
            # 2. Process
            batch_process_document(input_uri, output_uri, args.project, args.location, args.processor)
            
            # 3. Download & Parse
            extracted_text = download_and_parse_results(bucket, f"output/{pdf_name}/")
            
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
                print(f"[SUCCESS] Final extracted text saved to {args.out}")
            else:
                print("\n--- Extracted Text Preview (Batch) ---")
                print(extracted_text[:1000] + "...")
                
        else:
            if not args.pdf_path:
                print("[ERROR] Online processing requires a local pdf_path.")
                return
            print(f"[DocAI] Processing {args.pdf_path} (Online Mode)...")
            extracted_text = process_document(args.pdf_path, args.project, args.location, args.processor)
            
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
                print(f"[SUCCESS] Extracted text saved to {args.out}")
            else:
                print("\n--- Extracted Text Preview ---")
                print(extracted_text[:1000] + "...")
            
    except Exception as e:
        print(f"[ERROR] Document AI failed: {e}")
        if "Quota exceeded" in str(e):
            print("\n💡 TIP: For large textbooks (>15 pages), you MUST use Batch Processing.")
            print(f"I've automated this! Run: python document_ai_extraction.py {args.pdf_path} --batch --bucket YOUR_BUCKET")

if __name__ == "__main__":
    main()
