import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json
import sys

from clients import cosmos_digitaliezd, client_oai, cosmos_table
from gpt_module_financial_agent import *

# from gpt_module_delta_agent import *
from gpt_module import *
import json, ast, re
import pandas as pd
import numpy as np


def get_cpcgav(docs, verbose=True, safe=True, avenant_ordering=True):
    # TODO: This is getting very fragile...
    # TODO: this ordering options, without llms seems fine actually.
    cp_identifiers = ["SOUSCRIPTION", "CP", "PRESTATIONS"]
    cg_identifiers = ["CADRE", "CG"]
    content_cadre = [
        doc.get("content", "")
        for doc in docs
        if  any([c_flag.lower() in doc["id"].lower() for c_flag in cg_identifiers])
    ]
    content_sous = [
        doc.get("content", "")
        for doc in docs
        if any([c_flag.lower() in doc["id"].lower() for c_flag in cp_identifiers])
    ]
    if safe:
        assert len(content_cadre) >= 1 and len(content_sous) >= 1
    if avenant_ordering:
        avenant_id_content_list = [
            (doc.get("id", ""), doc.get("content", ""))
            for doc in docs
            if "AVENANT-".lower() in doc["id"].lower()
        ]
        # OBS: tuple structre (id, content, on=irdering on file name, oc=ordering of file content)
        avenant_id_content_index_list = [
            (
                id,
                content,
                parse_date_from_filename(id),
                parse_date_from_text_fr(content),
            )
            for id, content in avenant_id_content_list
        ]
        sorting_key = 2  # parse_date_from_filename(id) -> from filname
        sorting_key = 3  # parse_date_from_text_fr(content) -> from content
        avenant_id_content_index_list = sorted(
            avenant_id_content_index_list, key=lambda x: x[sorting_key]
        )
        if verbose:
            print("Avenant ordering:")
            for id, _, on, oc in avenant_id_content_index_list:
                print(on, oc)
        content_avenant = [
            content for _, content, _, _ in avenant_id_content_index_list
        ]
    else:
        content_avenant = [
            doc.get("content", "")
            for doc in docs
            if "AVENANT-".lower() in doc["id"].lower()
        ]
    if verbose:
        print(
            "Amount documents [CG,CP,AV]=",
            len(content_cadre),
            len(content_sous),
            len(content_avenant),
        )
    return content_cadre, content_sous, content_avenant


def process_cgcp(content_cadre, content_sous, tools_annex, annex_prompt, do_truncation, safe_flag=False, verbose=True):
    if len(content_cadre) == 1 and len(content_sous) == 1:
        content_cadre_str = content_cadre[0]
        content_sous_str = gpt_truncation(
            content_sous[0], tools_annex, annex_prompt, do_truncation, client_oai
        )
    elif len(content_cadre) == 1 and len(content_sous) >= 1:
        content_cadre_str = content_cadre[0]
        content_sous_str = "\n".join(
            gpt_truncation(t, tools_annex, annex_prompt, do_truncation, client_oai)
            for t in content_sous
        )
    elif safe_flag==False: #no expectation of amount of docs in cp or cg
        content_cadre_str = "\n".join(content_cadre)
        content_sous_str = "\n".join(content_sous)
    else:
        raise ValueError("Unexpected lengths.")
    if verbose:
        print("len [str] content [cg,cp]=", len(content_cadre_str), len(content_sous_str))
    return content_cadre_str, content_sous_str


items = cosmos_digitaliezd.read_all_items(max_item_count=100)
print("total amount of items in DB =", len([item for item in items]))
# for i, doc in enumerate(items, start=1):
#    print(i, doc["id"]) #, doc.get("blob_path")

def get_docs(company_name, exclude_flag=True, verbose=True):
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
            print(
                doc["id"][-70 : len(doc["id"])], doc.get("blob_path"), doc.get("page_count")
            )
    return docs

#embed()
safe_flag = False
do_truncation_flag = False
# embed()
# company_name = "S.N.F"
# company_name = "NORAUTO" # ok after truncation
# company_name = "SAVENCIA"
# company_name = "BOIRON"
# company_name = "AIRBUS-HELICOPTERS"
# company_name = "CULTURA"
company_name = "suez"
docs = get_docs(company_name)
content_cadre, content_sous, content_avenant = get_cpcgav(docs, safe=safe_flag)
content_cadre_str, content_sous_str = process_cgcp(
    content_cadre, content_sous, tools_annex, annex_prompt, do_truncation_flag, safe_flag=safe_flag
)

content_cpcg = (
    "=== DOC: CADRE — type=cadre ===\n"
    + content_cadre_str.strip()
    + "\n\n"
    + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
    + content_sous_str.strip()
)

