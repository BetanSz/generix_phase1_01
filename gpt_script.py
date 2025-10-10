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


items = list(cosmos_digitaliezd.read_all_items(max_item_count=100))
print("total amount of items in DB =", len([item for item in items]))
safe_flag = False
do_truncation_flag = False
avenant_ordering = False
for i, doc in enumerate(items, start=1):
    print(i, doc["id"]) #, doc.get("blob_path")
embed()
sys.exit()
# TODO: obs remove prestation from PC finding!
#company_name = "S.N.F"
#company_name = "NORAUTO" # ok after truncation
#company_name = "SAVENCIA"
#company_name = "BOIRON"
#company_name = "AIRBUS-HELICOPTERS"
company_name = "CULTURA"
#company_name = "suez"
#company_name = "carter"
#company_name = "edenred"
company_name = "renault"
#company_name = "hach" #AV only
company_name = "mason" # short contracts are not workign very well
#company_name = "fr_mes"
#company_name = "id_log" # difficult contract
#company_name = "invicta"
company_name = "coca"

docs = get_docs(company_name, cosmos_digitaliezd)
content_cadre, content_sous, content_avenant = get_cpcgav(docs, safe=safe_flag, avenant_ordering=avenant_ordering)
content_cadre_str, content_sous_str = process_cgcp(
    client_oai, content_cadre, content_sous, tools_annex, annex_prompt, do_truncation_flag, safe_flag=safe_flag
)
user_question = "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
messages_cpcg = build_message_cgcp(content_cadre_str, content_sous_str, user_question, financial_prompt)

embed()
sys.exit()
#TOOD: this is a big one, for 12 products the resp is at token limit befor summarization. Less columns are required for this model,
# or fillding them in a smarter way, like repeat less known values (currency dates, or ask for less evidence)
anticache_version = company_name + "_01"
df_cpcg = get_response_df(client_oai, messages_cpcg, financial_tools)

validate_columns(df_cpcg, col_order)
df_cpcg = df_cpcg.fillna("null")
df_cpcg = df_cpcg[col_order]
print("df_cpcg shape = ", df_cpcg.shape)
df_cpcg.to_markdown(f"product_cpcg_{anticache_version}.md", index=False)
print(f"product_cpcg_{anticache_version}.xlsx")
df_cpcg.to_excel(f"product_cpcg_{anticache_version}.xlsx")

user_question = "Extract all the products found in each avenant sections with their financial conditions using the rules and return products via the tool."
df_av_list = []
# TODO: generate a contract state, handled by an agent with a different system promp as to update it while you read the avenants.
# howoever in order to do this in a simple way, you need to have them ordered by time.
# obs: the regex from the pdf name works well and you can always do a pass to get the date using another agent.

for i, avenant_str in enumerate(content_avenant, start=1):
    print(f"*****************  processing {i}/{len(content_avenant)} *****************")
    content_av = "=== DOC: AVENANT — type=avenant ===\n" + avenant_str
    messages_av = [
        {"role": "system", "content": financial_prompt},
        {
            "role": "user",
            "content": f"DOCUMENT CONTENT:\n\n{content_av}\n\nTASK:\n{user_question}",
        },
    ]
    print("content [AV]=", len(content_av))
    df_av = get_response_df(client_oai, messages_av, financial_tools)
    validate_columns(df_av, col_order)
    df_av = df_av.fillna("null")
    print("output shape = ", df_av.shape)
    df_av_list.append(df_av)

if df_av_list:
    df_av_all = pd.concat(df_av_list)
    #validate_columns(df_av_all, col_order)
    df_av_all = df_av_all.sort_values("avenant_number")
    print("df_av_all shape = ", df_av_all.shape)
    print(
        "AV number [len(pdfs), unique number in df]",
        len(content_avenant),
        df_av_all["avenant_number"].nunique(),
    )
    df_av_all.to_markdown(f"product_av_{anticache_version}.md", index=False)
    df_cpcgav_all = get_df_cpcgav_all(df_cpcg, df_av_all)
    df_cpcgav_all = loyer2null(df_cpcgav_all, safe_flag=True)
    df_cpcgav_all = df_cpcgav_all.fillna("null")
    df_cpcgav_all.to_markdown(f"product_cpcgav_{anticache_version}.md", index=False)
    print(f"product_cpcgav_{anticache_version}.xlsx")
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
