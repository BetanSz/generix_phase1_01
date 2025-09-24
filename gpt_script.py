"""
pip install "azure-ai-formrecognizer>=3.3.0,<4"
pip install openai
pip install azure-search-documents 
pip install ipython
pip install azure-storage-blob
pip install azure-cosmos
pip install fastapi uvicorn
"""
import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from clients import cosmos_digitaliezd, client_oai
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

items = cosmos_digitaliezd.read_all_items(max_item_count=100)
for i, doc in enumerate(items, start=1):
    print(i, doc["id"]) #, doc.get("blob_path")

doc_id = "M_cafe_mao_c_010825-CAFE-MEO-202307-150831-BDC-PRESTATIONS-EDI.pdf" #works
doc_id = "M_canon_europe_a_CONTRAT-TOD-CANON.pdf" #works
doc_id = "M_caloteries_b_Calottiers-201706-058931.pdf"
doc = cosmos_digitaliezd.read_item(item=doc_id, partition_key=doc_id)
print(doc["id"], doc.get("blob_path"), doc.get("page_count"))
doc_content = doc.get("content", "")
print(doc_content[:100])  # preview first 500 chars

financial_prompt_1 = """
3) Totals:
   - base_monthly_mandatory = sum of mandatory monthly fees (exclude options/usage).
   - base_term_mandatory_total = base_monthly_mandatory × term_months (if term known).
   - optional_monthly_total = sum of monthly optional items explicitly marked OPTION/optional; if none, 0.
   - optional_term_total = optional_monthly_total × term_months (if term known).
   - overall_min_total = base_term_mandatory_total.
   - overall_max_total = base_term_mandatory_total + optional_term_total (when both known).
"""
financial_prompt_2 = """
3) Recurring vs one-time:
   - Identify the MAIN recurring base fee (if any) as:
       base_recurring_amount  (numeric)
       base_recurring_period  ∈ {monthly, quarterly, annual, other}
     Examples: “1 095 € / mois”, “12 000 € / an”, “3 000 € / trimestre”.
   - Identify BASE one-time fees (mandatory, included in the base scope) as:
       base_one_time_total (numeric; sum of mandatory one-time items).
   - Identify OPTIONAL recurring items (explicitly marked OPTION/optional) as:
       optional_recurring_amount  (sum of option monthly/quarterly/annual)
       optional_recurring_period  ∈ {monthly, quarterly, annual, other}
   - Identify OPTIONAL one-time items (sum as optional_one_time_total).

4) Computing overall bounds (only when math is well-defined):
   - If term_months is known and base_recurring_amount/period is known:
       recurring_months_per_period = {monthly:1, quarterly:3, annual:12, other: null}
       base_term_recurring_total = base_recurring_amount × (term_months / months_per_period)
     (Round to 2 decimals; if period “other” or division isn’t integral, set total=null.)
   - overall_min_total = base_term_recurring_total (if computed) + base_one_time_total (if any).
   - If both term_months and optional_recurring are known:
       optional_term_recurring_total = optional_recurring_amount × (term_months / months_per_period)
       overall_max_total = overall_min_total + optional_term_recurring_total + optional_one_time_total
     (If any component missing/ambiguous, set overall_max_total=null.)
"""
financial_promp2use = financial_prompt_2


