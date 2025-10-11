""" """

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
