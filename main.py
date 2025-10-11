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
from di_module import process_affair_document_intelligence, print_db_content
from IPython import embed
from pathlib import Path
from clients import client_di, cosmos_digitaliezd, client_oai, cosmos_table, container
import argparse

from gpt_module import (
    get_docs,
    get_cpcgav,
    verify_cpcgav_separation,
    run_avenants_pipeline,
    run_cgcp_pipeline,
    get_df_cpcgav_all,
    loyer2null,
    upsert_to_cosmos,
    save_df_local,
    cp_identifiers,
    cg_identifiers,
    av_identifiers
)
from gpt_module_financial_agent import financial_prompt, financial_tools, col_order, cgcp_question, avenant_question

DEFAULT_AFFAIRS = ["mason", "anagra"]
DEFAULT_DI = False
DEFAULT_TAG = "main"
DEFAULT_OUTDIR = Path(
    r"C:\Users\EstebanSzames\OneDrive - CELLENZA\Bureau\Generix\generix_phase1_01\doc_digitalized_sample"
)

def parse_cli_args() -> argparse.Namespace:
    """
    Parse CLI arguments for the pipeline.

    --affairs can be repeated or comma-separated, e.g.:
      --affairs mason anagra
      --affairs mason,anagra

    --di enables the Document Intelligence phase (default off).
    """
    def comma_or_list(arg: str) -> list[str]:
        # allow "a,b,c" or "a" (single item)
        return [x for x in (s.strip() for s in arg.split(",")) if x]

    parser = argparse.ArgumentParser(description="Contract processing pipeline")
    parser.add_argument(
        "--affairs",
        "-a",
        nargs="+",
        type=str,
        help="Affairs to process (list or comma-separated). Default: %(default)s",
        default=DEFAULT_AFFAIRS,
    )
    parser.add_argument(
        "--di",
        action="store_true",
        help="Enable Document Intelligence ingestion (default: off).",
        default=DEFAULT_DI,
    )
    parser.add_argument(
        "--tag",
        "-t",
        type=str,
        help="Local save tag used in output filenames.",
        default=DEFAULT_TAG,
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        type=Path,
        help="Directory for local Markdown/Excel outputs.",
        default=DEFAULT_OUTDIR,
    )

    args = parser.parse_args()

    # Normalize affairs: expand any comma-separated tokens inside nargs list
    normalized: list[str] = []
    for token in args.affairs:
        normalized.extend(comma_or_list(token))
    args.affairs = normalized
    return args

if __name__ == "__main__":
    # User input
    args = parse_cli_args()
    # User input (with defaults if not passed)
    # use python main.py -a "mason,anagra"
    affair_to_treat = args.affairs                      # e.g. ["mason","anagra"]
    performe_document_intelligence_read = args.di       # True if --di, else False
    local_save_tag = args.tag                           # e.g. "main"
    local_path = args.out_dir                           # Path(...)

    #affair_to_treat = ["S.N.F", "NORAUTO" , "SAVENCIA", "BOIRON", "AIRBUS-HELICOPTERS", "CULTURA", "suez", "carter",
    #                    "edenred", "renault", "mason" , "fr_mes", "id_log" , "invicta", "coca", "maha",
    #                    "kueh", "naviland", "psa", "ricard", "robot", "serhr", "shenker", "sicame", "watch",
    #                    "combrone", "anagra"]

    # Document intelligence
    for affair in affair_to_treat:
        if performe_document_intelligence_read:
            process_affair_document_intelligence(
                cosmos_digitaliezd, container, client_di, affair, local_path
            )
    # GPT agent
    print_db_content(cosmos_digitaliezd)
    for i, affair in enumerate(affair_to_treat, start=1):
        print(f"\nTreating affair {i}/{len(affair_to_treat)} = ", affair)
        docs = get_docs(affair, cosmos_digitaliezd)
        content_cadre, content_sous, content_avenant = get_cpcgav(
            docs, cp_identifiers, cg_identifiers, av_identifiers
        )
        verify_cpcgav_separation(docs, content_cadre, content_sous, content_avenant)
        #continue
        cpcg_df = run_cgcp_pipeline(
            content_cadre=content_cadre,
            content_sous=content_sous,
            client_oai=client_oai,
            cgcp_question=cgcp_question,
            financial_prompt=financial_prompt,
            financial_tools=financial_tools,
            col_order=col_order,
        )
        df_av_all = run_avenants_pipeline(
            content_avenant=content_avenant,
            client_oai=client_oai,
            avenant_question=avenant_question,
            financial_prompt=financial_prompt,
            financial_tools=financial_tools,
            col_order=col_order
        )
        if df_av_all is not None:
            affair_df = get_df_cpcgav_all(cpcg_df, df_av_all)
        else:
            affair_df = cpcg_df.copy()
        affair_df = loyer2null(cpcg_df)
        affair_df = affair_df.fillna("null")
        save_df_local(affair, local_save_tag, cpcg_df, df_av_all, affair_df)
        upsert_to_cosmos(affair_df, affair, cosmos_table)
        print("END")

