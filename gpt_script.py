import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json
import sys

from clients import cosmos_digitaliezd, client_oai
from gpt_prompt import *
import json, ast, re
import pandas as pd

def truncate_after_flag(text, annex_flag):
    if len(list(re.finditer(annex_flag, text, flags=re.IGNORECASE)))==1:
        i = text.find(annex_flag)
        if i!= -1:
            print("Safe truncation executed")
            return text[:i]
        else:
            print("Annex flag was not found. No truncation took place")
            return text
    else:
        print("Multiple matches for the Annex flag. Truncation considered unsafe")
        return text


items = cosmos_digitaliezd.read_all_items(max_item_count=100)
for i, doc in enumerate(items, start=1):
    print(i, doc["id"]) #, doc.get("blob_path")

#embed()
company_name = "S.N.F"
#company_name = "NORAUTO" # ok after truncation
#company_name = "SAVENCIA"
#company_name = "BOIRON"
doc_ids = list(cosmos_digitaliezd.query_items(
    query="SELECT VALUE c.id FROM c WHERE CONTAINS(c.id, @kw, true) AND ENDSWITH(c.id, '.pdf')",
    parameters=[{"name": "@kw", "value": company_name}],
    enable_cross_partition_query=True
))
print(doc_ids)

#doc = cosmos_digitaliezd.read_item(item=doc_id, partition_key=doc_id)
docs = [cosmos_digitaliezd.read_item(item=i, partition_key=i) for i in doc_ids]
for doc in docs:
    print(doc["id"], doc.get("blob_path"), doc.get("page_count"))

content_cadre = [doc.get("content", "") for doc in docs if "CADRE".lower() in doc["id"].lower()]
content_sous = [doc.get("content", "") for doc in docs if "SOUSCRIPTION".lower() in doc["id"].lower()]
assert len(content_cadre)>=1 and len(content_sous)>=1
annex_flag = "Annexe 1 :"
if len(content_cadre)==1 and len(content_sous)==1:
    content_cadre_str = content_cadre[0]
    content_sous_str = content_sous[0]
    print("len content [cadre, sous]=", len(content_cadre_str), len(content_sous_str))
    content_sous_str = truncate_after_flag(content_sous_str, annex_flag)
    print("len content [cadre, sous]=", len(content_cadre_str), len(content_sous_str))
elif len(content_cadre)==1 and len(content_sous)>=1:
    content_cadre_str = content_cadre[0]
    content_sous = [truncate_after_flag(text, annex_flag) for text in content_sous]
    content_sous_str = "\n".join(content_sous) 
else:
    print("TODO")

content = (
    "=== DOC: CADRE — type=cadre ===\n"
    + content_cadre_str.strip() + "\n\n"
    + "=== DOC: SOUSCRIPTION — type=souscription ===\n"
    + content_sous_str.strip()
)
user_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
messages = [
    {"role": "system", "content": financial_prompt},
    {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{content}\n\nTASK:\n{user_question}"}
]
# --- call Azure OpenAI (model = deployment name)
embed()
resp = client_oai.chat.completions.create(
    model="gpt-4.1",               # your deployment name from the portal
    messages=messages,
    tools=tools,
    tool_choice="auto",
    temperature=0.0,
    max_tokens=7000,
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
print(json.dumps(data, indent=2, ensure_ascii=False))

df = pd.json_normalize(data["products"])
print(df.to_markdown(index=False))

col_order  = ['company_name', 'signature_date_cg', 'signature_date_cp', 'product_code', 'product_name',
              'duree_de_service',  'duree_de_service_notes', 'term_mode', 'billing_frequency', "bon_de_command" ,'payment_methods', 'payment_terms', "debut_facturation",
 'price_unitaire',"quantity","loyer",'devise_de_facturation', 'price_periodicity', 'one_shot_service', 'tax_basis','is_included_or_free',
 'usage_overconsumption_price', 'usage_overconsumption_periodicity', 'usage_term_mode', 'overconsumption_term_mode', 
 'effective_date', 'billing_start_date', 'billing_modality_notes',
 'reval_method', 'reval_rate_per', 'reval_formula', 'reval_compute_when', 'reval_apply_when', "reval_apply_from",
       'reval_source',  
       'evidence_product', 'evidence_price', 'evidence_payment_methods',
       'evidence_usage', 'evidence_revalorization', 'evidence_billing',
       'evidence_dates', 'evidence_company', 'confidence_price',
       'confidence_usage', 'confidence_revalorization', 'confidence_billing',
       'confidence_dates', 'confidence_company'
       ] 
df=df.fillna("null")
df[col_order].to_markdown("product.md", index=False)
# df.to_csv("products.csv", index=False)
# df.to_excel("contract_products.xlsx", sheet_name="Products", index=False)
# pd.set_option("display.max_columns", None)   # show all columns
# pd.set_option("display.width", 0)            # auto-detect console width
# pd.set_option("display.max_colwidth", None)  # don't truncate cell text
# pd.set_option("display.expand_frame_repr", False)  # single-line wide frames
