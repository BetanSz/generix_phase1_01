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
[doc.get("id", "") for doc in docs if "AVENANT-".lower() in doc["id"].lower()][:4]
print(len(content_cadre), len(content_sous), len(content_avenant))
assert len(content_cadre)>=1 and len(content_sous)>=1

def gpt_truncation(content_sous_str, tools_annex, annex_prompt, do_truncation):
    """
    this hard trucncation impact culture semester declinantion.
    TODO: remove some sections only and summerize the rest
    """
    if not do_truncation:
        return content_sous_str
    content = (content_sous_str.strip())
    user_question = "Provie the Annex or Appendix using the rules"
    messages = [
        {"role": "system", "content": annex_prompt},
        {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{content}\n\nTASK:\n{user_question}"}
    ]
    resp = client_oai.chat.completions.create(
        model="gpt-4.1",               # your deployment name from the portal
        messages=messages,
        tools=tools_annex,
        tool_choice="auto",
        temperature=0.05, #0
        max_tokens=5000,
    )
    tc = resp.choices[0].message.tool_calls[0]
    args = json.loads(tc.function.arguments)

    annex_line_idx = args["line_index"]
    annex_heading   = args["annex_line"]
    annex_context   = args["context"]
    print("Annex truncation found:")
    print(annex_heading, annex_line_idx)

    # Truncate the CP right before the annex:
    lines = content.splitlines()
    truncated = "\n".join(lines[:annex_line_idx])
    print("before/after truncation", len(content_sous_str), len(truncated))
    return truncated

def process_docs(content_cadre, content_sous,  tools_annex, annex_prompt, do_truncation):
    if len(content_cadre)==1 and len(content_sous)==1:
        content_cadre_str = content_cadre[0]
        content_sous_str  = gpt_truncation(content_sous[0],  tools_annex, annex_prompt, do_truncation)
        return content_cadre_str, content_sous_str
    elif len(content_cadre)==1 and len(content_sous)>=1:
        content_cadre_str = content_cadre[0]
        content_sous_str  = "\n".join(gpt_truncation(t,  tools_annex, annex_prompt, do_truncation) for t in content_sous)
        return content_cadre_str, content_sous_str
    else:
        raise ValueError("Unexpected lengths.")

do_truncation=False
content_cadre_str, content_sous_str = process_docs(content_cadre, content_sous,  tools_annex, annex_prompt, do_truncation)

start_tag = "=== DOC: AVENANT/START ==="
end_tag   = "=== DOC: AVENANT/END ==="

blocks = [
    f"{start_tag} label=pdf{i+1}\n{avenant.strip()}\n{end_tag}"
    for i, avenant in enumerate(content_avenant)
]

#embed()
blocks = blocks[:4]
#blocks = []
content_avenant_str = "\n\n".join(blocks)

#content_sous_str = content_sous[0]
print(len(content_cadre_str), len(content_sous_str), len(content_avenant_str))
content = (
    "=== DOC: CADRE — type=cadre ===\n"
    + content_cadre_str.strip() + "\n\n"
    + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
    + content_sous_str.strip()
    + "=== DOC: AVENANT — type=avenant ===\n"
    + content_avenant_str
)
user_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
messages = [
    {"role": "system", "content": financial_prompt},
    {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{content}\n\nTASK:\n{user_question}"}
]

embed()
sys.exit()
resp = client_oai.chat.completions.create(
    model="gpt-4.1",               # your deployment name from the portal
    messages=messages,
    tools=financial_tools,
    tool_choice="auto",
    temperature=0.05, #0
    max_tokens=25000,
)

pt = resp.usage.prompt_tokens
ct = resp.usage.completion_tokens
tt = resp.usage.total_tokens
print(f"prompt: {pt}, completion: {ct}, total: {tt}")

INPUT_EUR_PER_1M  = 1.73
OUTPUT_EUR_PER_1M = 6.91

cost_eur = (pt/1_000_000)*INPUT_EUR_PER_1M + (ct/1_000_000)*OUTPUT_EUR_PER_1M
print(f"Cost per doc: €{cost_eur:.2f}") 
print(f"Cost all: €{10000*cost_eur:.2f}")

tool_call = resp.choices[0].message.tool_calls[0]

print("This should be tool_calls (if length then truncated output) =",getattr(resp.choices[0], "finish_reason", None))

args_str = tool_call.function.arguments  # from the SDK
print("len:", len(args_str))
print("tail:", args_str[-120:])   # last 120 chars
print("last char:", args_str[-1])
data = json.loads(args_str)
#print(json.dumps(data, indent=2, ensure_ascii=False))

df = pd.json_normalize(data["products"])
#print(df.to_markdown(index=False))

col_order  = ['company_name', "numero_de_contrat" ,'signature_date_cg', 'signature_date_cp','signature_date_av','avenant_number', 'product_code', 'product_name',
              'duree_de_service',  'duree_de_service_notes', "date_end_of_contract" ,'reconduction_tacite','term_mode', 'billing_frequency', "bon_de_command" ,'payment_methods', 'payment_terms', "debut_facturation",
 'price_unitaire',"quantity","is_volume_product","loyer","loyer_facturation","loyer_annuele",'devise_de_facturation', 'loyer_periodicity', "total_abbonement_mensuel" ,'one_shot_service', 'tax_basis','is_included',
 'usage_overconsumption_price', 'usage_overconsumption_periodicity', 'usage_term_mode', 'overconsumption_term_mode', "usage_notes",
 'service_start_date', 'billing_modality_notes',
 'reval_method', 'reval_rate_per', 'reval_formula', 'reval_compute_when', 'reval_apply_when', "reval_apply_from",
       'reval_source',  
       'evidence_product', 'evidence_price', 'evidence_payment_methods','total_abbonement_mensuel_evidence', 'evidence_date_end_of_contract', "evidence_avenant",
       'evidence_usage', 'evidence_revalorization', 'evidence_billing',
       'evidence_dates', 'confidence_price',
       'confidence_usage', 'confidence_revalorization', 'confidence_billing',
       'confidence_dates', 'confidence_company', 'confidence_avenant'
       ]

def validate_columns(df, col_order):
    missing = [c for c in df.columns if c not in col_order]
    extra   = [c for c in col_order if c not in df.columns]
    print(len(df.columns), len(col_order))
    if missing or extra:
        print("Missing-from-col_order:", missing)
        print("Missing-from-df (extra in col_order):", extra)
        raise ValueError("Column mismatch between df and col_order")
validate_columns(df, col_order)

df=df.fillna("null")
print("output shape = ",df.shape)
df[col_order].to_markdown("product_pppp.md", index=False)












df.to_markdown("product_raw.md", index=False)
df[col_order].to_excel(f"{company_name}.xlsx", index=False)


df2json = df.replace({np.nan: None})
rows = json.loads(df2json.to_json(orient="records"))
index_candidates = set([build_response_id(pdf).lower() for pdf in doc_ids])
if len(index_candidates)==1:
    id = index_candidates.pop()
else:
    print("elegent id generation failed")
    id = index_candidates.pop()
print("id of contract:", id)
#embed()

batch = {
    "id": id,
    "rows": rows
}
cosmos_table.upsert_item(batch)