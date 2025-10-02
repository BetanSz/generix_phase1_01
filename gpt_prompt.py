import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json

annex_prompt = """
Your main objective is to find the line where the Annex of the document starts.
Annex tend to start after the signature of the contract. Examples of signatures:

le : 20/03/2015
Pour GENERIX :
Signé par :
Marc BOULON
Titre :
Directeur des Opérations
Supply Chain
Signature :
Lu et approuvé
M
Pour CULTURA - SOCULTUR SAS :
Signé par :
JC Gabillard

or

Date:
27/1/2017
For and on behalf of GENERIX:
Name and forename of authorized person:
Renaud Vadon
Title: VP Sales
For and on behalf of Airbus :
Name and forename of authorized person:
<figure>
Title:
1
@ AIRBUS
Signature:
</figure>

Digitally signed
by Jose Villajos
Serrano - SIG
Reason: I am
the approver of
this document
Date: 28/11/17
08:53:24 CET

Signature:
generix
group
Read and Approved

(Signature and stamp preceded by the handwritten entry "Read and Approved")
2 rue des Peupliers - BP 20158
59810 LESQUIN
Tél. : +33 (0)1 77 45 41 80
Fax : +33 (0)3 20 41 48 07
Slie : www.generixgroup.com
SIREN : 3// 619 150 - IVA · IR 88 37/ 619 150

As you can see it tends to have a date and a recall of the signing parties.
Then the annex starts. Typicaal Appendix or Annex title look like this:

# Appendix 1: Description of the GCI Invoice Manager On Demand service
# Annexe 1: Description du service GCS On Demand
<caption>Annexe 1: Niveaux de Services (SLA), pack fonctionnalités et options Les Niveaux de Services (SLA) proposés</caption>
# ANNEXE 2 : DESCRIPTION DU SERVICE GENERIX COLLABORATIVE REPLENISHMENT (GCR)

So in order to identify the Annex you need to:
1) Find the signature region, usually after product description and payment details.
2) After the signature region identify where the Annex start.
3) Provide in json the line where the annex start, the actual annex line and the context of that lines.
4) the context of that line is 5 lines upper and lower than the annex line.

If you can identify a single best annex heading, you MUST call tool report_annex_anchor
with: line_index (0-based), annex_line, and context (≈5 lines around the heading).
If no safe annex is found, DO NOT call the tool; answer: "no_annex_found".
"""

