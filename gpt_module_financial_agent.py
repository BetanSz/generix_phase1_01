import os, uuid
import os, re
import hashlib, datetime as dt
from IPython import embed
from pathlib import Path
import textwrap
import json


financial_prompt = """
# Main Objectives:
- Your main objective is to identify the products present in the contract and retrieve the items defined in the Scope to extract. This is mainly financial
information about the products, and other aspects of the contract.
- Products & rows: Create one row per product as found in the CP (tables, bullets, or callouts) or AVENANTS.
Include items marked Inclus/Gratuit/Compris/0 with is_included=true and price_unitaire=null (or 0 only if literally “0”).
- Do not create rows for totals/recaps; only for underlying items (i.e. products) that usually carry their own price.
- Create a product row for each product present in the avenant.
- Include products even if free/included. For example the product "Niveau de service (SLA)" or simply SLA tends to be included without at price, and
must olways be present in the output if retained by the client.
- Product description or code in the avenant may repeat a product already present in the CP. Keep all of them, as to preserve the chronological history
of the contract product changes in time. 
- If a value is not present or unclear, set to null. Do not guess.
- Keep original language of quotes (FR/EN). Output currency as ISO (EUR, USD, GBP, CHF, CAD, AUD, JPY). No conversions.
- Prefer capturing a product row even if details are missing. when unsure about a field, set that field to null (do not invent values).
- Order the rows chronologically using the signature date: first the products as defined in the CP and then the products as defined in the avenant.
- Use null when a field is not applicable by design for that row (e.g., for a one-shot).
Use the string "unknown" when the field should exist in this contract (typical CP/AV fields) but is not explicitly stated or cannot be located with confidence.

## Document structure and precedence:
- One CG = Conditions Générales (cadre): general default contract conditions.
- One CP = Conditions Particulières (souscription): specific client defined contract conditions.
- Possibly many AVENANTS: updates, improvements or modifications of the CP, signed after the CP.
- If CP specifies a value (or any contract condition) it overrides what was defined in the CG.
- If CP is silent, fall back to CG.
- Treat each product present in the AVENANT section as separate products, even if they repeat with respect to the CP. 
- Older contracts are before 2023.
- In newer contracts products are usually found in “Abonnement …”, “Services associés/Options”, "Base de calcul du montant de l'Abonnement".
  Sometimes it can also be found in an annex such as "ANNEXE 5 : Conditions Financières".
- In older contracts  products are usually found in "Prix, modalites de facturation et de reglement".
- In avenants products are usually found under "2 ARTICLE 5.2 - ABONNEMENT" or "Modifications de l'article 5.2 des Conditions Particulières du Contrat".

## How to identify products & prices:
- One row = one priced block. A "block" may be a table row, a bullet/list item, or a short paragraph (≤3 lines) where a label is clearly tied to a
 nearby amount (same line or within the next line). Free-text blocks count if the pairing is clear. Create a product row whenever a description/label
   is directly tied to a price in the same line/cell/box or the immediately following short line.
- Valid blocks can be: table rows, bullet/paragraph lines with a nearby price, or bordered callouts. Products may also appear in the contract text in
natural language.
- Do not make rows for “Total / Sous-total / Récapitulatif / recaps /Total abonnement /Total abonnement aux Process métier …”. Only record the underlying 
items that carry their own price or are included. Do not aggregate across blocks: one row per priced block. If a block shows only a total,
 do not produce a row and use the child items that carry their own prices. These aggregated magnitudes can only be present in total_abbonement_mensuel.
- Price extraction. Take the closest amount to the block. Set tax_basis only if HT/TTC is shown next to that amount.
- Periodicity. Set loyer_periodicity from the local wording next to the price (e.g., mensuel/le, trimestriel/le, annuel/le).
 If not explicit on that block, leave null.
- One-time vs recurring. If the block says OTC / mise en œuvre / one-time / setup / frais initiaux or is a setup/milestone/OTC (e.g., “On order”,
 “After Design Phase”, “At delivery of the configuration”, “At the end of UAT”, “Production start-up”, “2 months after go live”,
  “Kick-off”, “Hypercare”), then: set one_shot_service=true. Put the amount in price_unitaire (NOT in loyer). Set loyer, loyer_facturation, loyer_annuele, 
  loyer_periodicity, billing_frequency, total_abbonement_mensuel = null. Set is_volume_product=false. Otherwise, treat as recurring.
- Priority for one-shots: when one_shot_service=true, the closest amount MUST be captured in price_unitaire.
  Do not populate loyer or any loyer_* fields for one-shots.
- Usage/volume cases. Only recurring, consumption-based blocks can be volume products. One-shot rows can NEVER be
  is_volume_product=true. If wording mentions volume / unité d'œuvre / palier / S1/S2 / dégressif / utilisateur
  supplémentaire, fill usage_* fields and summarize mechanics in usage_notes (≤100 chars).
- Naming. product_name = the shortest clear label/heading for the block. Put any explicit numeric code on that block in product_code; otherwise null.
- Multi-line features. If many bullets describe one thing and one price is given, create one row.  If multiple prices are listed under distinct
 labels in one block, emit one row per label-price pair.
- Minimum rows sanity check. If the CP shows ≥2 priced blocks, you must output ≥2 rows (still ignore totals).
- Evidence. Quote the shortest nearby text: amount/periodicity for evidence_price; the label you used for product_name for evidence_product.
- If a family/process line (e.g., “Warehouse Management System”, “Performance Indicators”) ends with “d'un montant forfaitaire mensuel total de : X €”, 
this IS the price of that product line.
- If a cell contains several amounts (e.g., “1 550 € HT 200 € HT 150 € HT”), map each amount to the closest preceding labeled item in that block
 (e.g., WMS → 1 550, KPI → 200, Cloisonnement → 150) and emit one row per amount.

## How to identify overconsumption (surconsommation)
- If the nearby text mentions any of: dépassement, complément de consommation, surconsommation, 
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

## How to handle avenants:
- Avenants are found after the CP. Each one is defined with the tags: "=== DOC: AVENANT — type=avenant ===\n".
  Each of these must be treated independently. Sometimes in the document they may be referred to as "amendment".
- Each avenant creates additional product rows in sequential order, as defined by the signature date of the avenant;
do not overwrite CP rows, even if the product is the same. Do not omit unchanged products already present in the CP.
- Row creation rule for amendments: create rows ONLY from blocks that pair a concrete label with a numeric price
  (table row, bullet, or short paragraph). Ignore methodology prose (phases, governance, calendars, UAT criteria)
  when no price is in the same block.
- If an avenant changes an already present product in any way, reflect the change in evidence_avenant following evidence guidelines.
- Order outputs by signature date (CP rows should come first, then avenants chronologically using their signature date).
- Implementation / milestone fees: treat as one-shot lines.
  one_shot_service=true; price_unitaire = the total for that item; loyer/loyer_* and billing_frequency = null.
  Set service_start_date if the block explicitly says start at signature/Go-Live/etc. Capture payment_terms/methods if stated.
- New perimeter / affiliate priced in the amendment: emit a separate one-shot row for that perimeter.
- Price grids shown without a chosen tier/commitment are descriptive: do NOT create rows. Create volume rows only
  when a concrete commitment (quantity × unit price) with a cadence is stated.
- Restated SLA without price (is_included=true; product_code if present; price_unitaire=null).
- Overconsumption terms in amendments: if a unit price is stated, fill usage_overconsumption_price and its periodicity (if given); do not infer a base fee.


## How to handle Volume products (table decomposition):
- If the CP or AVENANT shows a “Pricing mensuel volumes” table with Year and S1/S2 columns,
- EMIT ONE ROW PER PRICED SEMESTER CELL (e.g., 2015 S1, 2015 S2, 2016 S1, 2016 S2…).
- product_name: "Abonnement volume <Famille> — <Année> <S1/S2>".
- quantity: the numeric commitment as stated (lines, factures, bills) which is provided with a given periodicty. For example,
  “Nombre de lignes de préparation expédiées par an” ⇒ quantity (digits only, no spaces) and quantity_periodicity=Annuelle.
- quantity: use the numeric commitment as printed (digits only, no spaces) and keep it as an
  **integer**. Do **not** prorate by S1/S2 percentages (30%/70%). Set quantity_periodicity according to the information on
  the table, for example Annuelle.
- is_volume_product = true (because it's usage-based)
- Loyer can for exmaple be "Pricing mensual volumes".
- since the table states an explicit monthly price for that commitment period.
- Do NOT aggregate these; do NOT replace them with one generic “volume” row.
- Many times, the SLA agreement (wich must be included in the output) is found in the volumne description, for example: 
"Le montant de l'Abonnement au Volume d'activité est calculé en fonction du nombre mensuel de factures entrantes et sortantes et du Niveau de Services (SLA)"

## Edge cases to consider:
- If reconduction_tacite=True, ignore duration/prorata and set date_end_of_contract="2099-12-31". In evidence_date_end_of_contract, cite the reconduction clause.
- If the "Niveau de Service (SLA)" is present, add it as an additional product including the code. Most details about this product will remain empty.
  Common cases of SLA agreement is "SLA GIS Standard" having the code: 04311 or "SLA GIS Premium" having the code: 04317.
- Specially in AVENANT parts of the contract, The phrase “d'un montant forfaitaire mensuel total de : X €” is not a recap when tied to a family/process;
 it's the price of that product line. Only the terminal line “Total abonnement…” is the recap to put in total_abbonement_mensuel.
- total_abbonement_mensuel is a period-constant envelope; never copy the product's own loyer here. Rows within the same period must carry the same total.
- If the contract has no CG, set signature_date_cg = null (do not mirror CP signature into CG).
 
## Columns to emit (tool output schema).
- Emit one JSON object per product row that maps 1:1 to the record_products tool parameters below.
- Do not invent fields or keys. For each key, follow the definition exactly; if a value is not explicit on the relevant block, set null. 
- Duplicate affair-level fields on every row, many coming from the CG.

## Contract / affair (repeat on every product row)
- company_name (string) — Client legal name from CP “Raison sociale du Client”. If absent, fall back to CG; else null.
- numero_de_contrat (string|null)- The contract string, which usually appear the the beginning of the file under CONTRAT CADRE DE REFERENCE or OPPORTUNITE.
The contract string is usually composed of two numbers like "2014100-39808", this format must be kept.
- reconduction_tacite (bool|null) - Find if the contract has tacite or automatic reconduction, meaning it will renew itself unless stipulated otherwise.
This information is by default in the CG, and sometimes it's changed in the CP. Answer True or False.
- devise_de_facturation (enum: EUR, USD, GBP, CHF, CAD, AUD, JPY) — From CP “Devise de facturation”; fall back to CG.
- tax_basis (HT/TTC|null) — If explicitly shown near prices/totals. Never infer.
- signature_date_cg (date|null) — Signature date of CG, if present. If an AVENANT date is present instead, put this to null.
- signature_date_cp (date|null) — Signature date of CP, if present. If an AVENANT date is present instead, put this to null.
- signature_date_av (date|null) — Signature date of AVENANT, if present.
- avenant_number (numeric|null) - If this part of the document is an AVENANT, put the number in this field.
- service_start_date (string date|null) — Start date of services if a concrete date is written. Do not invent. For example it may be "prend effet à la 
date de signature.". So the start date should be the signature of the document. This is usually the case for AVENANTS.
- debut_facturation (string|null) — Write a specific billing start date if available. If the start is an event (e.g.,procede verbal: PV VABF, GO), put that
 instead. In a given contract, different products may have different billing start dates.
- duree_de_service (number or string|null) — Numeric duration in months or "indeterminé". If possible read the CP “Durée des Services …” line,
if absent in CP, fallback to CG. Any additional remainder such as (e.g., “+ prorata de la période en cours”) put into duree_de_service_notes. 
This value is "indeterminé" if the contract is of type reconduction tacite, meaning it will automatically renew itself.
This information is usually in the CG, old contracts tend to have reconduction tacite.
- duree_de_service_notes (string|null) — Any non-numeric tail near duree_de_service data (e.g., "+ prorata de la période en cours").
- date_end_of_contract (string|null) - This field represent the date at which the contract ends for evry product. The possible cases are:
    -- is null for every row that has one_shot_service=True (for example for OTC).
    -- If reconduction_tacite=True (global contract level property), then the contract is of duree "indetermine", there is no end to the contract.
    In this case put "31 dec 2099".
    -- If reconduction_tacite=False then this field is a derived quantity. It's the signature date + duree_de_service + prorata. The signature date
      is a date always present in the contract. duree_de_service is usually in months. prorata must be calculated as the difference in month between
      the signature date and the end of that year, in months. Therefore, to calculate date_end_of_contract sum to the signature date the months of 
      duree_de_service and prorata (if present). However, if duree_de_service is not available set it to "unknown".
- term_mode (À échoir, Échu or null) — Billing mode for base subscription, possibly present in the “Terme” column.
For overconsumption lines, set overconsumption_term_mode accordingly.

## Product identification
- product_name (string, required) — Line label (“Libellé”) in CP pricing sections.
- product_code (string|null) — “Code” in the same row if present. Put only the code number, any additional description belongs to product_name.
Older contracts tend to not have the product code.
- is_included (boolean, required) — True when the row shows Inclus/Gratuit/Compris/0, meaning this is a product or service which is being delivered,
but without a price. In this case set price_unitaire=null.
- price_unitaire (number|null) — There are three possible cases:
    -- General case, for a flat fee: Take the unitary price cell on the same row  if possible.
    -- If the cell is “Inclus/Gratuit/Compris/0”, set is_included=true and price_unitaire=null.
    -- If is_volume_product=True, then price_unitaire must probably be computed
    using the loyer and quantiy. However, both of this quantities must be expressed per month basis, which is not usually the case. Use
    quantity_periodicity to normalize quantity to a single month and loyer_periodicity to normalize loyer to a single month. Having this values
    then compute price_unitaire = loyer_{per month}/quantiy_{per month}. for example, if semestrial quantity and monthly loyer,
    then quantiy_{per month} = quantity / 6. Compute price_unitaire per single unit of the stated quantity. Do not rebase to “per 100 / 1 000 / 10 000”
    unless the contract explicitly says so (e.g., “€/1000 lignes”). Keep small decimals if needed.
- quantity (number|null) — amount of units of each service, possibly coming from the “Quantité” column of the product table.
It's usually an integer number (01, 02, ..) expressing the a amount of served items or for volume products values like 10000, 15000, 
expressing amount of for example bills. If absent set to null.
- quantity_periodicity (enum: Mensuelle|Trimestrielle|Semestrielle|Annuelle|Autre|null) — cadence of the quantity measure if explicitly stated
 (e.g., “par an” ⇒ Annuelle). Leave null if unstated.
- is_volume_product (boolean, required) — true only if the row's base price itself is
  defined by measured usage/tiers/paliers (volume d'activité, unités d'œuvre, S1/S2).
  If the row is a flat recurring fee with separate overconsumption terms (e.g., base
  200 €/mois + “utilisateur supplémentaire 10 €/mois”), set is_volume_product=false and
  capture overconsumption in usage_*.
- loyer (number|null) — Final price of the product for its own cadence (usually in the form of price_unitaire per quantity),
  regardless of periodicity. Example: if the row states “10 000 € par an”, then loyer=10000 and loyer_periodicity=Annuelle (also set loyer_annuele=10000).
  If one_shot_service=True, then set this to null, since it's a one time payment.
- loyer_facturation (number|null) — This is a calculated magnitude. Is the loyer at facturation time. For example if the loyer is mensuel and the
facturation time is trimestriel, loyer_facturation = loyer * 3. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula.
Also note that without loyer_periodicity it is not possible to calculate this derived magnitude, and thus leave this columns as "unknown".
If one_shot_service=True, then set this to null, since it's a one time payment.
- loyer_annuele (number|null) — This is a calculated magnitude. Is the loyer at the end of the year. For example if the loyer is mensuel then
loyer_facturation = loyer * 12. Note that if the loyer is not mensuel then it's necessary to first obtain
the loyer mensuel by dividing the presented loyer by the amount of months considered and then apply this calculated value in the formula
Also note that without loyer_periodicity it is not possible to calculate this derived magnitude, and thus leave this columns as "unknown".
If one_shot_service=True, then set this to null, since it's a one time payment.
- loyer_periodicity (enum: Mensuelle|Trimestrielle|Annuelle|null) — Set only if the same block states a cadence (e.g., Loyer mensuel). 
If cadence appears only in distant headers or elsewhere, leave null. Do not copy billing cadence here.
If one_shot_service=True, then set this to null, since it's a one time payment.
- total_abbonement_mensuel (number|null): monthly agregated total loyer:
  total_abbonement_mensuel = loyer mensuel of fixed producs (is_volume_product=False) + loyer mensuel of volumne producs (is_volume_product=True),
  for the row's period (CP or AVENANT). Do not copy loyer in this column. Build it using the following cases:
  Case 1 (preferred): If the contract shows a “Total abonnement mensuel (postes fixes)” for that period, 
  use it as loyer mensuel of fixed producs. If a volume projection exists for the same period, use it as loyer mensuel of volumne producs
  to produce the aggregated total.
  Case 2: If no explicit fixed total exists, compute the fixed base as the sum of the monthly loyers of all 
  fixed-fee rows active in that period (exclude included/free, OTC, and all is_volume_product=true rows). 
  If a volume projection exists for the same period, use it as loyer mensuel of volumne producs.
  Case 3: If only a volume projection exists for the period (no fixed-fee rows), 
  total_abbonement_mensuel = monthly volume loyer alone. Only in this case you can copy loyer in this column.
  Case 4 (derivation rule): If no explicit *monthly* volume loyer is shown, derive it:
    a) If price_unitaire and quantity are present:
       - Convert quantity to a monthly quantity based on quantity_periodicity:
         Mensuelle -> q_m = quantity
         Trimestrielle -> q_m = quantity / 3
         Semestrielle -> q_m = quantity / 6
         Annuelle -> q_m = quantity / 12
         Autre/Null -> cannot normalize -> volume monthly loyer = null (add evidence_total_abbonement_mensuel)
       - volume monthly loyer = price_unitaire * q_m
    b) Else if loyer is present with loyer_periodicity:
       Mensuelle -> volume monthly loyer = loyer
       Trimestrielle -> volume monthly loyer = loyer / 3
       Annuelle -> volume monthly loyer = loyer / 12
       Null/Autre -> cannot normalize -> volume monthly loyer = null (add total_abbonement_mensuel)
  The final total_abbonement_mensuel must be identical for all rows within the same period. 
  It should almost never be null; if it is, add a total_abbonement_mensuel note explaining why (e.g., missing periodicity).
  Evidence: in total_abbonement_mensuel_evidence, show a compact formula, e.g. 
  "Fixes=6 025 + Volume(100 000×0,0412=4 116) = 10 141 [CP, pg12]".
  Rules:
  - Do not set this field to the product's own loyer.
  - It must be identical for all rows that belong to the same period.
  - A period (for totals) is defined as: a continuous date range during which the fixed-fee set and (if present) the volume projection are 
  constant per the contract. Period boundaries come from, in order: (1) rows in “Total abonnement mensuel (postes fixes)” (each starts a new period),
  (2) dated activations/changes of fixed-fee products, (3) explicit date ranges on volume projections (these create sub-periods for the blended total).
  Assign each product row to the period that contains its start date (intervals are left-closed/right-open). total_abbonement_mensuel is period-constant:
  for a period it equals the fixed base, or fixed base + monthly volume loyer; if only volume exists, use the monthly volume loyer.
  Normalize volume to monthly (Trimestrielle ÷3, Semestrielle ÷6, Annuelle ÷12). If normalization is impossible, set total_abbonement_mensuel=null
  and briefly explain in total_abbonement_mensuel_evidence.
  
If one_shot_service=True or is_included=True, then set this to null, since it's a one time payment.
- one_shot_service (bool|null) — True if one shot product, paid only once, if explicitly listed. Otherwise False
- bon_de_commande (bool|null) - If the product is of type bon commande. This is usualy commented in the contract text, referencing
specific products. Binary value (True/False).
- bon_de_commande_code (string|null) - Code associated to the bon de commande, present near the bon de commande reference. For example "bon de commande
201612 054696".

## Usage / surconsommation
- usage_overconsumption_price (string|null) — Unit price for overconsumption only if shown, usually associated to volume products.
- usage_overconsumption_periodicity (enum: Mensuelle|Trimestrielle|Semestrielle|Annuelle|Autre|null) — Frequency of overconsumption calculation 
(how often surconsommation is computed), usually stated next to the overconsumption price.
- usage_term_mode (string|null) — Set only when an explicit term mode is stated   for included/usage; otherwise null.
It usually is "à terme échu" or simply "échu" since the client volume consumption cannot be known in advanced. Do not inherit the product billing term here.
- overconsumption_term_mode (string|null) — Term mode specifically for overconsumption (often Échu). Only set if explicit.
- usage_notes (string|null) — Notes about how usage/overconsumption is measured or charged (tiers/thresholds, proration, aggregation scope, carryover,
 rounding, exclusions, caps). Keep original language (FR/EN), ≤160 chars, strip line breaks/spaces, and don't repeat info already captured in structured fields.
 If nothing explicit → null.

## Facturation and payment modes
- billing_frequency (string|null) — Preferably from CP “Modalités de facturation” checkbox, otherwise from CG. e.g. Trimestrielle, Annuelle.
Note: Different from loyer_periodicity. A product can have Loyer mensuel but invoices are issued Trimestrielle.
If one_shot_service=True, then set billing_frequency to null.
- payment_methods (array of enums: virement | prelevement | cheque | other) — usually the checked ☒ methods.
If additional details are present such as “A 45 jours date de facture” add them in payment_terms. Note that the CP contract overwrites the CG contract,
use the terms as found in the CP.
- payment_terms (string|null) — Delay with respect to billing in which the client must pay. Short text like “A 45 jours date de facture”.
- billing_modality_notes (string|null) — Any extra notes you need to preserve.

## Revalorisation
- reval_method (enum: fixed_rate | index_formula | textual | null) — From CG/CP.
- reval_rate_per (number|null) — Numeric rate when fixed. Otherwise null.
- reval_formula (string|null) — Formula/text if index-based or complex. Possibly using Syntec and Energy values. Otherwise null.
If the contract sets a cap (e.g., "plafonnée à 3%"), append it to reval_formula: e.g., "PN = PN-1 × (SN/SN-1), plafonnée à 3%".
- reval_compute_when (string|null) — When it is calculated (e.g., “annuellement”).
- reval_apply_when (string|null) — The date in which it is applied (e.g., “le 1er janvier”).
- reval_apply_from (string|null) — The date (usually year) from which the revalorisation takes effect (start being applied).
- reval_source (enum: CG | CP | null) — Where the rule came from.

## Evidence (fields that start with evidence_*)
- Keep every evidence_* under 80 chars after whitespace collapse. If needed, shorten
  month names (e.g., “20/03/2015, 48m + prorata [CP p8]”). Keep it as short as possible you can summarize freely all evidence columns.
  Concise quotes taken from the same row/box that justified the value for each case.
- Always add a quotation having the source (CP, CG, AVX), being X the avenant number, and the page like [CP, p4]. If several magnitudes involved,
prive a reference for each.
- If possible evidence must come from the same block.
- evidence_price — Short quote showing “Prix unitaire” times "quantity" = “Loyer mensuel” if available for context.
  For volume products, quote the “Pricing mensuel volumes” cell for the period (e.g., “2016 S2 : 18 411 €”). Additionaly, present in detail
  the formula to calculate the price_unitaire.
- evidence_date_end_of_contract: If reconduction_tacite=False, write the reference to the 3 dates that compose this derived quantity: 
signature date, duree_de_service and prorate (it found). If reconduction_tacite=True, then put the reference to where this is stated.
- evidence_avenant: when a product has been modified by an avenant (data comes from an avenant file, the product code is the same or if there's no
product code, then the product description is similar), write a very short summary detailing old costs versus new costs. If possible write the difference as well.
- Evidence must be a single, minimal span from the SAME block as the value.
- Use compact tags of the source and page: [CP p12], [CG p3], [AV p2].
- evidence_product = shortest label you used as product_name.
- evidence_payment_methods = Present the value as found in CP (if present) but also mention the one found in CG. Example "Virement [CP, p12] replacing prelevement [CG, p56]".
- If nothing explicit in that block ⇒ null.
- total_abbonement_mensuel_evidence: list the products included under this enveloping value. Do not use full names since it could be too long, make the
list short if possible. If product codes are available use those instead of the product name. After that write the explicit formula to 
arriving at this value. For example, if 3 products having a loyer of 1550, 200 and 150 are present, then write them as “WMS+KPI+Cloisonnement (1550+200+150=1900)”.
Propagate this enveloping value as found in the CP or the AVENANT for all rows and product type therein (they should be the same for
each CP or each AVENANT). This is an aggregated calculation.
- evidence_dates: summarize the evidence of all the dates used to calculate any duration. In particular express the prorata in month: for example
if the contract is signed 01/10/2015 the prorata is the amount of month until the end of the year, so prorata(signed=01/10/2015) = 2 months.
- evidence_contract_errors (array of strings | null) — List of short flags about inconsistencies, conflicts, or cross-section mismatches
  detected in this contract (e.g., "Éditique 920€/mois in Annexe 3.4 vs 919€ elsewhere"). Keep each item ≤140 chars. Add the references where contradictions
  or erros appear, including typos (minly in french). Consider also very clear and explicity conceptual erros within the contract.
  If none, set null. List source inconsistencies (e.g., a product shown with 920 €/mois in one annex and 919 € in another). Keep it short.
  You can summarize in this section. If something looks kind of strange you can mention it, even if it is not a full blown error.
- For one_shot_service=True, evidence_price should quote the milestone/OTC label and its amount. There should be no loyer for this product: if evidence of
loyer is found, explain this contradiction in evidence_price with references but keep it short.

# Confidence scoring (0-1; null if the field is null)
- Base confidence value is 0.5. Apply this heuristic rules to determine final confidence value:
- (+0.2) if an evidence_* quote from the same block is provided.
- (+0.1) if the value is explicitly labeled (e.g., “mensuel”, “HT”).
- (+0.1) if all the fields values are nearby in the document.
- (+0.2) if calculated values aligned with aggregated values as found in the document (for total amount or service duration).
- (-0.3) if the document shows conflicting values for the same field.
- (-0.2) if the value is inferred only from distant headers or prior sections.
- (-0.1) if CP data is overriding CG data.
- (-0.1) if data for calculating a magnitude is missing.
- (-0.1) if you consider text data to produce a filed value ambiguous.
- (-0.1) obvious OCR garbling.
- Round to one decimal in {0.0,0.1,…,1.0}.
- Never output 1.0 unless the evidence_* quote includes the exact value/cadence token.
- If the corresponding evidence_* is **null**, cap that confidence_* at **0.7** (even if other positives apply).

# Output:
- Always return final results by calling record_products with a complete payload. Do not write plain text.
- When filling tool arguments, do not include raw newlines inside strings; replace internal newlines with spaces or “\n”.
- Each row duplicates the shared affair-level fields (company, dates, currency, etc.) for that product.
"""


