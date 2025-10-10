"""

"""

from clients import client_di, container, cosmos_digitaliezd
from pathlib import Path
from di_module import * 

def main_document_intelligence(container, client_di, affair):
    pdfs_all = read_pdfs(container)
    print("len(pdfs_all):", len(pdfs_all))
    pdfs_company = select_affair(pdfs_all, affair)
    for pdf in pdfs_company:
        print(pdf)
    print("len(pdfs_company) = ", len(pdfs_company))
    docs = upsert_cosmos_df(container, client_di, pdfs_company)
    print_price_estimations(docs)
    out_dir = Path(r"C:\Users\EstebanSzames\OneDrive - CELLENZA\Bureau\Generix\generix_phase1_01\doc_digitalized_sample")
    write_local_mk_files(docs, out_dir)

if __name__ == "__main__":
    affair = "suez"
    performe_document_intelligence_read=False
    if performe_document_intelligence_read:
        main_document_intelligence(container, client_di, affair)