financial_prompt = """
You extract ONLY the financial and billing information from the provided CONTEXT. CONTEXT will include three document types, which compose a single contract:
- One CG = Conditions Générales (cadre): general default contract conditions.
- One CP = Conditions Particulières (souscription): specific client vdeefined contract conditions
- Possibly many AVENANTS: updates, improvments or modifications of the CP.
- Older contracts are before 2023.

* Precedence:
- If CP specifies a value, CP overrides CG.
- If CP is silent, fall back to CG.
- If all are silent/ambiguous, set null.
- Include products even if free/included (e.g., SLA); they still get a row.
- Treat each product present in the AVENANT section as separate products, even if they repeat with respect to the CP. 
Consider the information of each avenant to define the financial conditions therein.

* Main Objectives:
- Your main objective is to identify the products present in the contract and recuperate the items defined in the Scope to extract.
- Products & rows: Create one row per product as found in the CP (tables, bullets, or callouts) or AVENANTS.
Include items marked Inclus/Gratuit/Compris/0 with is_included=true and price_unitaire=null (or 0 only if literally “0”).
Do not create rows for totals/recaps; only for underlying items (i.e. products) that usually carry their own price.
- Create a product row for each product present in the avenant. For each one of these rows, data in the avenant overrides former CP information.
- Product description or code in the avenant may repeat a product already present in the CP. Keep all of them, as to preserve the chronological history
of the contract product changes in time. 
- If a value is not present or unclear, set null. Do not guess. Do not compute totals.
- Keep original language of quotes (FR/EN). Output currency as ISO (EUR, USD, GBP, CHF, CAD, AUD, JPY). No conversions.
- In case of doubt it's better to include a doubtous product instead of skipping it.

Note that the presence of avenants may imply having several rows for a single product type. Avenant history must be saved in the form of the product rows.
Order the rows chronologically using the signature date: first the products as defined in the CP and then the products as defined in the avenant.

* Contract structre:
- In newer contracts products are usually found in “Abonnement …” and “Services associés/Options”.
- In older contracts  products are usually found in "Prix, modalites de facturation et de reglement".
- In avenants products are usually found under "2 ARTICLE 5.2 - ABONNEMENT" or "Modifications de l'article 5.2 des Conditions Particulières du Contrat".

* How to identify products & prices:
- One row = one priced block. Create a product row whenever a description/label is directly tied to a price in the same line/cell/box or the
 immediately following short line.
- Valid blocks can be: table rows, bullet/paragraph lines with a nearby price, or bordered callouts.
- Ignore totals/recaps. Do not make rows for “Total / Sous-total / Récapitulatif / Total abonnement …”.
 Only record the underlying items that carry their own price. Do not aggregate across blocks: one row per priced block. If a block shows only a total,
   skip it and use the child items that carry their own prices.
- Price extraction. Take the closest amount to the block.
 Set tax_basis only if HT/TTC is shown next to that amount.
- Periodicity. Set loyer_periodicity from the local wording next to the price (e.g., mensuel/le, trimestriel/le, annuel/le).
 If not explicit on that block, leave null.
- One-time vs recurring. If the block says OTC / mise en œuvre / one-time / setup / frais initiaux,
 set one_shot_service=true and leave loyer_periodicity=null. Otherwise, treat as recurring.
- Usage/volume cases. If wording mentions volume / unité d'œuvre / palier / S1/S2 / dégressif /
 utilisateur supplémentaire, fill usage_* fields and summarize mechanics in usage_notes (≤100 chars). Keep loyer only if a flat fee exists on that block.
- Naming. product_name = the shortest clear label/heading for the block. Put any explicit numeric code on that block in product_code; otherwise null.
- Multi-line features. If many bullets describe one thing and one price is given, create one row. If multiple prices appear 
in separate sub-blocks, create one row per sub-block.
- Minimum rows sanity check. If the CP shows ≥2 priced blocks, you must output ≥2 rows (still ignore totals).
- Evidence. Quote the shortest nearby text: amount/periodicity for evidence_price; the label you used for product_name for evidence_product.
- Do not copy a contract "total" value into item rows. This magnitude can only be present in total_abbonement_mensuel.
- If a family/process line (e.g., “Warehouse Management System”, “Performance Indicators”) ends with “d'un montant forfaitaire mensuel total de : X €”, 
this IS the price of that product line. Only skip the final line like “Total abonnement aux Process métier”.
- If a cell contains several amounts (e.g., “1 550 € HT 200 € HT 150 € HT”), map each amount to the closest preceding labeled item in that block
 (e.g., WMS → 1 550, KPI → 200, Cloisonnement → 150) and emit one row per amount.

* How to identify overconsumption (surconsommation)
- How to indentify: if the nearby text mentions any of: dépassement, complément de consommation, surconsommation, 
au-delà de l'engagement, utilisateur supplémentaire / seat additionnel, palier, unité d'œuvre, S1/S2, dégressif.
- If the rule has no numeric price (e.g., “unité d'œuvre surcotée de 15% vs palier”):
    - usage_overconsumption_price = small text indicating the rule.
    - usage_overconsumption_periodicity = cadence explicitly stated near the rule (e.g., Mensuelle, Trimestrielle, Semestrielle, Annuelle).
    - If the cadence is clearly stated in an adjacent “modalités” block that obviously applies to this usage 
    (e.g., “les volumes dépassent… facturés semestriellement, terme échu”), you may use it; otherwise leave null.
- If a numeric unit price is given for excess (e.g., “utilisateur supplémentaire 10 € / mois”, “par transaction 0,05 €”):
    - usage_overconsumption_price = number
    - usage_overconsumption_periodicity = cadence in the same block (e.g., Mensuelle)
    - usage_term_mode if the block states it; else null
    - usage_notes = short label, e.g. "prix par utilisateur supplémentaire".

* How to handle avenants:
- Avenants are found after the CP. Each one is defined with the tags: start of the avenant "=== DOC: AVENANT/START ===" and
end of the avenant "=== DOC: AVENANT/END ===". Each of these must be treated independently.
- Each avenant creates additional product rows in sequential order, as defined by the signature date of the avenant;
do not overwrite CP rows, even if the product is the same. Do not omit unchanged prodcuts already present in the CP.
- If an avenant changes an already present product in any way, reflect the change in evidence_avenant following evidence guidelines.
- If an avenant shows a new monthly total, put it in total_abbonement_mensuel only on the avenant rows. Propagate the same total_abbonement_mensuel
 to ALL recurring rows from that avenant.
- If not changed by the avenant keep previous rules (e.g. usage, overconsumption) from the previous state of the contract, as defined
by the CP or the previous avenant. Consider the signature date to define the latest state of the contract.
- Order outputs by signature date (CP rows should come first, then avenants chronologically using their signature date).
- When an AVENANT shows products that also exist in the CP (even with the same price), repeat them as new rows for that AVENANT. Do not omit unchanged products.
- If a right column contains multiple euro amounts, pair them to the nearest preceding labeled anchors in the left column
 (e.g., WMS → 1 550; KPI → 200; Cloisonnement → 150). Emit one row per pair.

* How to handle Volume products (table decomposition):
- If the CP shows a “Pricing mensuel volumes” table with Year and S1/S2 columns,
    - EMIT ONE ROW PER PRICED SEMESTER CELL (e.g., 2015 S1, 2015 S2, 2016 S1, 2016 S2…).
    - product_name: "Abonnement volume <Famille> — <Année> <S1/S2>".
    - price_unitaire = that semester's amount; loyer = that same amount.
    - loyer_periodicity = Mensuelle; tax_basis from the same cell if present.
    - is_volume_product = true (because it's usage-based), BUT you must still fill loyer
    - since the table states an explicit monthly price for that commitment period.
    - Do NOT aggregate these; do NOT replace them with one generic “volume” row.

* Edge cases to consider:
- If reconduction_tacite=True, ignore duration/prorata and set date_end_of_contract="2099-12-31". 
- In evidence_date_end_of_contract, cite the reconduction clause.
- If the "Niveau de Service (SLA)" is present, add it as an additional product including the code. Most details about this product will remain empty.
- Specially in AVENANT parts of the contract, The phrase “d'un montant forfaitaire mensuel total de : X €” is not a recap when tied to a family/process;
 it's the price of that product line. Only the terminal line “Total abonnement…” is the recap to skip.

* Columns to emit (tool output schema).
- Emit one JSON object per product row that maps 1:1 to the record_products tool parameters below.
- Do not invent fields or keys. For each key, follow the definition exactly; if a value is not explicit on the relevant block, set null. 
- Duplicate affair-level fields on every row, many comming from the GC.

* Contract / affair (repeat on every product row)
- company_name (string) — Client legal name from CP “Raison sociale du Client”. If absent, fall back to CG; else null.
- numero_de_contrat (number|null)- The contract number, which usually appear the the begining of the file under CONTRAT CADRE DE REFERENCE or OPPORTUNITE.
- reconduction_tacite (bool|null) - Find if the contract has tacite or automatic reconduction, meaning it will renew itself unless stipulated otherwise.
This information is by default in the GC, and sometimes it's changed in the CP. Answer Yes or NO.
- devise_de_facturation (enum: EUR, USD, GBP, CHF, CAD, AUD, JPY) — From CP “Devise de facturation”; fall back to CG.
- tax_basis (HT/TTC|null) — If explicitly shown near prices/totals. Never infer.
- signature_date_cg (date|null) — Signature date of CG, if present. If an AVENANT date is present instead, put this to null.
- signature_date_cp (date|null) — Signature date of CP, if present. If an AVENANT date is present instead, put this to null.
- signature_date_av (date|null) — Signature date of AVENANT, if present.
- avenant_number (numeric|null) - If this part of the document is an AVENANT, put the number in this field.
- service_start_date (string date|null) — Start date of services if a concrete date is written. Do not invent. For example it maay be "prend effet à la date de signature.",
So the start date should be the signature of the document. This is usually the case for AVENANTS.
- debut_facturation (string|null) — Write a specific billing start date if available. If the start is an event (e.g.,procede verbal: PV VABF, GO), put that instead.
In a given contract, different products may have different billing start dates.
- duree_de_service (number or string|null) — Numeric duration in months or "indeterminé". If possible read the CP “Durée des Services …” line, if absent in CP, fallback to CG.
Any additional remainder such as (e.g., “+ prorata de la période en cours”) put into duree_de_service_notes. This value is "indeterminé" if the contract is of type
reconduction tacie, meaning it will automatically renew itself. This information is usually in the CG, found mostly in old contracts.
- duree_de_service_notes (string|null) — Any non-numeric tail near duree_de_service data (e.g., "+ prorata de la période en cours").
- date_end_of_contract (string|null) - This is a derived quantity, not present in the contract per se.
If reconduction_tacite=False, then it's the signature date + duree_de_service + prorata. The signature date is a date always present in the contract. 
duree_de_service is usually in months. prorata must be calculated as the difference in month between the signature date and the end of that year, in months.
Therefore, to calculate date_end_of_contract sum to the signature date the months of duree_de_service and prorata (if present).
If the contract is of duree "indetermine" (meaning that reconduction_tacite=True) then there is no end to the contract. In this case instead of 
the calculation put the date "31 dec 2099". If reconduction_tacite=False but duree_de_service is not available set it to "unknown".
Otherwsie, if any of the two required fields (signature date, duree_de_service) is unknwon and reconduction_tacite=False, put "unknown".
- term_mode (À échoir, Échu or null) — Billing mode for base subscription, possibly present in the “Terme” column.
For overconsumption lines, set overconsumption_term_mode accordingly.

* Product identification
- product_name (string, required) — Line label (“Libellé”) in CP pricing sections.
- product_code (string|null) — “Code” in the same row if present. Put only the code number, any additional description belongs to product_name.
Older contracts tend to not have the product code.
- is_included (boolean, required) — True when the row shows Inclus/Gratuit/Compris/0; then set price_unitaire=null (or 0 only if literally “0”).
- price_unitaire (number|null) — Take the unitary price cell on the same row  if possible.
If the cell is “Inclus/Gratuit/Compris/0”, set is_included=true and price_unitaire=null (or 0 if explicitly “0”).
- quantity (number|null) — amount of units of each service, possibly comming from the “Quantité” column of the product table.
It's usally an integer number (01, 02, ..) expressing the a amount of served items or values like 10000, 15000, expressing amount of factures.
Si absente → null.
- is_volume_product (boolean, required) — true only if the row's base price itself is
  defined by measured usage/tiers/paliers (volume d'activité, unités d'œuvre, S1/S2).
  If the row is a flat recurring fee with separate overconsumption terms (e.g., base
  200 €/mois + “utilisateur supplémentaire 10 €/mois”), set false on the base row and
  capture overage in usage_*.
- loyer (number|null) — Final price of the product for its own cadence (usually in the form of price_unitaire per quantity),
  regardless of periodicity. Example: if the row states “10 000 € par an”, then loyer=10000 and loyer_periodicity=Annuelle (also set loyer_annuele=10000).
  If one_shot_service=True, then set this to null, since it's a one time payment.
  When is_volume_product=true, leave this field as null (the loyer cannot be calculated without knowing the consumption).
- loyer_facturation (number|null) — This is a calculated magnitude. Is the loyer at facturation time. For example if the loyer is mensuel and the
facturation time is trimestriel, loyer_facturation = loyer * 3. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula.
Also note that without loyer_periodicity it is not possible to calculate this dervied magntiude, and thus leave this colums as "unknown".
When is_volume_product=true, leave this field as null (the loyer cannot be calculated without knowing the consumption).
If one_shot_service=True, then set this to null, since it's a one time payment.
- loyer_annuele (number|null) — This is a calculated magnitude. Is the loyer at the end of the year. For example if the loyer is mensuel then
loyer_facturation = loyer * 12. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula
Also note that without loyer_periodicity it is not possible to calculate this dervied magntiude, and thus leave this colums as "unknown".
When is_volume_product=true, leave this field as null (the loyer cannot be calculated without knowing the consumption).
If one_shot_service=True, then set this to null, since it's a one time payment.
- loyer_periodicity (enum: Mensuelle|Trimestrielle|Annuelle|null) — Set only if the same block states a cadence (e.g., Loyer mensuel). 
If cadence appears only in distant headers or elsewhere, leave null. Do not copy billing cadence here.
If one_shot_service=True, then set this to null, since it's a one time payment.
When is_volume_product=true, leave this field as null (the loyer cannot be calculated without knowing the consumption).
- total_abbonement_mensuel (number|null): the total value of the CP or AVENANT as the sum of all products having a loyer.
Only consider mensual values if present in the contract. This is an agregated quantity that has to be propagated within all rows of the
CP or each AVENANT. If an AVENANT shows a monthly total, set total_abbonement_mensuel to that value on all recurring rows from that AVENANT
 (not just the new option).
- one_shot_service (bool|null) — True if one shot product, payed only once, if explicitly listed. Otherwise False
- bon_de_command (bool|null) - If the pourchase number (bon commande) appears in the contract. Binary value (Yes/No)

* Usage / surconsommation
- usage_overconsumption_price (string|null) — Unit price for overconsumption only if shown.
- usage_overconsumption_periodicity (enum: Mensuelle|Trimestrielle|Semestrielle|Annuelle|Autre|null) — Frequency of overconsumption calculation 
(how often surconsommation is computed), usually stated next to the overconsumption price.
- usage_term_mode (enum or null) — Set only when an explicit term mode is stated
  for included/usage; otherwise null. Do not inherit the product billing term here.
- overconsumption_term_mode (enum or null) — Term mode specifically for overconsumption (often Échu). Only set if explicit.
- usage_notes (string|null) — Notes about how usage/overconsumption is measured or charged (tiers/thresholds, proration, aggregation scope, carryover,
 rounding, exclusions, caps). Keep original language (FR/EN), ≤160 chars, strip line breaks/spaces, and don't repeat info already captured in structured fields.
 If nothing explicit → null.

* Facturation and payment modes
- billing_frequency (string|null) — Preferently from CP “Modalités de facturation” checkbox, otherwise from CG. e.g. Trimestrielle, Annuelle.
Note: Different from loyer_periodicity. A product can have Loyer mensuel but invoices are issued Trimestrielle.
If one_shot_service=True, then set billing_frequency to null.
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

* Evidence
- Keep every evidence_* under 80 chars after whitespace collapse. If needed, shorten
  month names (e.g., “20/03/2015, 48m + prorata [CP p8]”). Keep it as short as possible you can summerize freely here.
- Evidence must come from the same block.
- evidence_product / evidence_price / evidence_payment_methods / evidence_usage / evidence_revalorization / evidence_billing / evidence_dates (string|null) — 
- Concise quotes taken from the same row/box that justified the value for each case. Put reference [CG] or [CP] from which contract was obtained and page number. Replace internal newlines with spaces.
- evidence_price — Short quote showing “Prix unitaire” times "quantity" = “Loyer mensuel” if available for context.
- evidence_date_end_of_contract: Write the referrence to the 3 dates that compose this derived quantity: signature date, duree_de_service and prorate (it found).
If reconduction_tacite=True, then put the reference to where this is stated.
- evidence_avenant: when a product has been modfied by an avenant (data comes from an avenant file, the product code is the same or if there's no
product code, then the product description is similar), write a very short summary detailing old costs versus new costs. If possible write the difference as well.
- Evidence must be a single, minimal span from the SAME block as the value.
- Max 80 characters after whitespace collapse. No full sentences, no boilerplate.
- Use compact tags of the source and page: [CP p12], [CG p3], [AV p2].
- evidence_product = shortest label you used as product_name.
- evidence_price = closest amount + local periodicity (e.g., “1 750 € HT mensuel”).
- evidence_payment_methods = Present the value as found in CP (if present) but also mention the one found in CG. Example "Virement [CP, p12] replacing prelevement [CG, p56]".
- If nothing explicit in that block ⇒ null.
- total_abbonement_mensuel_evidence: list the products included under this envelopping value. Do not use full names since it could be too long, make the
list short if possible. If product codes are available use those instead of the product name. After that write the explicit formula to 
arriving at this value for example, if 3 products having a loyer of 100, 150 and 200 are present, then wrtie (100+150+200=450).
Propagate this envelopping value as found in the CP or the AVENANT for all rows and product type therein (they should be the same for
each CP or each AVENANT). This is an agregated calculation.

* Confidence (0-1; null if the field is null)
- confidence_price / confidence_usage / confidence_revalorization / confidence_billing / confidence_dates / confidence_company (number|null)
- Produce a float score in [0,1] based on how confident are the obtained values.
- Positive influence of score: explicitness & proximity, clear evidence in CP.
- Negative influence of socre: contradictions or incertinty within the document, missing data in document, conflict between the CG and CP, ambiguous wording, conflicting figures without clear precedence, inference from distant headers only, obvious OCR garbling.
- confidence_avenant: avenant overrides a product already present in the contract or explictly defined a new product or engagment. Dates of avenants
are in the future with respect to the CP or CG. In general prices present in the avenant are higher than the original ones found in the contract.
Attribute a low confidence value if these conditions are not satisfied.

Output:
- When filling tool arguments, do not include raw newlines inside strings; replace internal newlines with spaces or “\n”.
- Return an array of product rows via the tool. Each row duplicates the shared affair-level fields (company, dates, currency, etc.) for that product.
- Emit all fields. For every product, include every property defined in the tool schema. If unknown, set null. Do not omit keys.
"""

