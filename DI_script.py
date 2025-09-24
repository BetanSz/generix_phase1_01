"""
pip install "azure-ai-formrecognizer>=3.3.0,<4"
pip install openai
pip install azure-search-documents 
pip install ipython
pip install azure-storage-blob
pip install azure-cosmos
pip install fastapi uvicorn
"""
import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from clients import client_di, container, cosms_db, cosmos_digitaliezd
from pathlib import Path

#from azure.ai.documentintelligence.models import ContentFormat #not working

docs = []
MAX_EMBED_CHARS = 6000  # simple guard to avoid very long inputs
MAX_EMBED_CHARS = 6000  # simple guard to avoid very long inputs

# list PDFs in the container (optionally: name_starts_with="subfolder/")
pdfs = [b.name for b in container.list_blobs() if b.name.lower().endswith(".pdf")]
print("found in blob:", pdfs)

def slugify_path(p: str, max_len=200) -> str:
    s = p.strip()
    s = s.replace("/", "_").replace("\\", "_").replace("?", "_").replace("#", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)   # collapse weird chars
    return s[:max_len].strip("-_.")

analyse_doc_model = "prebuilt-read"
for pdf_name in pdfs:
    #breakpoint()
    pdf_bytes = container.download_blob(pdf_name).readall()
    #poller = client_di.begin_analyze_document(analyse_doc_model, pdf_bytes)
    poller = client_di.begin_analyze_document(
        "prebuilt-layout",
        pdf_bytes,
        #output_content_format="markdown", #TODO: try layout with mkdown. Not working
    )
    res = poller.result()
    text = res.content
    payload = {
        "id": slugify_path(pdf_name),
        "title": os.path.basename(pdf_name),
        "content": res.content or "",
        "file_path": os.path.abspath(pdf_name),
        "language": (res.languages[0].locale if res.languages else "unknown"),
        "page_count": len(res.pages),
    }
    docs.append(payload)
    cosmos_digitaliezd.upsert_item(payload)

#local_path = "C:\\Users\\EstebanSzames\\OneDrive - CELLENZA\\Bureau\\Generix\\generix_phase1_01\\doc_digitalized_sample\\"
#for doc_payload in docs:
#    with open(local_path, "w", encoding="utf-8", newline="\n") as f:
#        f.write(doc_payload.get("content",""))
#breakpoint()
#embed()
out_dir = Path(r"C:\Users\EstebanSzames\OneDrive - CELLENZA\Bureau\Generix\generix_phase1_01\doc_digitalized_sample")
out_dir.mkdir(parents=True, exist_ok=True)
for doc_payload in docs:
    doc_id = str(doc_payload.get("id", "untitled"))
    fname = doc_id + ".txt"
    file_path = out_dir / fname
    file_path.write_text(doc_payload.get("content", ""), encoding="utf-8")
    print("Wrote:", file_path)