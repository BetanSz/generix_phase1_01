"""
Lightweight helpers for contract ingestion with Azure services.

This module provides small, focused functions to:
- List and filter PDF blob names (`read_pdfs`, `select_affair`)
- Parse blob paths into structured fields (`parse_blob_path`)
- Produce safe identifiers from paths (`slugify_path`)
- Run Azure Document Intelligence on PDFs and upsert results to Cosmos DB
  (`upsert_cosmos_df`)
- Emit quick pricing stats from page counts (`print_price_estimations`)
- Write per-document Markdown outputs (`write_local_mk_files`)
- Orchestrate the whole DI flow for one affair (`process_affair_document_intelligence`)

Expectations & dependencies
---------------------------
- A Blob `container` exposing:
    - `list_blobs()` yielding objects with a `.name` attribute
    - `download_blob(name).readall()` to fetch file bytes
- A Document Intelligence client `client_di` exposing:
    - `begin_analyze_document(model, bytes, output_content_format="markdown")`
      returning a poller with `.result()`
- A Cosmos container `cosmos_digitaliezd` exposing:
    - `upsert_item(dict)` to persist extracted payloads

Side effects
------------
- Network calls to Azure Blob Storage, Document Intelligence, and Cosmos DB
- Filesystem writes of Markdown files to a user-provided output directory
- Console logging via simple `print()` calls

Function outputs (shapes)
-------------------------
- `upsert_cosmos_df(...) -> list[dict]` where each dict includes:
    id, title, content, file_path, language, page_count, analyse_doc_model,
    company_letter, company_name, company_affair, company_name_path, company_affair_path

Usage (minimal)
---------------
    pdfs = read_pdfs(container)
    subset = select_affair(pdfs, "sicame")
    docs = upsert_cosmos_df(cosmos_digitaliezd, container, client_di, subset)
    print_price_estimations(docs)
    write_local_mk_files(docs, Path("./doc_out"))

Notes
-----
- Case-insensitive filtering is performed via substring matching; adjust as needed.
- Error handling is intentionally simple (per-file `HttpResponseError` is printed and skipped).
- For production, consider structured logging, retries/timeouts, and stricter typing for SDK clients.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from azure.core.exceptions import HttpResponseError

def print_db_content(cosmos_digitaliezd: Any, max_item_count: int = 100) -> None:
    """Print a short overview of items currently in the DB."""
    items = list(cosmos_digitaliezd.read_all_items(max_item_count=max_item_count))
    print("total amount of items in DB =", len(items))
    #for i, doc in enumerate(items, start=1):
    #    print(i, doc["id"])

def process_affair_document_intelligence(
    cosmos_digitaliezd: Any,
    container: Any,
    client_di: Any,
    affair: Optional[str],
    local_path: Path,
) -> None:
    """
    Orchestrate the Document Intelligence phase for a single affair.

    Steps
    -----
    1) List PDFs from the given blob container.
    2) Filter the list by `affair` (if provided).
    3) Run Azure Document Intelligence on each selected PDF and upsert the
       resulting payloads into Cosmos.
    4) Print basic price/page statistics.
    5) Write Markdown outputs to `local_path`.

    Parameters
    ----------
    cosmos_digitaliezd : Any
        Cosmos DB container client (documents collection) with an `upsert_item` method.
    container : Any
        Azure Blob ContainerClient (must expose `list_blobs()` and `download_blob()`).
    client_di : Any
        Azure Document Intelligence client exposing `begin_analyze_document()`.
    affair : str or None
        Substring filter for PDF names. If `None`, process all PDFs.
    local_path : Path
        Directory where per-document Markdown files will be written.

    Returns
    -------
    None
    """
    pdfs_all = read_pdfs(container)
    print("len(pdfs_all):", len(pdfs_all))
    pdfs_company = select_affair(pdfs_all, affair)
    for pdf in pdfs_company:
        print(pdf)
    print("len(pdfs_company) = ", len(pdfs_company))
    docs = upsert_cosmos_df(cosmos_digitaliezd, container, client_di, pdfs_company)
    print_price_estimations(docs)
    write_local_mk_files(docs, local_path)

def parse_blob_path(path: str) -> Dict[str, Optional[str]]:
    """Split a blob path into {letter, company, affair, filename, company_key, affair_key}."""
    parts = [p for p in re.split(r"[\\/]+", path.strip()) if p]
    if len(parts) < 3:
        raise ValueError(f"Path doesn't look like 'letter/company/.../file': {path}")

    letter, company, filename = parts[0], parts[1], parts[-1]
    affair = "/".join(parts[2:-1]) if len(parts) > 3 else None

    return {
        "letter": letter,
        "company": company,
        "affair": affair,
        "filename": filename,
        "company_key": f"{letter}/{company}",
        "affair_key": f"{letter}/{company}/{affair or 'root'}",
    }


def slugify_path(p: str, max_len: int = 200) -> str:
    """
    Make a filesystem- and key-friendly slug from a path-like string.

    Parameters
    ----------
    p : str
        Input string (e.g., a blob path).
    max_len : int, default 200
        Maximum length of the resulting slug.

    Returns
    -------
    str
        A slugified version where path separators and special characters are
        replaced/sanitized, trimmed to `max_len`.
    """
    s = p.strip()
    s = s.replace("/", "_").replace("\\", "_").replace("?", "_").replace("#", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s)  # collapse weird chars
    return s[:max_len].strip("-_.")  # keep consistent edge chars off


def read_pdfs(container: Any) -> List[str]:
    """List all PDF blob names in the given container."""
    return [b.name for b in container.list_blobs() if b.name.lower().endswith(".pdf")]


def select_affair(pdfs_all: List[str], affair: Optional[str]) -> List[str]:
    """Filter PDFs by a case-insensitive substring; return all if no affair."""
    if not affair:
        return pdfs_all
    return [pdf for pdf in pdfs_all if affair in pdf.lower()]

def upsert_cosmos_df(
    cosmos_digitaliezd: Any,
    container: Any,
    client_di: Any,
    pdfs_company: List[str],
    analyse_doc_model: str = "prebuilt-layout",
) -> List[Dict[str, Any]]:
    """
    Analyze PDFs with Azure Document Intelligence and upsert results into Cosmos.

    Parameters
    ----------
    cosmos_digitaliezd : Any
        Cosmos DB container client exposing `upsert_item(dict)`.
    container : Any
        Azure Blob ContainerClient exposing `download_blob(name).readall()`.
    client_di : Any
        Azure Document Intelligence client (`begin_analyze_document` -> poller -> `result()`).
    pdfs_company : list[str]
        The list of blob names to process.
    analyse_doc_model : str, default 'prebuilt-layout'
        DI model identifier (e.g., 'prebuilt-layout', 'prebuilt-read').

    Returns
    -------
    list[dict[str, Any]]
        A list of payloads that were upserted into Cosmos and used for output.

    Side Effects
    ------------
    - Prints progress to stdout.
    - Upserts each payload to `cosmos_digitaliezd`.

    Exceptions
    ----------
    Catches `HttpResponseError` per-document and continues processing others.
    """
    docs: List[Dict[str, Any]] = []
    for i, pdf_name in enumerate(pdfs_company, start=1):
        print(f"processing....{i}/{len(pdfs_company)}", pdf_name)
        pdf_bytes = container.download_blob(pdf_name).readall()
        try:
            poller = client_di.begin_analyze_document(
                analyse_doc_model, pdf_bytes, output_content_format="markdown"
            )
            res = poller.result()
            folder_strct_dict = parse_blob_path(pdf_name)
            payload: Dict[str, Any] = {
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
            print(f"ERROR processing {pdf_name}: {e}")
    return docs

def print_price_estimations(docs: List[Dict[str, Any]], model_price_1000p=8.626) -> None:
    """Print mean pages and price estimate; no-op if docs is empty."""
    if not docs:
        print("No documents processed; skipping stats.")
        return
    model_price_page =  model_price_1000p/ 1000
    doc_pages = [doc["page_count"] for doc in docs]
    doc_mean = sum(doc_pages) / len(doc_pages)
    print("mean pages per contract = ", doc_mean)
    print(
        "price [single document, 2000X]",
        model_price_page * doc_mean,
        model_price_page * 2000 * doc_mean,
    )

def write_local_mk_files(docs: List[Dict[str, Any]], out_dir: Path) -> None:
    """
    Write per-document Markdown files to `out_dir`.

    Parameters
    ----------
    docs : list[dict[str, Any]]
        Payloads containing `id` and `content` keys.
    out_dir : Path
        Destination directory (will be created if missing).

    Returns
    -------
    None

    Side Effects
    ------------
    - Creates `out_dir` if it does not exist.
    - Writes `<id>.md` files with the `content` of each payload.
    - Logs each file path written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for doc_payload in docs:
        fname = doc_payload["id"] + ".md"
        file_path = out_dir / fname
        file_path.write_text(doc_payload.get("content", ""), encoding="utf-8")
        print("Wrote:", file_path)