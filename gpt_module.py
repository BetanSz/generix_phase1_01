import json
import pandas as pd
import numpy as np


def get_docs(company_name, cosmos_digitaliezd, exclude_flag=True, verbose=True):
    doc_ids = list(
        cosmos_digitaliezd.query_items(
            query="SELECT VALUE c.id FROM c WHERE CONTAINS(c.id, @kw, true) AND ENDSWITH(c.id, '.pdf')",
            parameters=[{"name": "@kw", "value": company_name}],
            enable_cross_partition_query=True,
        )
    )
    if verbose:
        print("numbers of docs original = ", len(doc_ids))
    if exclude_flag:
        doc_ids = [doc for doc in doc_ids if "-ASP-" not in doc]
    if verbose:
        print("numbers of docs after exclusion = ", len(doc_ids))
    docs = [cosmos_digitaliezd.read_item(item=i, partition_key=i) for i in doc_ids]
    if verbose:
        print("All recuperated docs from company name:")
        for doc in docs:
            print(doc["id"], doc.get("blob_path"), doc.get("page_count"))
    return docs


def get_cpcgav(
    docs, cp_identifiers, cg_identifiers, av_identifiers, verbose=True, safe_flag=True
):
    content_cadre = [
        doc.get("content", "")
        for doc in docs
        if any([c_flag.lower() in doc["id"].lower() for c_flag in cg_identifiers])
        and "avenant" not in doc["id"].lower()
    ]
    content_sous = [
        doc.get("content", "")
        for doc in docs
        if any([c_flag.lower() in doc["id"].lower() for c_flag in cp_identifiers])
        # and "avenant" not in doc["id"].lower()
    ]
    content_avenant = [
        doc.get("content", "")
        for doc in docs
        if "AVENANT-".lower() in doc["id"].lower()
    ]
    content_avenant = [
        doc.get("content", "")
        for doc in docs
        if any([c_flag.lower() in doc["id"].lower() for c_flag in av_identifiers])
    ]
    if safe_flag:
        if len(content_cadre) == 0 and len(content_sous) == 0:
            raise ValueError("no CP or CG content")
    if verbose:
        print(
            "Amount documents [CG,CP,AV]=",
            len(content_cadre),
            len(content_sous),
            len(content_avenant),
        )
    return content_cadre, content_sous, content_avenant


def process_cgcp(content_cadre, content_sous, verbose=True):
    """ """
    content_cadre_str = "\n".join(content_cadre)
    content_sous_str = "\n".join(content_sous)
    if verbose:
        print(
            "len [str] content [cg,cp]=", len(content_cadre_str), len(content_sous_str)
        )
    return content_cadre_str, content_sous_str


def build_message_cgcp(
    content_cadre_str, content_sous_str, user_question, financial_prompt
):
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


def get_response_df(client_oai, message, tools):
    resp = client_oai.chat.completions.create(
        model="gpt-4.1",  # your deployment name from the portal
        messages=message,
        tools=tools,
        tool_choice="auto",  # tool_choice={"type":"function","function":{"name":"record_products"}}, #this produced a stop termination instead of toolcals (carter)=> due to some schema mismatch?
        temperature=0.05,  # 0
        max_tokens=32000,
    )
    print_resp_properties(resp)
    tool_call = resp.choices[0].message.tool_calls[0]
    args_str = tool_call.function.arguments
    data = json.loads(args_str)
    df = pd.json_normalize(data["products"])
    return df


def print_resp_properties(resp):
    pt = resp.usage.prompt_tokens
    ct = resp.usage.completion_tokens
    tt = resp.usage.total_tokens
    print(f"prompt: {pt}, completion: {ct}, total: {tt}")

    INPUT_EUR_PER_1M = 1.73
    OUTPUT_EUR_PER_1M = 6.91

    cost_eur = (pt / 1_000_000) * INPUT_EUR_PER_1M + (
        ct / 1_000_000
    ) * OUTPUT_EUR_PER_1M
    print(f"Cost per doc: €{cost_eur:.2f}")
    print(f"Cost all: €{2000*cost_eur:.2f}")

    print(
        "This should be tool_calls (if length then truncated output) =",
        getattr(resp.choices[0], "finish_reason", None),
    )


