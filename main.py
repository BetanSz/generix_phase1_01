"""
End-to-end contract processing pipeline.

This module orchestrates two phases:

1) Document Intelligence (optional)
   - Scans PDF contracts stored in an Azure Blob container.
   - Uses Azure Document Intelligence to extract Markdown content.
   - Writes local Markdown files per document.
   - Upserts extracted documents into a Cosmos DB (documents collection).

2) GPT-based extraction (financial agent)
   - Reads previously extracted/ingested documents from Cosmos.
   - Splits content into Contract Cadre (CG), Souscription (CP), and Avenants.
   - Asks a financial QA agent (OpenAI client) to extract products and financial terms
     according to a predefined prompt and tools.
   - Produces both Markdown and Excel summaries, and upserts the consolidated results
     into a Cosmos Table.

Environment & dependencies
--------------------------
- External clients are provided by the local `clients` package:
  `client_di` (Azure DI), `container` (Azure Blob), `cosmos_digitaliezd` (Cosmos documents),
  `cosmos_table` (Cosmos Table), and `client_oai` (OpenAI).
- Helper logic is imported from `di_module`, `gpt_module`, and
  `gpt_module_financial_agent` (e.g., `process_affair_document_intelligence`,
  `get_docs`, `get_cpcgav`, `process_cgcp`, `build_message_*`, `get_response_df`,
  `rectify_df`, `concat_avenant_df`, `get_df_cpcgav_all`, `loyer2null`, `upsert_to_cosmos`).

Configuration knobs (edit in __main__)
--------------------------------------
- `affair_to_treat`: list[str]
    Substring(s) used to filter documents by "affair" (case-insensitive).
- `performe_document_intelligence_read`: bool
    If True, run Azure Document Intelligence over matching PDFs and ingest results.
    If False, skip DI and use whatever is already in Cosmos.
- `local_path`: pathlib.Path
    Folder where Markdown renditions of each processed document are written.
- `cgcp_question`, `avenant_question`:
    Prompts for the GPT financial agent (Cadre/CP and Avenants, respectively).
- `cp_identifiers`, `cg_identifiers`, `av_identifiers`:
    Section tags/identifiers used to split and classify document content.

Inputs
------
- Azure Blob Storage: source PDFs.
- Cosmos DB (documents collection): destination for DI outputs and later retrieval.
- OpenAI API: called by the financial agent to extract structured data.

Outputs
-------
- Local files:
    - `product_cpcg_<affair><tag>.md`
    - `product_cpcg_<affair><tag>.xlsx`
    - `product_av_<affair><tag>.md` (if any Avenants)
    - `product_cpcgav_<affair><tag>.md`
    - `product_cpcgav_<affair><tag>.xlsx`
    Plus per-document Markdown dumps produced by the DI phase under `local_path/`.
- Cosmos Table:
    - Upserted product rows with extracted financial conditions.
- Console logs:
    - Progress and basic counts for traceability.

Side effects
------------
- Network calls to Azure Document Intelligence and Blob Storage.
- Reads/writes to Cosmos DB and Cosmos Table.
- File system writes under `local_path`.

Usage
-----
Run directly as a script and adjust the variables in the `__main__` block:

    python main.py

Typical flow:
1. (Optional) Set `performe_document_intelligence_read = True` to populate/update Cosmos
   from the latest PDFs in Blob.
2. Always run the GPT agent phase to extract product-level financial terms and export
   Markdown/Excel artifacts, then upsert the results into Cosmos Table.

Notes
-----
- This module currently uses in-code configuration rather than a CLI or config file.
  A future revision will introduce a proper CLI (`argparse` or `click`), typed functions,
  and docstrings throughout.
- Error handling is minimal; upstream helpers should raise or log appropriately.
- Ensure credentials/config for Azure and OpenAI are available in your environment.

"""

from pathlib import Path
from di_module import *
from IPython import embed
from pathlib import Path
from clients import client_di, cosmos_digitaliezd, client_oai, cosmos_table, container
from gpt_module_financial_agent import *
from gpt_module import *

if __name__ == "__main__":
    # User input
    affair_to_treat = ["mason"]
    performe_document_intelligence_read = False
    performe_document_intelligence_read = True
    local_path = Path(
        r"C:\Users\EstebanSzames\OneDrive - CELLENZA\Bureau\Generix\generix_phase1_01\doc_digitalized_sample"
    )

    # Document intelligence
    for affair in affair_to_treat:
        if performe_document_intelligence_read:
            process_affair_document_intelligence(
                cosmos_digitaliezd, container, client_di, affair, local_path
            )

    # GPT agent
    local_save_tag = "main"
    cgcp_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
    avenant_question = "Extract all the products found in each avenant sections with their financial conditions using the rules and return products via the tool."
    cp_identifiers = [
        "SOUSCRIPTION",
        "CP",
        "LICENCE",
        "CONTRAT-SAAS",
        "CONTRAT-PRESTATIONS",
    ]  # suez is a special case due to bad id
    cg_identifiers = ["CADRE", "CG"]
    av_identifiers = ["AVENANT-"]
    items = list(cosmos_digitaliezd.read_all_items(max_item_count=100))
    print("total amount of items in DB =", len([item for item in items]))
    for i, doc in enumerate(items, start=1):
        print(i, doc["id"])
    for affair in affair_to_treat:
        docs = get_docs(affair, cosmos_digitaliezd)
        content_cadre, content_sous, content_avenant = get_cpcgav(
            docs, cp_identifiers, cg_identifiers, av_identifiers
        )
        content_cadre_str, content_sous_str = process_cgcp(
            content_cadre,
            content_sous,
        )
        messages_cpcg = build_message_cgcp(
            content_cadre_str, content_sous_str, cgcp_question, financial_prompt
        )
        affair_df = get_response_df(client_oai, messages_cpcg, financial_tools)
        affair_df = rectify_df(affair_df, col_order)
        tag = affair + local_save_tag
        affair_df.to_markdown(f"product_cpcg_{tag}.md", index=False)
        affair_df.to_excel(f"product_cpcg_{tag}.xlsx")
        df_av_list = []
        for i, avenant_str in enumerate(content_avenant, start=1):
            print(
                f"*****************  processing {i}/{len(content_avenant)} *****************"
            )
            messages_av = build_message_avenant(
                avenant_str, avenant_question, financial_prompt
            )
            print("content [AV]=", len(avenant_str))
            df_av = get_response_df(client_oai, messages_av, financial_tools)
            rectify_df(df_av)
            df_av_list.append(df_av)
        if df_av_list:
            df_av_all = concat_avenant_df(df_av_list)
            df_av_all.to_markdown(f"product_av_{tag}.md", index=False)
            affair_df = get_df_cpcgav_all(affair_df, df_av_all)
            affair_df = loyer2null(affair_df, safe_flag=True)
            affair_df = affair_df.fillna("null")
            affair_df.to_markdown(f"product_cpcgav_{tag}.md", index=False)
            print(f"product_cpcgav_{tag}.xlsx")
            affair_df.to_excel(f"product_cpcgav_{tag}.xlsx")
        upsert_to_cosmos(affair_df, affair, cosmos_table)
        print("END")
