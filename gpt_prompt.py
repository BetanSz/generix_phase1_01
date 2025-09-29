import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json




financial_prompt = """
You extract ONLY the financial and billing information from the provided CONTEXT. CONTEXT will include two documents:
- CG = Conditions Générales (cadre)
- CP = Conditions Particulières (souscription)

Precedence:
- If CP specifies a value, CP overrides CG.
- If CP is silent, fall back to CG.
- If both are silent/ambiguous, set null.
- Include products even if free/included (e.g., SLA); they still get a row.

Main Objectives:
- Your main objective is to identify the products present in the contract and recuperate the items defined in the Scope to extract.
- Keep original language of quotes (FR/EN). Output currency as ISO (EUR, USD, GBP, CHF, CAD, AUD, JPY). No conversions.
- Products & rows: Create exactly one product row for each line in CP sections, possibly found in “Abonnement …” and “Services associés/Options”. 
Include lines marked Inclus/Gratuit/Compris with is_included=true and price_amount=null.
- If a value is not present or unclear, set null. Do not guess. Do not compute totals.
- If the "Niveau de Service (SLA)" is present, add it as an additional product including the code. Most details about this product will remain empty

The fields to extract are the following:

* Contract / affair (repeat on every product row)
- company_name (string) — Client legal name from CP “Raison sociale du Client”. If absent, fall back to CG; else null.
- numero_de_contrat (number|null)- The contract number, which usually appear the the begining of the file under CONTRAT CADRE DE REFERENCE or OPPORTUNITE.
- reconduction_tacite (bool|null) - Find if the contract has tacite or automatic reconduction, meaning it will renew itself unless stipulated otherwise.
This information is by default in the GC, and sometimes it's changed in the CP. Awnser Yes or NO.
- devise_de_facturation (enum: EUR, USD, GBP, CHF, CAD, AUD, JPY) — From CP “Devise de facturation”; fall back to CG.
- tax_basis (HT/TTC|null) — If explicitly shown near prices/totals. Never infer.
- signature_date_cg (date|null) — Signature date of CG, if present.
- signature_date_cp (date|null) — Signature date of CP, if present.
- service_start_date (string date|null) — Start date of services if a concrete date is written. Do not invent.
- billing_start_date (string date|null) — If a specific billing start date is written. If the start is an event (e.g.,procede verbal: PV VABF), leave billing_start_date null and set debut_facturation.
- debut_facturation (string|null) — Event that triggers consumptions billing start (e.g., "PV VABF").
- duree_de_service (number or string|null) — Numeric duration in months or "indeterminé". If possible read the CP “Durée des Services …” line.
Put the numeric into duree_de_service and any remainder (e.g., “+ prorata de la période en cours”) into duree_de_service_notes. If absent in CP, fallback to CG; else null.
- duree_de_service_notes (string|null) — Any non-numeric tail near duree_de_service data (e.g., "+ prorata de la période en cours").
- date_end_of_contract (number|null) - this is a derived quantity: it's debut_facturation + duree_de_service. Note that debut_facturation is usually a date
and duree_de_service is usually in months. If the contract if of duree indeterminé or has reconduction_tacite=True then there is no end to the contract.
Only in this case put the year 31 dec 2099. Otherwsie, if any of the two required debut_facturation or duree_de_service is unknwon, put "unknown".
- term_mode (À échoir, Échu or null) — Billing mode for base subscription, possibly present in the “Terme” column.
For overconsumption lines, set overconsumption_term_mode accordingly.

* Product identification
- product_name (string, required) — Line label (“Libellé”) in CP pricing sections.
- product_code (string|null) — “Code” in the same row if present. Put only the code number, any additional description belongs to product_name.
- is_included (boolean, required) — True when the row shows Inclus/Gratuit/Compris/0; then set price_unitaire=null (or 0 only if literally “0”).
- price_unitaire (number|null) — Take the unitary price cell on the same row (normalize FR numbers) if possible.
If the cell is “Inclus/Gratuit/Compris/0”, set is_included=true and price_unitaire=null (or 0 if explicitly “0”).
- quantity (number|null) — amount of units of each service, possibly comming from the “Quantité” column of the product table.
It's usally an integer number (01, 02, ..) expressing the a amount of served items or values like 10000, 15000, expressing amount of factures.
Si absente → null.
- loyer (number|null) — This is the final price of a product, usually in the form of price_unitaire per quantity.
- loyer_facturation (number|null) — This is a calculated magnitude. Is the loyer at facturation time. For example if the loyer is mensuel and the
facturation time is trimestriel, loyer_facturation = loyer * 3. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula.
Also note that without loyer_periodicity it is not possible to calculate this dervied magntiude, and thus leave this colums as "unknown".
- loyer_annuele (number|null) — This is a calculated magnitude. Is the loyer at the end of the year. For example if the loyer is mensuel then
loyer_facturation = loyer * 12. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula
Also note that without loyer_periodicity it is not possible to calculate this dervied magntiude, and thus leave this colums as "unknown".
- loyer_periodicity (enum: monthly | quarterly | annual | other | null) — Cadence attached to the price row (e.g., “Loyer mensuel”). If not stated on that row,
 leave null. Do not copy billing cadence here.
- one_shot_service (bool|null) — True if one shot product, payed only once, if explicitly listed. Otherwise False
- bon_de_command (bool|null) - If the pourchase number (bon commande) appears in the contract. Binary value (Yes/No)

* Usage / surconsommation
- usage_overconsumption_price (number|null) — Unit price for overconsumption only if shown.
- usage_overconsumption_periodicity (enum: Mensuelle|Trimestrielle|Annuelle|Autre|null) — Frequency of overconsumption calculation (how often surconsommation is computed), 
usually stated next to the overconsumption price.
- usage_term_mode (enum or null) — Term mode specifically for included/usage if explicitly stated.
- overconsumption_term_mode (enum or null) — Term mode specifically for overconsumption (often Échu). Only set if explicit.
- usage_notes (string|null) — Notes about how usage/overconsumption is measured or charged (tiers/thresholds, proration, aggregation scope, carryover,
 rounding, exclusions, caps). Keep original language (FR/EN), ≤160 chars, strip line breaks/spaces, and don't repeat info already captured in structured fields.
 If nothing explicit → null.

* Facturation and payment modes
- billing_frequency (e.g. Trimestrielle, Annuelle) — Preferently from CP “Modalités de facturation” checkbox, otherwise from CG.
Note: Different from loyer_periodicity. A product can have Loyer mensuel but invoices are issued Trimestrielle.
- payment_methods (array of enums: virement | prelevement | cheque | other) — Only the checked ☒ methods. Do not include unchecked.
If additional details are present such as “A 45 jours date de facture” add them in payment_terms. Note that the SOUSCRIPTION contract overwrites the CADRE contract, use the latter.
If price_amount is "not applicable" then put the payment_methods also to "not applicable".
- payment_terms (string|null) — Delay with respect to billing in which the client must pay. Short text like “A 45 jours date de facture”.
- billing_modality_notes (string|null) — Any extra notes you need to preserve.

* Revalorisation
- reval_method (enum: fixed_rate | index_formula | textual | null) — From CG/CP.
- reval_rate_per (number|null) — Numeric rate when fixed. Otherwise null.
- reval_formula (string|null) — Formula/text if index-based or complex. Possibly using Syntec and Energy values. Otherwise null.
- reval_compute_when (string|null) — When it is calculated (e.g., “annuellement”).
- reval_apply_when (string|null) — The date in which it is applied (e.g., “le 1er janvier”).
- reval_apply_from (string|null) — The date (usually year) from wich the revalorisation takes effect (start being applied).
- reval_source (enum: CG | CP | null) — Where the rule came from.

* Evidence (short quotes ≤100 chars; French; no ellipses)
- evidence_product / evidence_price / evidence_payment_methods / evidence_usage / evidence_revalorization / evidence_billing / evidence_dates / evidence_company (string|null) — 
- Concise quotes taken from the same row/box that justified the value for each case. Put reference [CG] or [CP] from which contract was obtained and page number. Replace internal newlines with spaces.
- evidence_price — Short quote showing “Prix unitaire” times "quantity" = “Loyer mensuel” if available for context.

* Confidence (0-1; null if the field is null)
- confidence_price / confidence_usage / confidence_revalorization / confidence_billing / confidence_dates / confidence_company (number|null)
- Produce a float score in [0,1] based on how confident are the obtained values.
- Positive influence of score: explicitness & proximity, clear evidence in CP.
- Negative influence of socre: contradictions or incertinty within the document, missing data in document, conflict between the CG and CP, ambiguous wording, conflicting figures without clear precedence, inference from distant headers only, obvious OCR garbling.


Output:
- When filling tool arguments, do not include raw newlines inside strings; replace internal newlines with spaces or “\n”.
- Return an array of product rows via the tool. Each row duplicates the shared affair-level fields (company, dates, currency, etc.) for that product.
"""