# TODO: include this? what are their effect exactly
"""
Sanity checks:
- For each AVENANT pricing table, count numeric amounts excluding the very last “Total abonnement …”. You must output at least that many product
 rows from the AVENANT.
 - Minimum rows sanity check. If the CP shows ≥2 priced blocks, you must output ≥2 rows (still ignore totals).
 """


col_order = [
    "company_name",
    "numero_de_contrat",
    "signature_date_cg",
    "signature_date_cp",
    "signature_date_av",
    "avenant_number",
    "product_code",
    "product_name",
    "service_start_date",
    "duree_de_service",
    "duree_de_service_notes",
    "date_end_of_contract",
    "reconduction_tacite",
    "term_mode",
    "billing_frequency",
    "bon_de_commande",
    "bon_de_commande_code",
    "payment_methods",
    "payment_terms",
    "debut_facturation",
    "price_unitaire",
    "quantity",
    "quantity_periodicity",
    "is_volume_product",
    "loyer",
    "loyer_facturation",
    "loyer_annuele",
    "devise_de_facturation",
    "loyer_periodicity",
    "total_abbonement_mensuel",
    "one_shot_service",
    "tax_basis",
    "is_included",
    "usage_overconsumption_price",
    "usage_overconsumption_periodicity",
    "usage_term_mode",
    "overconsumption_term_mode",
    "usage_notes",
    "billing_modality_notes",
    "reval_method",
    "reval_rate_per",
    "reval_formula",
    "reval_compute_when",
    "reval_apply_when",
    "reval_apply_from",
    "reval_source",
    "evidence_product",
    "evidence_price",
    "evidence_payment_methods",
    "total_abbonement_mensuel_evidence",
    "evidence_date_end_of_contract",
    "evidence_avenant",
    "evidence_usage",
    "evidence_revalorization",
    "evidence_billing",
    "evidence_dates",
    "evidence_contract_errors",
    "confidence_price",
    "confidence_usage",
    "confidence_revalorization",
    "confidence_billing",
    "confidence_dates",
    "confidence_company",
    "confidence_avenant",
]


