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
import pandas as pd
import json

def get_avenant_delta(client, delta_tool, delta_prompt, prior_state: dict, avenant_text: str):
    messages = [
        {"role":"system","content": delta_prompt},
        {"role":"user","content": f"PRIOR_STATE:\n{prior_state}\n\nAVENANT TEXT:\n{avenant_text}\n\nReturn deltas via the tool."}
    ]
    resp = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        tools=[delta_tool],
        tool_choice="auto",
        temperature=0.0,
        max_tokens=4000
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    return json.loads(tool_call.function.arguments)

delta_prompt = """
You are a contract delta extractor.

INPUTS
1) PRIOR_STATE (JSON) — a list of product rows previously extracted from CP and earlier AVENANTS.
   - Treat "null" (string), empty strings, and JSON null as missing.
   - Columns may include many fields; only a subset are relevant for defaults.
   - Rows can include CP and multiple AVs across time.

2) AVENANT TEXT — the digitized content for exactly one AVENANT.

GOAL
Return ONLY the changes (deltas) that this AVENANT introduces relative to the latest known state
BEFORE this AVENANT. Focus on default / non-price conditions (see DEFAULT_KEYS).
Do not compute totals and do not restate unchanged values as fields.
If the only difference vs baseline is price/quantity/total, set action="relist" and fields={} (pricing is handled elsewhere).

BASELINE SELECTION (very important)
- Infer this AVENANT’s signature date from the AVENANT TEXT if present; if absent, assume it follows
  all rows already in PRIOR_STATE.
- For each product identity (see PRODUCT IDENTITY), choose the baseline row as the latest row in
  PRIOR_STATE with signature_date_any < current AVENANT signature date (if dates exist). If dates are
  missing, prefer AV rows over CP and break ties by the last occurrence.
- Compare the AVENANT TEXT to that baseline to determine what changed.

WHAT COUNTS AS A “CHANGE”
- A newly stated default that was previously unknown.
- A modification of an existing default.
- An explicit cancellation/voiding (set to null).
- A product explicitly re-listed with no change (use action="relist" and fields={} so the timeline stays complete).

DO NOT INCLUDE IN fields
- Any price-related keys (price_unitaire, loyer, loyer_periodicity, totals, etc.).
- Anything you cannot tie to this AVENANT (if unsure, omit the key).

DEFAULT_KEYS (examples; not exhaustive)
billing_frequency, payment_methods, payment_terms, billing_modality_notes,
term_mode,
usage_overconsumption_price, usage_overconsumption_periodicity,
usage_term_mode, overconsumption_term_mode, usage_notes,
reval_method, reval_rate_per, reval_formula,
reval_compute_when, reval_apply_when, reval_apply_from, reval_source,
devise_de_facturation, reconduction_tacite, duree_de_service, duree_de_service_notes.

PRODUCT IDENTITY
- input_name: raw label as written in the AVENANT.
- canonical_family: a coarse bucket such as: option | support | otc | volume | application | third-party | other.
  (Pick what best fits; do not assume WMS/KPI only.)
- canonical_label: a short, stable name ≤40 chars that stays consistent across wording drift.
- canonical_id: slug of canonical_label (lowercase, no accents, spaces→“-”, keep only [a-z0-9-]).
- period_tag: only when the AV clearly names a specific commitment period (e.g., "2017 S2", "2017 T3").
- applies_from: set to this AVENANT’s signature_date_av for each product change.

MONTHLY TOTAL ON THIS AVENANT
- If the AVENANT explicitly states a monthly total (e.g., “Total abonnement mensuel …”), put the numeric value
  in avenant.monthly_total_explicit and a short quote in monthly_total_evidence.
- Normalize numbers: strip spaces/thousand separators; emit a plain number (e.g., 10 534 € → 10534).
- Prefer avenant.avenant_number as an integer if unambiguous; otherwise a string.
- Do NOT compute a total here if it is not explicitly stated.

EVIDENCE
- For any changed field or for monthly_total_explicit, include a short (≤80 chars) quote from this AVENANT
  in the relevant evidence slot: price / usage / billing / revalorisation / other.
- Use compact tags like [AV p2] if page hints exist. One short span per evidence slot.

OUTPUT
- Return only via the tool `record_contract_delta`.
- Be concise and consistent. If unsure about a value, omit that key from fields (do not guess).
"""

