import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json

def compute_confidence(parsed):
    score = 0
    reasons = []

    # Source strength
    if parsed.get("evidence_overall_min", "").lower().find("total montant") != -1:
        score += 0.5; reasons.append("explicit_total_min")
    if parsed.get("evidence_overall_max"):
        score += 0.1

    # Arithmetic consistency
    bm, tm = parsed.get("base_monthly_mandatory"), parsed.get("term_months")
    btot = parsed.get("base_term_mandatory_total")
    if isinstance(bm, (int,float)) and isinstance(tm, (int,float)) and isinstance(btot, (int,float)):
        if abs(bm * tm - btot) <= max(1.0, 0.01 * btot):
            score += 0.2; reasons.append("math_consistent")

    # Currency & tax-basis present
    if parsed.get("currency") in {"EUR","USD","GBP"}:
        score += 0.1; reasons.append("currency_ok")
    if parsed.get("tax_basis") in {"HT","TTC"}:
        score += 0.05; reasons.append("tax_basis_ok")

    # No obvious ambiguity
    ev_text = " ".join(filter(None, [
        parsed.get("evidence_base",""),
        parsed.get("evidence_options",""),
        parsed.get("variable_rates_summary","")
    ])).lower()
    if "nn €" not in ev_text and "nn eur" not in ev_text:
        score += 0.05; reasons.append("no_nn_prices")

    # Clamp 0..1
    return min(1.0, round(score, 2)), reasons

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

def build_response_id(text):
    stem = Path(text).stem                        # drop extension
    base = re.split(r'-(?:CG|CP|CONTRAT-CADRE|CONTRAT-SOUSCRIPTION)|_gcr_contrat-de-souscription|__contrat_cadre_saas\b',
                     stem, 1, flags=re.IGNORECASE)[0]
    return base 


#TRuncation chat gpt
from typing import Optional, Tuple, List

ANNEX_KEYWORDS = ["ANNEXE", "ANNEXES", "ANNEX", "APPENDIX", "APPENDICE"]
SIGNATURE_HINTS = [
    "lu et approuvé", "lu et approuve", "signature", "signé par", "signataire",
    "ne lie pas les parties", "merci de parapher", "does not bind the parties",
    "please initial each page"
]

def _lower(s: str) -> str:
    return s.lower()

def _upper(s: str) -> str:
    return s.upper()

def _build_line_index(text: str) -> List[int]:
    """Return start char index of each line in `text`."""
    idxs, pos = [0], 0
    for ch in text:
        pos += 1
        if ch == "\n":
            idxs.append(pos)
    return idxs

def _first_signature_pos(text: str) -> Optional[int]:
    low = _lower(text)
    hits = [low.find(h) for h in SIGNATURE_HINTS]
    hits = [p for p in hits if p != -1]
    return min(hits) if hits else None

def _is_probably_heading(line: str) -> bool:
    """
    Decide if a single line looks like an ANNEX heading, without regex.
    Rules (all cheap checks):
      - begins with one of the keywords (case-insensitive)
      - short-ish line (<= 120 chars)
      - mostly uppercase / digits / punctuation (i.e., not a sentence)
      - optional number or punctuation immediately after the keyword is fine
      - preferably surrounded by blank lines (checked by caller)
    """
    raw = line.strip()
    if not raw or len(raw) > 120:  # too long or empty
        return False

    # must start with an annex keyword
    up = _upper(raw)
    match = None
    for kw in ANNEX_KEYWORDS:
        if up.startswith(kw):
            match = kw
            break
    if not match:
        return False

    # if there is extra text after the keyword, allow things like:
    # "ANNEXE 1", "ANNEXE N° 2", "ANNEXES:", "APPENDIX 3 - SLA"
    tail = raw[len(match):].lstrip()
    if tail:
        ok_starts = ("N", "NO", "N°", "Nº", "1","2","3","4","5","6","7","8","9","0",":","-","–",".")
        if not tail.upper().startswith(ok_starts):
            # still allow a brief uppercase title like "SLA"
            # check lowercase ratio: if many lowercase letters, likely not a heading
            lower_count = sum(c.islower() for c in tail)
            total_letters = sum(c.isalpha() for c in tail)
            if total_letters and (lower_count / total_letters) > 0.40:
                return False

    return True

def find_annex_cut_index_plain(
    text: str,
    min_fraction: float = 0.45,        # only consider candidates after ~45% of the doc
    require_after_signature: bool = True,
    require_blank_context: bool = True  # require a blank line before or after the heading
) -> Tuple[Optional[int], str]:
    n = len(text)
    if n < 2000:
        return None, "Document too short; skip truncation."

    # decide where we start scanning
    sig_pos = _first_signature_pos(text)
    start_pos = int(n * min_fraction)
    if require_after_signature and sig_pos is not None:
        start_pos = max(start_pos, sig_pos)

    # line-based scan from start_pos
    lines = text.splitlines()
    line_starts = _build_line_index(text)

    # locate the first line index whose start >= start_pos
    start_line_idx = 0
    while start_line_idx < len(line_starts) and line_starts[start_line_idx] < start_pos:
        start_line_idx += 1

    # pass 1: strict scan
    for i in range(start_line_idx, len(lines)):
        line = lines[i]
        if _is_probably_heading(line):
            if require_blank_context:
                before_blank = (i == 0) or (lines[i-1].strip() == "")
                after_blank  = (i+1 >= len(lines)) or (lines[i+1].strip() == "")
                if not (before_blank or after_blank):
                    continue
            return line_starts[i], "Annex heading after threshold/signature."

    # pass 2: relaxed fallback — accept any heading if it's very late (>60%)
    late_threshold = int(n * 0.60)
    for i, line in enumerate(lines):
        pos = line_starts[i]
        if pos < late_threshold:
            continue
        if _is_probably_heading(line):
            return pos, "Late annex heading (>60%) accepted."

    return None, "No safe annex heading found."

def truncate_after_annex_plain(text: str) -> str:
    cut, reason = find_annex_cut_index_plain(text)
    print(reason)
    # print(reason)  # optional logging
    return text if cut is None else text[:cut]