tools = [{
    "type": "function",
    "function": {
        "name": "record_products",
        "description": "Return per-product financial/billing rows with CG/CP precedence applied.",
        "parameters": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            # --- Affair / company ---
                            "affair_id": { "type": ["string","null"] },
                            "company_name": { "type": ["string","null"] },
                            "numero_de_contrat": { "type": ["number","null"] },
                            "reconduction_tacite": { "type": ["boolean","null"] },
                            
                            

                            # --- devise_de_facturation & tax ---
                            "devise_de_facturation": { "type": "string", "enum": ["EUR","USD","GBP","CHF","CAD","AUD","JPY"] },
                            "tax_basis": { "type": ["string","null"], "enum": ["HT","TTC", "unknown"] },

                            # --- Dates & term ---
                            "service_start_date": { "type": ["string","null"] },
                            "billing_start_date": { "type": ["string","null"] },
                            "debut_facturation": { "type": ["string","null"] },
                            "signature_date_cg": { "type": ["string","null"] },
                            "signature_date_cp": { "type": ["string","null"] },
                            "duree_de_service": { "type": ["number","string","null"] },
                            "duree_de_service_notes":   { "type": ["string","null"] },
                            "date_end_of_contract":   { "type": ["string","number","null"] },
                            "term_mode": { "type": ["string","null"], "enum": ["À échoir","Échu", "unknown"] },

                            # --- Product identification ---
                            "product_name": { "type": "string" },
                            "product_code": { "type": ["string","null"] },
                            "is_included": { "type": "boolean" },

                            # --- Recurring base ---
                            "price_unitaire": { "type": ["number","null"] },
                            "quantity": { "type": ["number","null"] },
                            "loyer": { "type": ["number","null"] },
                            "loyer_facturation": { "type": ["number","null"] },
                            "loyer_annuele": { "type": ["number","null"] },
                            
                            
                            "loyer_periodicity": { "type": ["string","null"], "enum": ["Mensuelle","Trimestrielle","Annuelle","Autre", "unknown"] },

                            # --- One-time ---
                            "one_shot_service": { "type": ["boolean"] },
                            "bon_de_command": { "type": ["boolean"] },
                            

                            # --- Usage / consumption ---
                            "usage_overconsumption_price": { "type": ["number","null"] },
                            "usage_overconsumption_periodicity": { "type": ["string","null"], "enum": ["Mensuelle","Trimestrielle","Annuelle","Autre", "unknown"] },
                            "usage_notes": { "type": ["string","null"] },
                            "usage_term_mode": { "type": ["string","null"], "enum": ["À échoir","Échu", "unknown"] },  
                            "overconsumption_term_mode": { "type": ["string","null"], "enum": ["À échoir","Échu", "unknown"] },

                            # --- Revalorization ---
                            "reval_method": { "type": ["string","null"], "enum": ["fixed_rate","index_formula","textual", "unknown"] },
                            "reval_rate_per": { "type": ["number","null"] },
                            "reval_formula": { "type": ["string","null"] },
                            "reval_compute_when": { "type": ["string","null"] },
                            "reval_apply_when": { "type": ["string","null"] },
                            "reval_apply_from": { "type": ["string","null"] },
                            "reval_source": { "type": ["string","null"], "enum": ["CG","CP", "unknown"] },

                            # --- Modalities ---
                            "billing_frequency": { "type": ["string","null"], "enum": ["Mensuelle","Trimestrielle","Annuelle","Autre", "unknown"] },
                            "payment_methods": { "type": ["array","null"], "items": { "type": "string", "enum": ["virement","prelevement","cheque","portal","other"] } },
                            "payment_terms": { "type": ["string","null"] },
                            "billing_modality_notes": { "type": ["string","null"] },

                            # --- Evidence (short quotes ≤120 chars) ---
                            "evidence_product": { "type": ["string","null"] },
                            "evidence_price": { "type": ["string","null"] },
                            "evidence_usage": { "type": ["string","null"] },
                            "evidence_revalorization": { "type": ["string","null"] },
                            "evidence_billing": { "type": ["string","null"] },
                            "evidence_dates": { "type": ["string","null"] },
                            "evidence_company": { "type": ["string","null"] },
                            "evidence_payment_methods": { "type": ["string","null"] },
                            

                            # --- Confidences (0–1) ---
                            "confidence_price": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_usage": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_revalorization": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_billing": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_dates": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_company": { "type": ["number","null"], "minimum": 0, "maximum": 1 }
                        },
                        "required": ["product_name", "is_included", "devise_de_facturation"]
                    }
                }
            },
            "required": ["products"]
        }
    }
}]