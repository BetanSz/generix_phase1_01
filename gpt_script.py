import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json
import sys

from clients import cosmos_digitaliezd, client_oai, cosmos_table
from gpt_prompt import *
from gpt_module import *
import json, ast, re
import pandas as pd
import numpy as np


items = cosmos_digitaliezd.read_all_items(max_item_count=100)
for i, doc in enumerate(items, start=1):
    print(i, doc["id"]) #, doc.get("blob_path")

#embed()
#company_name = "S.N.F"
#company_name = "NORAUTO" # ok after truncation
#company_name = "SAVENCIA"
#company_name = "BOIRON"
#company_name = "AIRBUS-HELICOPTERS"
company_name = "CULTURA"
doc_ids = list(cosmos_digitaliezd.query_items(
    query="SELECT VALUE c.id FROM c WHERE CONTAINS(c.id, @kw, true) AND ENDSWITH(c.id, '.pdf')",
    parameters=[{"name": "@kw", "value": company_name}],
    enable_cross_partition_query=True
))
doc_ids = [doc for doc in doc_ids if "-ASP-" not in doc]
print(doc_ids)
print(len(doc_ids))

#doc = cosmos_digitaliezd.read_item(item=doc_id, partition_key=doc_id)
docs = [cosmos_digitaliezd.read_item(item=i, partition_key=i) for i in doc_ids]
for doc in docs:
    print(doc["id"], doc.get("blob_path"), doc.get("page_count"))

#TODO: This is getting very fragile...
content_cadre = [doc.get("content", "") for doc in docs if "CADRE".lower() in doc["id"].lower() or "CG".lower() in doc["id"].lower()]
content_sous = [doc.get("content", "") for doc in docs if "SOUSCRIPTION".lower() in doc["id"].lower() or "CP".lower() in doc["id"].lower()]
content_avenant = [doc.get("content", "") for doc in docs if "AVENANT-".lower() in doc["id"].lower()]

# TODO: this ordering options, without llms seems fine actually.
pdf_names = [doc.get("id", "") for doc in docs if "AVENANT-".lower() in doc["id"].lower()]
order_pdf = [parse_date_from_filename(name) for name in pdf_names]
order_content = [parse_date_from_text_fr(content) for content in content_avenant]
order_both = list(zip(order_pdf, order_content, pdf_names))
order_both

print(len(content_cadre), len(content_sous), len(content_avenant))
assert len(content_cadre)>=1 and len(content_sous)>=1

def process_docs(content_cadre, content_sous,  tools_annex, annex_prompt, do_truncation):
    if len(content_cadre)==1 and len(content_sous)==1:
        content_cadre_str = content_cadre[0]
        content_sous_str  = gpt_truncation(content_sous[0],  tools_annex, annex_prompt, do_truncation, client_oai)
        return content_cadre_str, content_sous_str
    elif len(content_cadre)==1 and len(content_sous)>=1:
        content_cadre_str = content_cadre[0]
        content_sous_str  = "\n".join(gpt_truncation(t,  tools_annex, annex_prompt, do_truncation, client_oai) for t in content_sous)
        return content_cadre_str, content_sous_str
    else:
        raise ValueError("Unexpected lengths.")

do_truncation=False
content_cadre_str, content_sous_str = process_docs(content_cadre, content_sous,  tools_annex, annex_prompt, do_truncation)
print("len content [cg,cp,av]=",len(content_cadre_str), len(content_sous_str))

content_cpcg = (
    "=== DOC: CADRE — type=cadre ===\n"
    + content_cadre_str.strip() + "\n\n"
    + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
    + content_sous_str.strip()
)

user_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
messages_cpcg = [
    {"role": "system", "content": financial_prompt},
    {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{content_cpcg}\n\nTASK:\n{user_question}"}
]

embed()
sys.exit()
anticache_version = "dual_07_2review"
resp = client_oai.chat.completions.create(
    model="gpt-4.1",               # your deployment name from the portal
    messages=messages_cpcg,
    tools=financial_tools,
    tool_choice="auto",
    temperature=0.05, #0
    max_tokens=25000,
)
print_resp_properties(resp)
tool_call = resp.choices[0].message.tool_calls[0]
args_str = tool_call.function.arguments
data = json.loads(args_str)
df_cpcg = pd.json_normalize(data["products"])
validate_columns(df_cpcg, col_order)

df_cpcg=df_cpcg.fillna("null")
print("output shape = ",df_cpcg.shape)
df_cpcg[col_order].to_markdown(f"product_cpcg_{anticache_version}.md", index=False)

user_question = ("Extract all the products found in each avenant sections with their financial conditions using the rules and return products via the tool."
+ "Treat each avenant independently and repeat products if found multiple times")
df_av_list = []
#TODO: generate a contract state, handled by an agent with a different system promp as to update it while you read the avenants.
# howoever in order to do this in a simple way, you need to have them ordered by time.
#obs: the regex from the pdf name works well and you can always do a pass to get the date using another agent.
for i, avenant_str in enumerate(content_avenant, start=1):
    print(f"processing {i}/{len(content_avenant)}")
    content_av = ("=== DOC: AVENANT — type=avenant ===\n" + avenant_str)
    messages_av = [
        {"role": "system", "content": financial_prompt},
        {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{content_av}\n\nTASK:\n{user_question}"}
    ]
    print("content [CPCG, AV]=", len(content_cpcg), len(content_av))
    resp = client_oai.chat.completions.create(
        model="gpt-4.1",               # your deployment name from the portal
        messages=messages_av,
        tools=financial_tools,
        tool_choice="auto",
        temperature=0.05, #0
        max_tokens=25000,
    )
    print_resp_properties(resp)
    tool_call = resp.choices[0].message.tool_calls[0]
    args_str = tool_call.function.arguments
    data = json.loads(args_str)
    df_av = pd.json_normalize(data["products"])
    validate_columns(df_av, col_order)
    df_av=df_av.fillna("null")
    print("output shape = ",df_av.shape)
    df_av_list.append(df_av)

df_av_all = pd.concat(df_av_list)
df_av_all = df_av_all.sort_values("avenant_number")
print("AV number [len(pdfs), unique number in df]",len(content_avenant), df_av_all["avenant_number"].nunique())
df_av_all[col_order].to_markdown(f"product_av_{anticache_version}.md", index=False)

df_cpcgav_all = pd.concat([df_cpcg, df_av_all])
df_cpcgav_all[["signature_date_cp","signature_date_av"]] = (
    df_cpcgav_all[["signature_date_cp","signature_date_av"]]
    .replace("null", pd.NA)
)
df_cpcgav_all["signature_date_any"] = (
    df_cpcgav_all["signature_date_av"].combine_first(df_cpcgav_all["signature_date_cp"])
)
df_cpcgav_all["signature_date_any"] = pd.to_datetime(df_cpcgav_all["signature_date_any"], errors="coerce")
df_cpcgav_all = df_cpcgav_all.sort_values("signature_date_any")
df_cpcgav_all.to_markdown(f"product_cpcgav_{anticache_version}.md", index=False)


#df2json = df.replace({np.nan: None})
#rows = json.loads(df2json.to_json(orient="records"))
#index_candidates = set([build_response_id(pdf).lower() for pdf in doc_ids])
#if len(index_candidates)==1:
#    id = index_candidates.pop()
#else:
#    print("elegent id generation failed")
#    id = index_candidates.pop()
#print("id of contract:", id)
##embed()
#
#batch = {
#    "id": id,
#    "rows": rows
#}
#cosmos_table.upsert_item(batch)