system_msg = textwrap.dedent(f"""
You extract the financial situation of the contract ONLY from the provided CONTEXT.

Focus:
- Prioritize financials (amounts, totals, term).
- Company and dates are secondary but required if present.
- Ignore non-financial content (technical text, vendor marketing, indices, penalties, schedules like 40/40/20).
                             
Priority: If there is any trade-off, prioritize correctness of financial totals and term over company and dates.

Rules:
1) Company (CLIENT, not vendor):
   - Accept ONLY names next to client labels such as:
     “Dénomination sociale du client”, “Dénomination (client)”, “Client”,
     “Adresse de facturation (si différente)”.
   - If no such labeled line is present, set company_name = null.

2) Dates and term:
   - Extract start_date and end_date if stated (YYYY-MM-DD when possible).
   - Extract term_months if stated (e.g., “36 mois”). If only term is present, set dates null.

{financial_promp2use}

4) Tax basis and currency:
   - Prefer “HT/TTC” markers near totals; currency from “€” → EUR, etc.
   - Output currency as ISO (e.g., EUR). Output numbers without separators (e.g., 1095.0).

5) Variable/usage rates:
   - Do NOT include in totals. Provide a short flat summary (≤ 400 chars) like:
     “Env suppl: 150 EUR/mo; Volume > forfait: 0.03 EUR/Ko; Partenaire RVA: 12 EUR…”

6) Evidence & confidence:
   - Provide short quotes (≤120 chars) as evidence for company, term, base, options, and each overall total.
   - Confidence 0.0–1.0. Heuristic:
        * If the amount comes from an explicit total line (e.g., "Total montant HT/TTC"), confidence ≥ 0.90.
        * If computed from clear monthly per term with both explicitly stated, confidence 0.75-0.9.
        * If inferred from partial info (e.g., unit price without term), confidence 0.4-0.7.
        * If ambiguous text ("NN €", conflicting figures), confidence ≤ 0.3.

7) If a value is not present, set it to null. Never invent VAT or convert currencies.
""").strip()

def T_string_nullable():
    return {"type": ["string", "null"]}

def T_number_nullable():
    return {"type": ["number", "null"]}

def T_bool():
    return {"type": "boolean"}

def T_date_nullable():
    # Loose date pattern (YYYY-MM or YYYY-MM-DD); keep nullable
    return {"type": ["string","null"]}

def T_string_enum_nullable(options):
    return {"type": ["string","null"], "enum": options + [None]}

tools = [{
  "type": "function",
  "function": {
    "name": "record_financials",
    "description": "Extract flat contract financials from CONTEXT.",
    "parameters": {
      "type": "object",
      "properties": {
        "company_name": T_string_nullable(),
        "start_date":   T_date_nullable(),
        "end_date":     T_date_nullable(),
        "term_months":  T_number_nullable(),

        "currency": {"type": "string", "enum": ["EUR","USD","GBP","CHF","CAD","AUD","JPY"]},
        "tax_basis": {"type": ["string","null"], "enum": ["HT","TTC", None]},

        "base_monthly_mandatory":    T_number_nullable(),
        "base_term_mandatory_total": T_number_nullable(),
        "optional_monthly_total":    T_number_nullable(),
        "optional_term_total":       T_number_nullable(),

        "overall_min_total":         T_number_nullable(),   # required (see below)
        "overall_max_total":         T_number_nullable(),   # optional

        "has_variable_rates":        T_bool(),
        "variable_rates_summary":    T_string_nullable(),

        "evidence_company":          T_string_nullable(),
        "evidence_term":             T_string_nullable(),
        "evidence_base":             T_string_nullable(),
        "evidence_options":          T_string_nullable(),
        "evidence_overall_min":      T_string_nullable(),
        "evidence_overall_max":      T_string_nullable(),

        "confidence_base":           T_number_nullable(),
        "confidence_options":        T_number_nullable(),
        "confidence_overall_min":    T_number_nullable(),
        "confidence_overall_max":    T_number_nullable()
      },
      "required": [
        "currency",
        "overall_min_total",
        "evidence_overall_min",
        "has_variable_rates"
      ],
      "additionalProperties": False
    }
  }
}]

user_question = "Extract the total cost of this contract."
embed()

messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": f"DOCUMENT CONTENT:\n\n{doc_content}\n\nQUESTION:\n{user_question}"}
]
# --- call Azure OpenAI (model = deployment name)
resp = client_oai.chat.completions.create(
    model="gpt-4.1",               # your deployment name from the portal
    messages=messages,
    tools=tools,
    tool_choice="auto",
    temperature=0.0,
    max_tokens=1000,
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

#answer = resp.choices[0].message.content
#print(answer)

tool_call = resp.choices[0].message.tool_calls[0]
data = json.loads(tool_call.function.arguments)
print(json.dumps(data, indent=2, ensure_ascii=False))
