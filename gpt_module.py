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