#TODO: include this? what are their effect exactly
"""
Sanity checks:
- For each AVENANT pricing table, count numeric amounts excluding the very last “Total abonnement …”. You must output at least that many product
 rows from the AVENANT.
 - Minimum rows sanity check. If the CP shows ≥2 priced blocks, you must output ≥2 rows (still ignore totals).
 """

financial_tools = [{
    "type": "function",
    "function": {
        "name": "record_products",
        "description": "Return per-product financial/billing rows with CG/CP precedence applied and all avenants are appended.",
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
                            "debut_facturation": { "type": ["string","null"] },
                            "signature_date_cg": { "type": ["string","null"] },
                            "signature_date_cp": { "type": ["string","null"] },
                            "signature_date_av": { "type": ["string","null"] },
                            "avenant_number": { "type": ["number","null"] },
                            "duree_de_service": { "type": ["number","string","null"] },
                            "duree_de_service_notes":   { "type": ["string","null"] },
                            "date_end_of_contract":   { "type": ["string","null"] },
                            "term_mode": { "type": ["string","null"], "enum": ["À échoir","Échu", "unknown"] },

                            # --- Product identification ---
                            "product_name": { "type": "string" },
                            "product_code": { "type": ["string","null"] },
                            "is_included": { "type": "boolean" },

                            # --- Recurring base ---
                            "price_unitaire": { "type": ["number","null"] },
                            "quantity": { "type": ["number","null"] },
                            "is_volume_product": { "type": ["boolean","null"] },
                            "loyer": { "type": ["number","null"] },
                            "loyer_facturation": { "type": ["number","null"] },
                            "loyer_annuele": { "type": ["number","null"] },
                            "loyer_periodicity": { "type": ["string","null"], "enum": ["Mensuelle","Trimestrielle","Annuelle","Autre", "unknown"] },
                            "total_abbonement_mensuel": { "type": ["number","null"] },

                            # --- One-time ---
                            "one_shot_service": { "type": ["boolean"] },
                            "bon_de_command": { "type": ["boolean"] },
                            

                            # --- Usage / consumption ---
                            "usage_overconsumption_price": { "type": ["string","null"] },
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
                            "evidence_payment_methods": { "type": ["string","null"] },
                            "total_abbonement_mensuel_evidence": { "type": ["string","null"] },
                            "evidence_date_end_of_contract": { "type": ["string","null"] },
                            "evidence_avenant": { "type": ["string","null"] },
                            
                            # --- Confidences (0–1) ---
                            "confidence_price": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_usage": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_revalorization": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_billing": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_dates": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_company": { "type": ["number","null"], "minimum": 0, "maximum": 1 },
                            "confidence_avenant": { "type": ["number","null"], "minimum": 0, "maximum": 1 }
                            
                        },
                        "required": ["product_name", "is_included", "devise_de_facturation"]
                    }
                }
            },
            "required": ["products"]
        }
    }
}]

