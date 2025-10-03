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

delta_prompt = """

You are a delta extractor for WMS SaaS contracts.
INPUTS:
1) PRIOR_STATE (JSON) — a snapshot of known defaults per product (by name) BEFORE this AVENANT.
   - It may be empty or partial.
   - Keys typically include: billing_frequency, payment_methods, payment_terms, billing_modality_notes,
     term_mode, usage_overconsumption_*, usage_term_mode, overconsumption_term_mode, usage_notes,
     reval_method, reval_rate_per, reval_formula, reval_compute_when, reval_apply_when, reval_apply_from, reval_source,
     devise_de_facturation, reconduction_tacite, duree_de_service, duree_de_service_notes.
   - Price fields are not defaults; ignore them for propagation.
2) AVENANT TEXT — the digitized content for exactly one AVENANT.

YOUR TASK:
- Compare the AVENANT against PRIOR_STATE and output ONLY the changes introduced by this AVENANT.
- A “change” includes:
  • a newly stated default (not present before),
  • a modification of a prior default,
  • removal/explicit nullification,
  • product restated without change (mark action="relist" if clearly re-listed unchanged and useful for timeline completeness).
- Also capture an explicit “total abonnement mensuel” if present on this AVENANT (do not compute; if clearly absent, keep null).

PRODUCT IDENTITY:
- For each change, emit input_name and also a canonical identity:
  canonical_family ∈ { wms | kpi | streamserve | volume-wms | otc | support | option | other }.
  canonical_label = short stable label (≤40 chars).
  period_tag only for volume rows if the AV names a specific period (e.g., “2017 S2”, “2017 T3”).

WHAT TO PUT IN fields:
- Include ONLY keys whose value changes relative to PRIOR_STATE for that product, or new keys that become known.
- If the AV explicitly cancels/voids a default, set that key to null.
- Focus on default-type fields listed above. Do NOT put price_unitaire/loyer/loyer_periodicity here.
- If nothing changes but the product is explicitly re-listed, return action="relist" and fields={}.

EVIDENCE:
- For any change, include a short quote (≤80 chars) in the relevant evidence slot (price/usage/billing/revalorisation/other).
- Use compact tags like [AV p2] when possible. Keep one short span per evidence field.

OUTPUT:
- Return your result via the tool `record_contract_delta`.
- Be concise and consistent. If unsure about a value → do not include that key in fields.

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
