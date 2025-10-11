"""
Utilities for extracting product/financial data from contract text using GPT and Cosmos.

This module contains lightweight helpers to:
- Query digitalized contract documents from Cosmos (`get_docs`)
- Partition documents into CG/CP/Avenant buckets (`get_cpcgav`)
- Join CG/CP text blocks for prompting (`process_cgcp`)
- Build chat messages for CG+CP and Avenant prompts (`build_message_cgcp`, `build_message_avenant`)
- Call the chat model with tool calls and normalize outputs to a DataFrame (`get_response_df`)
- Log token usage and rough € cost for a completion (`print_resp_properties`)
- Merge CG/CP and Avenant product tables with date normalization (`get_df_cpcgav_all`)
- Clean pricing fields for one-shot/non-volume items (`loyer2null`)
- Validate/rectify a DataFrame to a target column order (`validate_columns`, `rectify_df`)
- Upsert the final results back into Cosmos as a single batch row (`upsert_to_cosmos`)
- Concatenate multiple Avenant result tables (`concat_avenant_df`)

Expectations & external dependencies
------------------------------------
- Cosmos containers:
    - A *documents* container holding digitalized PDFs with fields like `id`, `content`, `page_count`.
    - A *table-like* container where aggregated product rows are upserted as one batch item `{id=<affair>, rows=[...]}`.
- Azure OpenAI client (`client_oai`) that supports `chat.completions.create(...)` with tool calls.
- DataFrames use pandas and may contain the following columns, among others:
    - `one_shot_service`, `is_volume_product`, `price_unitaire`, `loyer`, `loyer_*`, `billing_frequency`, `avenant_number`,
      and signature date fields (`signature_date_cp`, `signature_date_av`).

Conventions
-----------
- Case-insensitive matching on document IDs is done by substring checks.
- Tool responses are expected to include a top-level JSON object with `products: [...]`.
- Literal string `"null"` in certain fields is treated as missing and normalized to NA before date parsing.

Side effects
------------
- Network I/O to Cosmos (queries, reads, upserts).
- Network I/O to Azure OpenAI (chat completions).
- Console logging via simple `print()` statements (counts, shapes, token usage, cost).

Typical usage (sketch)
----------------------
    docs = get_docs("sicame", cosmos_digitaliezd)
    cg, cp, av = get_cpcgav(docs, cp_identifiers, cg_identifiers, av_identifiers)
    cg_str, cp_str = process_cgcp(cg, cp)
    msgs = build_message_cgcp(cg_str, cp_str, user_question, financial_prompt)
    df_cpcg = get_response_df(client_oai, msgs, financial_tools)

    # Avenants
    df_av_list = []
    for av_str in av:
        msgs_av = build_message_avenant(av_str, avenant_question, financial_prompt)
        df_av_list.append(get_response_df(client_oai, msgs_av, financial_tools))
    df_av_all = concat_avenant_df(df_av_list)

    # Combine, clean, validate, and persist
    df_all = get_df_cpcgav_all(df_cpcg, df_av_all)
    df_all = loyer2null(df_all, safe_flag=True)
    df_all = rectify_df(df_all, col_order)
    upsert_to_cosmos(df_all, affair="sicame", cosmos_table=cosmos_table)

Notes
-----
- This is not production-hardened code: error handling is minimal by design.
- For stricter environments, consider retries, structured logging, and schema validation.
"""

import json
from typing import Any, Dict, List, Tuple, Optional

import pandas as pd
import numpy as np

cp_identifiers = [
    "SOUSCRIPTION",
    "CP",
    "CONTRAT-SAAS",
    "CONTRAT-PRESTATIONS",
    "BDC-LICENCE",
    "CONTRAT-P"
]
cg_identifiers = ["CADRE", "CG"]
av_identifiers = ["AVENANT-", "APPLICATION"]

