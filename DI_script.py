"""
pip install -U azure-ai-documentintelligence
pip install openai
pip install azure-search-documents 
pip install ipython
pip install azure-storage-blob
pip install azure-cosmos
pip install fastapi uvicorn
pip install pandas
pip install openpyxl 
pip install tabulate
 pip install unidecode


"""
import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from clients import client_di, container, cosms_db, cosmos_digitaliezd
from pathlib import Path
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError
import sys

def parse_blob_path(path: str):
    """
    Parse blob paths like:
      'M/caloteries/b/Calottiers 201706 058931.pdf'
      'M/cafe_mao/010825 CAFE MEO.pdf'
      'M/MAS SAINT PAUL/201707 059985/Mas Saint Paul 201707-059985.pdf'

    Returns dict with:
      letter   -> first segment (e.g., 'M')
      company  -> second segment (e.g., 'caloteries' or 'MAS SAINT PAUL')
      affair   -> everything between company and filename (optional, may be None)
      filename -> last segment
      company_key -> 'M/company'
      affair_key  -> 'M/company/<affair or "root">'
    """
    # normalize separators and drop empty parts
    parts = [p for p in re.split(r"[\\/]+", path.strip()) if p]
    if len(parts) < 3:
        raise ValueError(f"Path doesn't look like 'letter/company/…/file': {path}")

    letter   = parts[0]
    company  = parts[1]
    filename = parts[-1]
    # optional: there may be zero or more subfolders between company and file
    affair   = "/".join(parts[2:-1]) if len(parts) > 3 else None

    return {
        "letter": letter,
        "company": company,
        "affair": affair,                  # None if not present
        "filename": filename,
        "company_key": f"{letter}/{company}",
        "affair_key": f"{letter}/{company}/{affair or 'root'}",
    }
def slugify_path(p: str, max_len=200) -> str:
    s = p.strip()
    s = s.replace("/", "_").replace("\\", "_").replace("?", "_").replace("#", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)   # collapse weird chars
    return s[:max_len].strip("-_.")

#from azure.ai.documentintelligence.models import ContentFormat #not working

docs = []
MAX_EMBED_CHARS = 6000  # simple guard to avoid very long inputs
MAX_EMBED_CHARS = 6000  # simple guard to avoid very long inputs

# list PDFs in the container (optionally: name_starts_with="subfolder/")
pdfs_all = [b.name for b in container.list_blobs() if b.name.lower().endswith(".pdf")]
print("len(pdfs_all):", len(pdfs_all))


#pdfs=['M/caloteries/b/Calottiers 201706 058931.pdf']
#pdfs = [pdf for pdf in pdfs if "New contracts" in pdf]
#pdfs = [pdf for pdf in pdfs if "CULTURA" in pdf]
#pdfs_company = [pdf for pdf in pdfs_all if "RENAULT" in pdf or "RCI F" in pdf]
#pdfs_company = [pdf for pdf in pdfs_all if "edenred" in pdf]
#pdfs_company = [pdf for pdf in pdfs_all if "suez" in pdf]
pdfs_company = [pdf for pdf in pdfs_all if "carter" in pdf]
print(pdfs_company)
print("len(pdfs_company) = ", len(pdfs_company))
#pdfs = [pdf for pdf in pdfs if "Old contracts" in pdf]
embed()
sys.exit()
analyse_doc_model = "prebuilt-read"
analyse_doc_model = "prebuilt-layout"

for i, pdf_name in enumerate(pdfs_company, start=1):
    print(f"processing....{i}/{len(pdfs_company)}", pdf_name)
    #breakpoint()
    pdf_bytes = container.download_blob(pdf_name).readall()
    #poller = client_di.begin_analyze_document(analyse_doc_model, pdf_bytes)
    #embed()
    try:
        poller = client_di.begin_analyze_document(
            analyse_doc_model,
            pdf_bytes,
            output_content_format="markdown"
        )
        res = poller.result()
        text = res.content
        folder_strct_dict = parse_blob_path(pdf_name)
        print("contract structure looks like this...")
        print(folder_strct_dict)
        payload = {
            "id": slugify_path(pdf_name),
            "title": os.path.basename(pdf_name),
            "content": res.content or "",
            "file_path": os.path.abspath(pdf_name),
            "language": (res.languages[0].locale if res.languages else "unknown"),
            "page_count": len(res.pages),
            "analyse_doc_model": analyse_doc_model,
            "company_letter": folder_strct_dict["letter"],
            "company_name": folder_strct_dict["company"],
            "company_affair": folder_strct_dict["affair"],
            "company_name_path": folder_strct_dict["company_key"],
            "company_affair_path": folder_strct_dict["affair_key"],
        }
        docs.append(payload)
        cosmos_digitaliezd.upsert_item(payload)
    except HttpResponseError as e:
        print("ERROR!")
        print(e)

#local_path = "C:\\Users\\EstebanSzames\\OneDrive - CELLENZA\\Bureau\\Generix\\generix_phase1_01\\doc_digitalized_sample\\"
#for doc_payload in docs:
#    with open(local_path, "w", encoding="utf-8", newline="\n") as f:
#        f.write(doc_payload.get("content",""))
#breakpoint()
#embed()
layout_price_page = 8.626/1000
doc_pages = [doc["page_count"] for doc in docs]
doc_mean = sum(doc_pages)/len(doc_pages)
print("mean pages per contract = ", doc_mean)
print("price [single document, 10000X]", layout_price_page*doc_mean, layout_price_page*10000*doc_mean)

out_dir = Path(r"C:\Users\EstebanSzames\OneDrive - CELLENZA\Bureau\Generix\generix_phase1_01\doc_digitalized_sample")
out_dir.mkdir(parents=True, exist_ok=True)
for doc_payload in docs:
    fname = doc_payload["id"] + ".md"
    file_path = out_dir / fname
    file_path.write_text(doc_payload.get("content", ""), encoding="utf-8")
    print("Wrote:", file_path)