tools_annex = [
    {
        "type": "function",
        "function": {
            "name": "report_annex_anchor",
            "description": (
                "Return where the Annex/Appendix starts. "
                "Use 0-based line index in the *provided DOCUMENT CONTENT*. "
                "Context must be ~5 lines before and after the annex line."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "line_index": {
                        "type": "integer",
                        "description": "0-based index of the annex heading line in the input text split by \\n."
                    },
                    "annex_line": {
                        "type": "string",
                        "description": "The exact annex heading line, verbatim from the document."
                    },
                    "context": {
                        "type": "string",
                        "description": "Concise context: ~5 lines before and after the annex line, joined with \\n."
                    }
                },
                "required": ["line_index", "annex_line", "context"]
            }
        }
    }
]

col_order  = ['company_name', "numero_de_contrat" ,'signature_date_cg', 'signature_date_cp','signature_date_av','avenant_number', 'product_code', 'product_name',
              'duree_de_service',  'duree_de_service_notes', "date_end_of_contract" ,'reconduction_tacite','term_mode', 'billing_frequency', "bon_de_command" ,'payment_methods', 'payment_terms', "debut_facturation",
 'price_unitaire',"quantity","is_volume_product","loyer","loyer_facturation","loyer_annuele",'devise_de_facturation', 'loyer_periodicity', "total_abbonement_mensuel" ,'one_shot_service', 'tax_basis','is_included',
 'usage_overconsumption_price', 'usage_overconsumption_periodicity', 'usage_term_mode', 'overconsumption_term_mode', "usage_notes",
 'service_start_date', 'billing_modality_notes',
 'reval_method', 'reval_rate_per', 'reval_formula', 'reval_compute_when', 'reval_apply_when', "reval_apply_from",
       'reval_source',  
       'evidence_product', 'evidence_price', 'evidence_payment_methods','total_abbonement_mensuel_evidence', 'evidence_date_end_of_contract', "evidence_avenant",
       'evidence_usage', 'evidence_revalorization', 'evidence_billing',
       'evidence_dates', 'confidence_price',
       'confidence_usage', 'confidence_revalorization', 'confidence_billing',
       'confidence_dates', 'confidence_company', 'confidence_avenant'
       ]