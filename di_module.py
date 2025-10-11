""" """

import os, re
from IPython import embed
from azure.core.exceptions import HttpResponseError


def process_affair_document_intelligence(
    cosmos_digitaliezd, container, client_di, affair, local_path
):
    pdfs_all = read_pdfs(container)
    print("len(pdfs_all):", len(pdfs_all))
    pdfs_company = select_affair(pdfs_all, affair)
    for pdf in pdfs_company:
        print(pdf)
    print("len(pdfs_company) = ", len(pdfs_company))
    docs = upsert_cosmos_df(cosmos_digitaliezd, container, client_di, pdfs_company)
    print_price_estimations(docs)
    write_local_mk_files(docs, local_path)


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

    letter = parts[0]
    company = parts[1]
    filename = parts[-1]
    # optional: there may be zero or more subfolders between company and file
    affair = "/".join(parts[2:-1]) if len(parts) > 3 else None

    return {
        "letter": letter,
        "company": company,
        "affair": affair,  # None if not present
        "filename": filename,
        "company_key": f"{letter}/{company}",
        "affair_key": f"{letter}/{company}/{affair or 'root'}",
    }


def slugify_path(p: str, max_len=200) -> str:
    s = p.strip()
    s = s.replace("/", "_").replace("\\", "_").replace("?", "_").replace("#", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)  # collapse weird chars
    return s[:max_len].strip("-_.")


def read_pdfs(container):
    # list PDFs in the container (optionally: name_starts_with="subfolder/")
    pdfs_all = [
        b.name for b in container.list_blobs() if b.name.lower().endswith(".pdf")
    ]
    return pdfs_all


def select_affair(pdfs_all, affair):
    if affair:
        return [pdf for pdf in pdfs_all if affair in pdf.lower()]
    else:
        return pdfs_all


def upsert_cosmos_df(
    cosmos_digitaliezd,
    container,
    client_di,
    pdfs_company,
    analyse_doc_model="prebuilt-layout",
):
    docs = []
    for i, pdf_name in enumerate(pdfs_company, start=1):
        print(f"processing....{i}/{len(pdfs_company)}", pdf_name)
        pdf_bytes = container.download_blob(pdf_name).readall()
        try:
            poller = client_di.begin_analyze_document(
                analyse_doc_model, pdf_bytes, output_content_format="markdown"
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
    return docs


def print_price_estimations(docs):
    layout_price_page = 8.626 / 1000
    doc_pages = [doc["page_count"] for doc in docs]
    doc_mean = sum(doc_pages) / len(doc_pages)
    print("mean pages per contract = ", doc_mean)
    print(
        "price [single document, 2000X]",
        layout_price_page * doc_mean,
        layout_price_page * 2000 * doc_mean,
    )


def write_local_mk_files(docs, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for doc_payload in docs:
        fname = doc_payload["id"] + ".md"
        file_path = out_dir / fname
        file_path.write_text(doc_payload.get("content", ""), encoding="utf-8")
        print("Wrote:", file_path)