def get_docs(
    company_name: str,
    cosmos_digitaliezd: Any,
    exclude_flag: bool = True,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch company docs from Cosmos by id substring; optionally exclude '-ASP-'."""
    exclusin_flags = ["-ASP-", "PLAN-PROJET-GENERIX", "ANNEXE-DONNEES-PERSONNELLES"]
    query = (
        "SELECT VALUE c.id FROM c "
        "WHERE CONTAINS(c.id, @kw, true) AND ENDSWITH(c.id, '.pdf')"
    )
    params = [{"name": "@kw", "value": company_name}]
    doc_ids = list(
        cosmos_digitaliezd.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )
    if verbose:
        print("numbers of docs original =", len(doc_ids))
    if exclude_flag:
        doc_final = [doc_id for doc_id in doc_ids if all([flag.lower() not in doc_id.lower() for flag in exclusin_flags ])]
        if len(doc_final)!=len(doc_ids):
            print("numbers of docs after exclusion =", len(doc_final))
            print("excluded contracts = ", set(doc_ids) - set(doc_final))

    return [cosmos_digitaliezd.read_item(item=i, partition_key=i) for i in doc_final]


def get_cpcgav(
    docs: List[Dict[str, Any]],
    cp_identifiers: List[str],
    cg_identifiers: List[str],
    av_identifiers: List[str],
    verbose: bool = True
) -> Tuple[List[str], List[str], List[str]]:
    """Split docs into CG, CP, AV (matching on id substrings, case-insensitive)."""
    cg_flags = [s.casefold() for s in cg_identifiers]
    cp_flags = [s.casefold() for s in cp_identifiers]
    av_flags = [s.casefold() for s in av_identifiers]

    content_cadre = [
        doc.get("content", "")
        for doc in docs
        if any(flag in doc["id"].casefold() for flag in cg_flags)
        and "-avenant-" not in doc["id"].casefold()
    ]
    content_sous = [
        doc.get("content", "")
        for doc in docs
        if any(flag in doc["id"].casefold() for flag in cp_flags)
    ]
    content_avenant = [
        "=== DOC: AVENANT — type=avenant ===\n" + doc.get("content", "")
        for doc in docs
        if any(flag in doc["id"].casefold() for flag in av_flags)
    ]

    if verbose:
        print(
            "Amount documents [CG,CP,AV]=",
            len(content_cadre), len(content_sous), len(content_avenant),
        )
    return content_cadre, content_sous, content_avenant


def process_cgcp(
    content_cadre: List[str],
    content_sous: List[str],
    verbose: bool = True,
) -> Tuple[str, str]:
    """Join CG/CP content lists into two newline-separated strings."""
    content_cadre_str = "\n".join(content_cadre)
    content_sous_str = "\n".join(content_sous)
    if verbose:
        print("len [str] content [cg,cp]=", len(content_cadre_str), len(content_sous_str))
    return content_cadre_str, content_sous_str


def build_message_cgcp(
    content_cadre_str: str,
    content_sous_str: str,
    user_question: str,
    financial_prompt: str,
) -> List[Dict[str, str]]:
    """Build chat messages for CG+CP extraction using a system prompt and user task."""
    content_cpcg = (
        "=== DOC: CADRE — type=cadre ===\n"
        + content_cadre_str.strip()
        + "\n\n"
        + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
        + content_sous_str.strip()
    )
    messages_cpcg = [
        {"role": "system", "content": financial_prompt},
        {
            "role": "user",
            "content": f"DOCUMENT CONTENT:\n\n{content_cpcg}\n\nTASK:\n{user_question}",
        },
    ]
    return messages_cpcg

def build_message_avenant(
    avenant_str: str, avenant_question: str, financial_prompt: str
) -> List[Dict[str, str]]:
    """Build chat messages for a single Avenant section using the financial prompt."""
    messages_av = [
        {"role": "system", "content": financial_prompt},
        {
            "role": "user",
            "content": f"DOCUMENT CONTENT:\n\n{avenant_str}\n\nTASK:\n{avenant_question}",
        },
    ]
    return messages_av

def get_response_df(
    client_oai: Any,
    message: List[Dict[str, str]],
    tools: Any,
    model="gpt-4.1",
    max_tokens=32000
) -> pd.DataFrame:
    """
    Call the chat model with tools and return a normalized DataFrame of products.

    Parameters
    ----------
    client_oai : Any
        Azure OpenAI client exposing `chat.completions.create(...)`.
    message : list[dict[str, str]]
        List of role/content message dicts.
    tools : Any
        Tool definitions passed to the chat completion call.
    model : str, default "gpt-4.1"
        Deployment/model name for the completion call.
    max_tokens : int, default 32000
        Max tokens for the completion.

    Returns
    -------
    pandas.DataFrame
        DataFrame created from the JSON argument payload under `products`.

    Notes
    -----
    - Assumes the first choice contains a `tool_calls` entry with a JSON payload
      matching `{"products": [...]}`.
    - Prints basic token usage and computed costs via `print_resp_properties`.
    """
    resp = client_oai.chat.completions.create(
        model=model,
        messages=message,
        tools=tools,
        tool_choice="auto", 
        temperature=0.05,  
        max_tokens=max_tokens,
    )
    print_resp_properties(resp)
    tool_call = resp.choices[0].message.tool_calls[0]
    args_str = tool_call.function.arguments
    data = json.loads(args_str)
    df = pd.json_normalize(data["products"])
    return df


def print_resp_properties(resp: Any, INPUT_EUR_PER_1M = 1.73, OUTPUT_EUR_PER_1M = 6.91) -> None:
    """Print token usage, rough € cost, and finish reason for a chat completion."""
    pt = resp.usage.prompt_tokens
    ct = resp.usage.completion_tokens
    tt = resp.usage.total_tokens
    print(f"prompt: {pt}, completion: {ct}, total: {tt}")
    cost_eur = (pt / 1_000_000) * INPUT_EUR_PER_1M + (
        ct / 1_000_000
    ) * OUTPUT_EUR_PER_1M
    print(f"Cost per doc: €{cost_eur:.2f}")
    print(f"Cost all: €{2000*cost_eur:.2f}")    
    print(
        "Finish reason (if length then truncated output) = ",
        getattr(resp.choices[0], "finish_reason", None),
    )

def get_df_cpcgav_all(df_cpcg: pd.DataFrame, df_av_all: pd.DataFrame) -> pd.DataFrame:
    """Concat CG/CP & AV, normalize 'null' dates, sort, and clean helper column."""
    df = pd.concat([df_cpcg, df_av_all])
    df[["signature_date_cp", "signature_date_av"]] = df[
        ["signature_date_cp", "signature_date_av"]
    ].replace("null", pd.NA)
    df["signature_date_any"] = df["signature_date_av"].combine_first(df["signature_date_cp"])
    df["signature_date_any"] = pd.to_datetime(df["signature_date_any"], errors="coerce")
    df = df.sort_values("signature_date_any").drop(columns=["signature_date_any"]).reset_index(drop=True)
    return df

def loyer2null(df: pd.DataFrame, safe_flag: bool = True) -> pd.DataFrame:
    """For one-shot & non-volume rows, move 'loyer' to 'price_unitaire' and null recurring fields."""
    df = df.copy()
    df = df
    if safe_flag == True:
        try:
            df["one_shot_service"] = df["one_shot_service"].astype(bool)
            df["is_volume_product"] = df["is_volume_product"].astype(bool)
        except:
            print("WARNING unsafe loyer2null call. returning original df")
            return df
        if sorted(df["one_shot_service"].unique()) != sorted([False, True]) or sorted(
            df["is_volume_product"].unique()
        ) != sorted([False, True]):
            print("WARNING unsafe loyer2null call. returning original df")
            return df
    df["price_unitaire_f"] = pd.to_numeric(
        df["price_unitaire"].replace({"null": np.nan}), errors="coerce"
    )
    one_shot_mask = df["one_shot_service"].astype(bool)
    move_mask = one_shot_mask & df["price_unitaire_f"].isna() & df["loyer"].notna()
    print("moving badly classified loyer to price... number of affected rows =", int(move_mask.sum()))
    df.loc[move_mask, "price_unitaire"] = df.loc[move_mask, "loyer"]

    cols_to_null = ["loyer", "loyer_facturation", "loyer_annuele", "billing_frequency", "loyer_periodicity"]
    not_volume_mask = ~df["is_volume_product"].astype(bool)
    no_loyer_mask = one_shot_mask & not_volume_mask
    for c in cols_to_null:
        if c in df.columns:
            df.loc[no_loyer_mask, c] = np.nan

    return df.drop(columns=["price_unitaire_f"])

def upsert_to_cosmos(affair_df: pd.DataFrame, affair: str, cosmos_table: Any) -> None:
    """Upsert all rows as a single batch item {id=affair, rows=[...] }."""
    rows = json.loads(affair_df.to_json(orient="records"))
    cosmos_table.upsert_item({"id": affair, "rows": rows})

def validate_columns(df: pd.DataFrame, col_order: List[str]) -> None:
    """Ensure df columns exactly match `col_order` (order & membership)."""
    df_only = [c for c in df.columns if c not in col_order]
    expected_only = [c for c in col_order if c not in df.columns]
    print("df.cols == col_order:", len(df.columns) == len(col_order))
    if df_only or expected_only:
        print("Unexpected in df (not in col_order):", df_only)
        print("Missing from df (expected in col_order):", expected_only)
        raise ValueError("Column mismatch between df and col_order")

def rectify_df(df_cpcg: pd.DataFrame, col_order: List[str]) -> pd.DataFrame:
    """Fill NA with 'null' and reorder columns after schema validation."""
    df_out = df_cpcg.copy()
    validate_columns(df_out, col_order)
    df_out = df_out.fillna("null")[col_order]
    print("df_cpcg shape =", df_out.shape)
    return df_out

def run_cgcp_pipeline(
    content_cadre: List[str],
    content_sous: List[str],
    client_oai: Any,
    cgcp_question: str,
    financial_prompt: str,
    financial_tools: Any,
    col_order: List[str],
) -> pd.DataFrame:
    """
    Build a CG+CP prompt, call the model, and return a rectified products DataFrame.

    Steps
    -----
    1) Join CG/CP blocks into strings via `process_cgcp`.
    2) Build messages for the CG+CP extraction via `build_message_cgcp`.
    3) Call the model with tools via `get_response_df` to obtain a products DataFrame.
    4) Rectify the DataFrame schema/order via `rectify_df`.

    Parameters
    ----------
    content_cadre : list[str]
        Text blocks detected as CG (cadre).
    content_sous : list[str]
        Text blocks detected as CP (souscription).
    client_oai : Any
        Azure OpenAI client exposing `chat.completions.create(...)`.
    cgcp_question : str
        The task/question posed to the model for CG+CP extraction.
    financial_prompt : str
        System prompt used for financial extraction.
    financial_tools : Any
        Tool definitions passed to the completion call.
    col_order : list[str]
        Expected column order enforced by `rectify_df`.

    Returns
    -------
    pandas.DataFrame
        The rectified products table extracted from CG+CP content.
    """
    content_cadre_str, content_sous_str = process_cgcp(content_cadre, content_sous)
    messages_cpcg = build_message_cgcp(
        content_cadre_str, content_sous_str, cgcp_question, financial_prompt
    )
    affair_df = get_response_df(client_oai, messages_cpcg, financial_tools)
    affair_df = rectify_df(affair_df, col_order)
    return affair_df

def run_avenants_pipeline(
    content_avenant: List[str],
    client_oai: Any,
    avenant_question: str,
    financial_prompt: str,
    financial_tools: Any,
    col_order: List[str],
) -> Optional[pd.DataFrame]:
    """
    Build messages for each Avenant block, call the model, and concatenate results.

    Steps
    -----
    For each `avenant_str` in `content_avenant`:
      1) Build a prompt via `build_message_avenant`.
      2) Call the model with tools via `get_response_df` → DataFrame.
      3) Rectify the per-avenant DataFrame (as in your snippet).
      4) Accumulate into a list and finally `concat_avenant_df`.

    Parameters
    ----------
    content_avenant : list[str]
        List of already-prefixed Avenant text blocks.
    client_oai : Any
        Azure OpenAI client exposing `chat.completions.create(...)`.
    avenant_question : str
        The task/question posed to the model for Avenant extraction.
    financial_prompt : str
        System prompt used for financial extraction.
    financial_tools : Any
        Tool definitions passed to the completion call.

    Returns
    -------
    pandas.DataFrame or None
        Concatenated Avenant results (sorted) if any were produced; otherwise None.

    Notes
    -----
    - This function intentionally mirrors your original loop, including
      `rectify_df(df_av)` as written. Ensure `rectify_df` is compatible with
      this call in your environment.
    """
    df_av_list: List[pd.DataFrame] = []
    for i, avenant_str in enumerate(content_avenant, start=1):
        print(f"*****************  processing {i}/{len(content_avenant)} *****************")
        messages_av = build_message_avenant(avenant_str, avenant_question, financial_prompt)
        print("content [AV]=", len(avenant_str))
        df_av = get_response_df(client_oai, messages_av, financial_tools)
        rectify_df(df_av, col_order)  # kept exactly as in your snippet
        df_av_list.append(df_av)

    if df_av_list:
        df_av_all = concat_avenant_df(df_av_list)
        return df_av_all

    return None

def concat_avenant_df(df_av_list: List[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate and sort Avenant DataFrames by `avenant_number` with basic logging."""
    df_av_all = pd.concat(df_av_list, ignore_index=True)
    df_av_all = df_av_all.sort_values("avenant_number")
    print("df_av_all shape =", df_av_all.shape)
    print(
        "AV number [len(pdfs), unique number in df]",
        len(df_av_list),
        df_av_all["avenant_number"].nunique(),
    )
    return df_av_all

def save_df_local(affair, local_save_tag, cpcg_df, df_av_all, affair_df):
    tag = affair + "_" +local_save_tag
    print("saving dfs using the tag = ", tag)
    cpcg_df.to_markdown(f"cpcg_{tag}.md", index=False)
    cpcg_df.to_excel(f"cpcg_{tag}.xlsx")
    if df_av_all:
        df_av_all.to_markdown(f"df_av_all_{tag}.md", index=False)
    affair_df.to_markdown(f"affair_df_{tag}.md", index=False)
    affair_df.to_excel(f"affair_df_{tag}.xlsx")

def verify_cpcgav_separation(docs, content_cadre, content_sous, content_avenant):
    if len(docs) != len(content_cadre) + len(content_sous) + len(content_avenant):
        print("original docs:")
        print([d.get("id") for d in docs])
        raise ValueError("CG/CP/AV mismatch lenght with original documents")
    if len(content_sous)==0:
        raise ValueError("no CP in affair")