# the complete contract => generates summerization
# start_tag = "=== DOC: AVENANT/START ==="
# end_tag   = "=== DOC: AVENANT/END ==="
#
# blocks = [
#    f"{start_tag} label=pdf{i+1}\n{avenant.strip()}\n{end_tag}"
#    for i, avenant in enumerate(content_avenant)
# ]
# content_avenant_str = "\n\n".join(blocks)
# content = (
#    "=== DOC: CADRE — type=cadre ===\n"
#    + content_cadre_str.strip() + "\n\n"
#    + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
#    + content_sous_str.strip()
#    + "=== DOC: AVENANT — type=avenant ===\n"
#    + content_avenant_str
# )

user_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
messages_cpcg = [
    {"role": "system", "content": financial_prompt},
    {
        "role": "user",
        "content": f"DOCUMENT CONTENT:\n\n{content_cpcg}\n\nTASK:\n{user_question}",
    },
]

embed()
sys.exit()
anticache_version = "newer_volumne_01"
#TODO: try this instead tool_choice={"type":"function","function":{"name":"record_products"}}
# TODO: copy colorder in required fiels schema
# TODO: add this to the description of tools “Return per-product financial rows. This tool’s schema is the authoritative JSON format for output. Include all keys (use null if unknown).”
#TODO: and this to the system prompt “Always return final results by calling record_products with a complete payload—do not write plain text.”
df_cpcg = get_response_df(client_oai, messages_cpcg, financial_tools)

validate_columns(df_cpcg, col_order)
df_cpcg = df_cpcg.fillna("null")
df_cpcg = df_cpcg[col_order]
print("df_cpcg shape = ", df_cpcg.shape)
df_cpcg.to_markdown(f"product_cpcg_{anticache_version}.md", index=False)
df_cpcg.to_excel(f"product_cpcg_{anticache_version}.xlsx")

user_question = "Extract all the products found in each avenant sections with their financial conditions using the rules and return products via the tool."
df_av_list = []
# TODO: generate a contract state, handled by an agent with a different system promp as to update it while you read the avenants.
# howoever in order to do this in a simple way, you need to have them ordered by time.
# obs: the regex from the pdf name works well and you can always do a pass to get the date using another agent.

for i, avenant_str in enumerate(content_avenant, start=1):
    print(f"*****************  processing {i}/{len(content_avenant)} *****************")
    content_av = "=== DOC: AVENANT — type=avenant ===\n" + avenant_str
    # if df_av_list:
    #    prior_state = pd.concat([df_cpcg] + df_av_list)
    # else:
    #    prior_state = df_cpcg
    # prior_state = prior_state.to_json(orient="records", force_ascii=False)
    # delta = get_avenant_delta(client_oai, delta_tool, delta_prompt, prior_state, avenant_str)
    # print(json.dumps(delta, ensure_ascii=False, indent=2))
    messages_av = [
        {"role": "system", "content": financial_prompt},
        {
            "role": "user",
            "content": f"DOCUMENT CONTENT:\n\n{content_av}\n\nTASK:\n{user_question}",
        },
    ]
    print("content [CPCG, AV]=", len(content_av))
    df_av = get_response_df(client_oai, messages_av, financial_tools)
    validate_columns(df_av, col_order)
    df_av = df_av.fillna("null")
    print("output shape = ", df_av.shape)
    df_av_list.append(df_av)

if df_av_list:
    df_av_all = pd.concat(df_av_list)
    validate_columns(df_av_all, col_order)
    df_av_all = df_av_all[col_order].sort_values("avenant_number")
    print("df_av_all shape = ", df_av_all.shape)
    print(
        "AV number [len(pdfs), unique number in df]",
        len(content_avenant),
        df_av_all["avenant_number"].nunique(),
    )
    
    df_av_all.to_markdown(f"product_av_{anticache_version}.md", index=False)
    
    df_cpcgav_all = get_df_cpcgav_all(df_cpcg, df_av_all)
    df_cpcgav_all.to_markdown(f"product_cpcgav_{anticache_version}.md", index=False)
    df_cpcgav_all.to_excel(f"product_cpcgav_{anticache_version}.xlsx")


# df2json = df.replace({np.nan: None})
# rows = json.loads(df2json.to_json(orient="records"))
# index_candidates = set([build_response_id(pdf).lower() for pdf in doc_ids])
# if len(index_candidates)==1:
#    id = index_candidates.pop()
# else:
#    print("elegent id generation failed")
#    id = index_candidates.pop()
# print("id of contract:", id)
##embed()
#
# batch = {
#    "id": id,
#    "rows": rows
# }
# cosmos_table.upsert_item(batch)
