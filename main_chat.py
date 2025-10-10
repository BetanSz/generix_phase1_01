"""

"""
import os
from IPython import embed
from pathlib import Path
import sys
from clients import cosmos_digitaliezd, client_oai
from gpt_module_financial_agent import *
from gpt_module import *

if __name__ == "__main__":
    items = list(cosmos_digitaliezd.read_all_items(max_item_count=100))
    print("total amount of items in DB =", len([item for item in items]))
    safe_flag = False
    do_truncation_flag = False
    avenant_ordering = False
    local_save_tag = "main"
    cgcp_question= "Extract the products found in the contract with their financial conditions using the rules and return products via the tool."
    avenant_question = "Extract all the products found in each avenant sections with their financial conditions using the rules and return products via the tool."
    for i, doc in enumerate(items, start=1):
        print(i, doc["id"]) #, doc.get("blob_path")
    for company_name in ["mason"]:
        docs = get_docs(company_name, cosmos_digitaliezd)
        content_cadre, content_sous, content_avenant = get_cpcgav(docs, safe=safe_flag, avenant_ordering=avenant_ordering)
        content_cadre_str, content_sous_str = process_cgcp(
        client_oai, content_cadre, content_sous, tools_annex, annex_prompt, do_truncation_flag, safe_flag=safe_flag
        )
        messages_cpcg = build_message_cgcp(content_cadre_str, content_sous_str, cgcp_question, financial_prompt)
        df_cpcg = get_response_df(client_oai, messages_cpcg, financial_tools)
        df_cpcg = rectify_df(df_cpcg, col_order)
        anticache_version = company_name + local_save_tag
        df_cpcg.to_markdown(f"product_cpcg_{anticache_version}.md", index=False)
        df_cpcg.to_excel(f"product_cpcg_{anticache_version}.xlsx")
        df_av_list = []
        for i, avenant_str in enumerate(content_avenant, start=1):
            print(f"*****************  processing {i}/{len(content_avenant)} *****************")
            messages_av = build_message_avenant(avenant_str, avenant_question, financial_prompt)
            print("content [AV]=", len(avenant_str))
            df_av = get_response_df(client_oai, messages_av, financial_tools)
            rectify_df(df_av)
            df_av_list.append(df_av)

        if df_av_list:
            df_av_all = concat_avenant_df(df_av_list)
            df_av_all.to_markdown(f"product_av_{anticache_version}.md", index=False)
            df_cpcgav_all = get_df_cpcgav_all(df_cpcg, df_av_all)
            df_cpcgav_all = loyer2null(df_cpcgav_all, safe_flag=True)
            df_cpcgav_all = df_cpcgav_all.fillna("null")
            df_cpcgav_all.to_markdown(f"product_cpcgav_{anticache_version}.md", index=False)
            print(f"product_cpcgav_{anticache_version}.xlsx")
            df_cpcgav_all.to_excel(f"product_cpcgav_{anticache_version}.xlsx")
        embed()
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