delta_tool = {
    "type": "function",
    "function": {
        "name": "record_contract_delta",
        "description": "Return ONLY the deltas introduced by this AVENANT versus the provided PRIOR_STATE.",
        "parameters": {
            "type": "object",
            "properties": {
                "avenant": {
                    "type":"object",
                    "properties": {
                        "avenant_number": {"type":["integer","string","null"]},
                        "signature_date_av": {"type":["string","null"], "description":"YYYY-MM-DD if present, else null"},
                        "monthly_total_explicit": {"type":["number","null"], "description":"Total abonnement mensuel if explicitly stated in this AV; else null"},
                        "monthly_total_evidence": {"type":["string","null"]}
                    },
                    "required": []
                },
                "product_changes": {
                    "type": "array",
                    "items": {
                        "type":"object",
                        "properties": {
                            "input_name": {"type":"string", "description":"Raw product name as seen in AV text/table"},
                            "canonical_family": {"type":"string", "description":"coarse bucket, e.g. wms|kpi|streamserve|volume-wms|otc|support|option|other"},
                            "canonical_label": {"type":"string", "description":"≤40 chars, stable across wording drift"},
                            "period_tag": {"type":"string", "description":"only for volume rows, e.g. '2017 S2' or '2017 T3'", "default":""},
                            "action": {"type":"string", "enum":["add","modify","remove","relist"], "description":"relist = unchanged but explicitly restated here"},
                            "fields": {
                                "type":"object",
                                "description":"Only put keys that change vs PRIOR_STATE, or keys that are newly set. Use value=null to explicitly clear.",
                                "additionalProperties": True
                            },
                            "notes": {"type":["string","null"], "description":"≤120 chars, optional summary of the change"},
                            "evidence": {
                                "type":"object",
                                "properties": {
                                    "price": {"type":["string","null"]},
                                    "usage": {"type":["string","null"]},
                                    "billing": {"type":["string","null"]},
                                    "revalorisation": {"type":["string","null"]},
                                    "other": {"type":["string","null"]}
                                }
                            }
                        },
                        "required": ["input_name","canonical_family","canonical_label","action","fields"]
                    }
                },
                "global_notes": {"type":["string","null"]}
            },
            "required": ["product_changes"]
        }
    }
}

DEFAULT_KEYS = [
    "billing_frequency","payment_methods","payment_terms","billing_modality_notes",
    "term_mode",
    "usage_overconsumption_price","usage_overconsumption_periodicity",
    "usage_term_mode","overconsumption_term_mode","usage_notes",
    "reval_method","reval_rate_per","reval_formula",
    "reval_compute_when","reval_apply_when","reval_apply_from","reval_source",
    "devise_de_facturation","reconduction_tacite","duree_de_service","duree_de_service_notes"
]

from datetime import date

def apply_delta_to_state(delta, state, monthly_totals):
    av_meta = delta.get("avenant", {}) or {}
    av_date = av_meta.get("signature_date_av")  # keep as string if you prefer

    # monthly total (optional)
    mt = av_meta.get("monthly_total_explicit")
    if mt is not None:
        monthly_totals.append({"applies_from": av_date, "total": mt})

    # product changes
    for ch in delta.get("product_changes", []):
        cid = ch.get("canonical_id") or slugify(ch.get("canonical_label", ch.get("input_name","unknown")))
        lab = ch.get("canonical_label", "")
        action = ch.get("action")
        fields = ch.get("fields", {}) or {}

        if cid not in state:
            state[cid] = {"canonical_label": lab, "last_update": None}
            for k in DEFAULT_KEYS:
                state[cid].setdefault(k, None)

        if action in ("add","modify"):
            for k, v in fields.items():
                if k in DEFAULT_KEYS:
                    state[cid][k] = v
            state[cid]["canonical_label"] = lab or state[cid]["canonical_label"]
            state[cid]["last_update"] = av_date

        elif action == "remove":
            # if specific keys are listed, null them; else leave as-is
            for k in fields.keys():
                if k in DEFAULT_KEYS:
                    state[cid][k] = None
            state[cid]["last_update"] = av_date

        # relist -> no change
    return state, monthly_totals

def enrich_rows_with_defaults(df_rows, state, av_signature_date):
    # Prefer existing canonical_id column; else derive from product_name
    if "canonical_id" not in df_rows.columns:
        df_rows["canonical_id"] = df_rows["product_name"].fillna("").map(slugify)

    # Normalize "null" to actual NaN for easy fill
    df_rows = df_rows.replace("null", pd.NA)

    for cid, sub in df_rows.groupby("canonical_id"):
        defaults = state.get(cid, {})
        if not defaults:
            continue
        for key in DEFAULT_KEYS:
            if key in df_rows.columns:
                mask = sub[key].isna()
                if mask.any():
                    df_rows.loc[sub.index[mask], key] = defaults.get(key, pd.NA)

    # If you recorded an AV monthly total, propagate it to recurring rows
    # (You already know how to detect one-shot/volume rows.)
    return df_rows