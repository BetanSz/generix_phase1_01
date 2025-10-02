import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json
from datetime import datetime
from unidecode import unidecode
from datetime import date


def truncate_after_flag(text, annex_flag, signature_flag_list):
    if len(list(re.finditer(annex_flag, text, flags=re.IGNORECASE)))==1:
        i = text.find(annex_flag)
        j = [text.find(signature) for signature in signature_flag_list]
        print(i, j)
        j = max(j)
        if i!= -1 and i>j:
            print("Safe truncation executed")
            print("len before truncation =", len(text))
            text = text[:i]
            print("len after truncation =", len(text))
            return text
        else:
            print("Annex flag was not found. No truncation took place")
            return text
    else:
        print("Multiple matches for the Annex flag. Truncation considered unsafe")
        return text

def gpt_truncation(content_sous_str, tools_annex, annex_prompt, do_truncation, client_oai):
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

def build_response_id(text):
    stem = Path(text).stem                        # drop extension
    base = re.split(r'-(?:CG|CP|CONTRAT-CADRE|CONTRAT-SOUSCRIPTION)|_gcr_contrat-de-souscription|__contrat_cadre_saas\b',
                     stem, 1, flags=re.IGNORECASE)[0]
    return base 

def print_resp_properties(resp):
    pt = resp.usage.prompt_tokens
    ct = resp.usage.completion_tokens
    tt = resp.usage.total_tokens
    print(f"prompt: {pt}, completion: {ct}, total: {tt}")

    INPUT_EUR_PER_1M  = 1.73
    OUTPUT_EUR_PER_1M = 6.91

    cost_eur = (pt/1_000_000)*INPUT_EUR_PER_1M + (ct/1_000_000)*OUTPUT_EUR_PER_1M
    print(f"Cost per doc: €{cost_eur:.2f}") 
    print(f"Cost all: €{2000*cost_eur:.2f}")

    tool_call = resp.choices[0].message.tool_calls[0]
    print("This should be tool_calls (if length then truncated output) =",getattr(resp.choices[0], "finish_reason", None))
    args_str = tool_call.function.arguments  # from the SDK
    print("len:", len(args_str))
    print("tail:", args_str[-120:])   # last 120 chars
    print("last char:", args_str[-1])

def validate_columns(df, col_order):
    missing = [c for c in df.columns if c not in col_order]
    extra   = [c for c in col_order if c not in df.columns]
    print(len(df.columns), len(col_order))
    if missing or extra:
        print("Missing-from-col_order:", missing)
        print("Missing-from-df (extra in col_order):", extra)
        raise ValueError("Column mismatch between df and col_order")
    

MONTHS_FR = {
    "janvier":1, "janv":1, "jan":1,
    "fevrier":2, "février":2, "fevr":2, "fev":2, "févr":2,
    "mars":3,
    "avril":4, "avr":4,
    "mai":5,
    "juin":6,
    "juillet":7, "juil":7,
    "aout":8, "août":8, "aou":8,
    "septembre":9, "sept":9, "sep":9,
    "octobre":10, "oct":10,
    "novembre":11, "nov":11,
    "decembre":12, "décembre":12, "dec":12, "déc":12,
}

def parse_date_from_text_fr(text: str):
    if not text:
        return None

    # Signatures are near the end; reduce noise & speed up
    tail = text[-8000:] if len(text) > 8000 else text
    norm = unidecode(tail.lower())
    norm = re.sub(r'\s+', ' ', norm)

    candidates = []

    # 1) ISO-like: YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD
    for m in re.finditer(r'\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b', norm):
        y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        candidates.append((m.start(), date(y, mm, dd)))

    # 2) D/M/Y or D-M-Y (assume DMY if day<=31 and month<=12)
    for m in re.finditer(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b', norm):
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = yy + 2000 if yy < 100 else yy
        if 1 <= dd <= 31 and 1 <= mm <= 12 and 2000 <= y <= 2100:
            candidates.append((m.start(), date(y, mm, dd)))

    # 3) "le 26 juin 2015" or "26 juin 2015"
    for m in re.finditer(r'\b(?:le\s+)?(\d{1,2})\s+([a-zéû]+)\s+(20\d{2})\b', norm):
        dd, month_word, y = int(m.group(1)), m.group(2), int(m.group(3))
        month_key = month_word  # already unidecoded
        mm = MONTHS_FR.get(month_key)
        if mm and 1 <= dd <= 31:
            candidates.append((m.start(), date(y, mm, dd)))

    if not candidates:
        return None

    # choose the last occurrence in the tail (closest to signature)
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]

def parse_date_from_filename(name):
    # e.g. "...-201709-062279-AVENANT-8-..."
    m = re.search(r'-(20\d{2})(\d{2})-', name)
    if m:
        y, mth = int(m.group(1)), int(m.group(2))
        return datetime(y, mth, 1).date()
    return None