def get_df_cpcgav_all(df_cpcg, df_av_all):
    df_cpcgav_all = pd.concat([df_cpcg, df_av_all])
    df_cpcgav_all[["signature_date_cp", "signature_date_av"]] = df_cpcgav_all[
        ["signature_date_cp", "signature_date_av"]
    ].replace("null", pd.NA)
    df_cpcgav_all["signature_date_any"] = df_cpcgav_all[
        "signature_date_av"
    ].combine_first(df_cpcgav_all["signature_date_cp"])
    df_cpcgav_all["signature_date_any"] = pd.to_datetime(
        df_cpcgav_all["signature_date_any"], errors="coerce"
    )
    df_cpcgav_all = df_cpcgav_all.sort_values("signature_date_any")
    df_cpcgav_all = df_cpcgav_all.drop(columns=["signature_date_any"])
    df_cpcgav_all = df_cpcgav_all.reset_index(drop=True)
    return df_cpcgav_all


def loyer2null(df, safe_flag=True):
    df = df.copy()
    if safe_flag == True:
        if sorted(df["one_shot_service"].unique()) != sorted([False, True]) or sorted(
            df["is_volume_product"].unique()
        ) != sorted([False, True]):
            print("WARNING unsafe loyer2null call. returning original df")
            return df
    one_shot_mask = df["one_shot_service"].astype(bool) == True
    not_volume_mask = df["is_volume_product"].astype(bool) == False
    no_loyer_mask = one_shot_mask & not_volume_mask
    # (a) If price_unitaire is NaN and loyer has a value, move loyer into price_unitaire

    df["price_unitaire_f"] = pd.to_numeric(
        df["price_unitaire"].replace({"null": np.nan}), errors="coerce"
    )
    df["price_unitaire_f"].values

    move_mask = one_shot_mask & df["price_unitaire_f"].isna() & df["loyer"].notna()
    print(
        "moving badly classified loyer to price... number of affected rows = ",
        sum(move_mask),
    )
    df.loc[move_mask, "price_unitaire"] = df.loc[move_mask, "loyer"]

    # (b) For ALL one-shot rows, null out recurring/cadence fields
    cols_to_null = [
        "loyer",
        "loyer_facturation",
        "loyer_annuele",
        "billing_frequency",
        "loyer_periodicity",
    ]
    for c in cols_to_null:
        if c in df.columns:
            df.loc[no_loyer_mask, c] = np.nan
    df = df.drop(columns=["price_unitaire_f"])
    return df


def upsert_to_cosmos(affair_df, affair, cosmos_table):
    rows = json.loads(affair_df.to_json(orient="records"))
    batch = {"id": affair, "rows": rows}
    cosmos_table.upsert_item(batch)


def validate_columns(df, col_order):
    missing = [c for c in df.columns if c not in col_order]
    extra = [c for c in col_order if c not in df.columns]
    print("df.cols == col_order: ", len(df.columns) == len(col_order))
    if missing or extra:
        print("Missing-from-col_order:", missing)
        print("Missing-from-df (extra in col_order):", extra)
        raise ValueError("Column mismatch between df and col_order")


def rectify_df(df_cpcg, col_order):
    df_cpcg = df_cpcg.copy()
    validate_columns(df_cpcg, col_order)
    df_cpcg = df_cpcg.fillna("null")
    df_cpcg = df_cpcg[col_order]
    print("df_cpcg shape = ", df_cpcg.shape)
    return df_cpcg


def build_message_avenant(avenant_str, avenant_question, financial_prompt):
    content_av = "=== DOC: AVENANT — type=avenant ===\n" + avenant_str
    messages_av = [
        {"role": "system", "content": financial_prompt},
        {
            "role": "user",
            "content": f"DOCUMENT CONTENT:\n\n{content_av}\n\nTASK:\n{avenant_question}",
        },
    ]
    return messages_av


def concat_avenant_df(df_av_list):
    df_av_all = pd.concat(df_av_list)
    df_av_all = df_av_all.sort_values("avenant_number")
    print("df_av_all shape = ", df_av_all.shape)
    print(
        "AV number [len(pdfs), unique number in df]",
        len(df_av_list),
        df_av_all["avenant_number"].nunique(),
    )
    return df_av_all