financial_tools = [
    {
        "type": "function",
        "function": {
            "name": "record_products",
            "description": "Return per-product financial rows. This tool's schema is the authoritative JSON format for output. Include all keys (use null if unknown).",
            "parameters": {
                "type": "object",
                "properties": {
                    "products": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                # --- Affair / company ---
                                "affair_id": {"type": ["string", "null"]},
                                "company_name": {"type": ["string", "null"]},
                                "numero_de_contrat": {"type": ["string", "null"]},
                                "reconduction_tacite": {"type": ["boolean", "null"]},
                                # --- devise_de_facturation & tax ---
                                "devise_de_facturation": {
                                    "type": "string",
                                    "enum": [
                                        "EUR",
                                        "USD",
                                        "GBP",
                                        "CHF",
                                        "CAD",
                                        "AUD",
                                        "JPY",
                                    ],
                                },
                                "tax_basis": {
                                    "type": ["string", "null"],
                                    "enum": ["HT", "TTC", "unknown"],
                                },
                                # --- Dates & term ---
                                "service_start_date": {"type": ["string", "null"]},
                                "debut_facturation": {"type": ["string", "null"]},
                                "signature_date_cg": {"type": ["string", "null"]},
                                "signature_date_cp": {"type": ["string", "null"]},
                                "signature_date_av": {"type": ["string", "null"]},
                                "avenant_number": {"type": ["number", "null"]},
                                "duree_de_service": {
                                    "type": ["number", "string", "null"]
                                },
                                "duree_de_service_notes": {"type": ["string", "null"]},
                                "date_end_of_contract": {"type": ["string", "null"]},
                                "term_mode": {
                                    "type": ["string", "null"],
                                    "enum": ["À échoir", "Échu", "unknown"],
                                },
                                # --- Product identification ---
                                "product_name": {"type": "string"},
                                "product_code": {"type": ["string", "null"]},
                                "is_included": {"type": "boolean"},
                                # --- Recurring base ---
                                "price_unitaire": {"type": ["number", "null"]},
                                "quantity": {"type": ["number", "null"]},
                                "quantity_periodicity": {"type": ["string", "null"]},
                                "is_volume_product": {"type": ["boolean", "null"]},
                                "loyer": {"type": ["number", "null"]},
                                "loyer_facturation": {"type": ["number", "null"]},
                                "loyer_annuele": {"type": ["number", "null"]},
                                "loyer_periodicity": {
                                    "type": ["string", "null"],
                                    "enum": [
                                        "Mensuelle",
                                        "Trimestrielle",
                                        "Annuelle",
                                        "Autre",
                                        "unknown",
                                    ],
                                },
                                "total_abbonement_mensuel": {
                                    "type": ["number", "null"]
                                },
                                # --- One-time ---
                                "one_shot_service": {"type": ["boolean"]},
                                "bon_de_commande": {"type": ["boolean"]},
                                "bon_de_commande_code": {"type": ["string"]},
                                # --- Usage / consumption ---
                                "usage_overconsumption_price": {
                                    "type": ["string", "null"]
                                },
                                "usage_overconsumption_periodicity": {
                                    "type": ["string", "null"],
                                    "enum": [
                                        "Mensuelle",
                                        "Trimestrielle",
                                        "Annuelle",
                                        "Autre",
                                        "unknown",
                                    ],
                                },
                                "usage_notes": {"type": ["string", "null"]},
                                "usage_term_mode": {
                                    "type": ["string", "null"],
                                    "enum": ["À échoir", "Échu", "unknown"],
                                },
                                "overconsumption_term_mode": {
                                    "type": ["string", "null"],
                                    "enum": ["À échoir", "Échu", "unknown"],
                                },
                                # --- Revalorization ---
                                "reval_method": {
                                    "type": ["string", "null"],
                                    "enum": [
                                        "fixed_rate",
                                        "index_formula",
                                        "textual",
                                        "unknown",
                                    ],
                                },
                                "reval_rate_per": {"type": ["number", "null"]},
                                "reval_formula": {"type": ["string", "null"]},
                                "reval_compute_when": {"type": ["string", "null"]},
                                "reval_apply_when": {"type": ["string", "null"]},
                                "reval_apply_from": {"type": ["string", "null"]},
                                "reval_source": {
                                    "type": ["string", "null"],
                                    "enum": ["CG", "CP", "unknown"],
                                },
                                # --- Modalities ---
                                "billing_frequency": {
                                    "type": ["string", "null"],
                                    "enum": [
                                        "Mensuelle",
                                        "Trimestrielle",
                                        "Annuelle",
                                        "Autre",
                                        "unknown",
                                    ],
                                },
                                "payment_methods": {
                                    "type": ["array", "null"],
                                    "items": {
                                        "type": "string",
                                        "enum": [
                                            "virement",
                                            "prelevement",
                                            "cheque",
                                            "portal",
                                            "other",
                                        ],
                                    },
                                },
                                "payment_terms": {"type": ["string", "null"]},
                                "billing_modality_notes": {"type": ["string", "null"]},
                                # --- Evidence (short quotes ≤120 chars) ---
                                "evidence_product": {"type": ["string", "null"]},
                                "evidence_price": {"type": ["string", "null"]},
                                "evidence_usage": {"type": ["string", "null"]},
                                "evidence_revalorization": {"type": ["string", "null"]},
                                "evidence_billing": {"type": ["string", "null"]},
                                "evidence_dates": {"type": ["string", "null"]},
                                "evidence_contract_errors": {"type": ["string", "null"]},
                                "evidence_payment_methods": {
                                    "type": ["string", "null"]
                                },
                                "total_abbonement_mensuel_evidence": {
                                    "type": ["string", "null"]
                                },
                                "evidence_date_end_of_contract": {
                                    "type": ["string", "null"]
                                },
                                "evidence_avenant": {"type": ["string", "null"]},
                                # --- Confidences (0–1) ---
                                "confidence_price": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_usage": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_revalorization": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_billing": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_dates": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_company": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "confidence_avenant": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": col_order,
                        },
                    }
                },
                "required": ["products"],
            },
        },
    }
]
