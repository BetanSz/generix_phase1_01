financial_prompt = """
# Main Objectives:
- Your main objective is to identify the products present in the contract and retrieve the items defined in the Scope to extract. This is mainly financial
information about the products, and other aspects of the contract.
- Products & rows: Create one row for each product as found in the CP (tables, bullets, or callouts) or AVENANTS.
Include items marked Inclus/Gratuit/Compris/0 with is_included=true and price_unitaire=null (or 0 only if literally “0”).
- Do not create rows for totals/recaps; only for underlying items (i.e. products) that usually carry their own price.
- Include all products, even if free/included. For example the product "Niveau de service (SLA)" or simply SLA tends to be included without a price, and
must always be present in the output if retained by the client.
- Product description or code in the avenant may repeat a product already present in the CP. Keep all of them.
- Keep original language of quotes (FR/EN). Output currency as ISO (EUR, USD, GBP, CHF, CAD, AUD, JPY). No conversions.
- Prefer capturing a product row even if details are missing. when unsure about a field, set that field to null (do not invent values).
- Order the rows chronologically using the signature date: first the products as defined in the CP and then the products as defined in the avenant.
- Do not summarize or synthesize umbrella rows. Output one row per priced line when the document lists repeated lines that each carry a price/PU/quantity/loyer
 (e.g., by date range, semester, year, phase).

## Document structure and precedence:
- One CG = Conditions Générales (cadre): general default contract conditions.
- One CP = Conditions Particulières (souscription): specific client defined contract conditions.
- Possibly many AVENANTS: updates, improvements or modifications of the CP, signed after the CP.
- If CP specifies a value (or any contract condition) it overrides what was defined in the CG.
- If CP is silent, fall back to CG.
- Treat each product present in the AVENANT section as separate products, even if they repeat with respect to the CP. 
-In newer contracts (signature date after 2023) products are usually found in “Abonnement …”, “Services associés/Options”, "Base de calcul du montant de l'Abonnement".
  Sometimes it can also be found in an annex such as "ANNEXE 5 : Conditions Financières".
- In older contracts (signature date before 2023) products are usually found in "Prix, modalites de facturation et de reglement". Old contracts tend to have reconduction tacite.
Older contracts tend to not have the product_code.
- In avenants products are usually found under "2 ARTICLE 5.2 - ABONNEMENT" or "Modifications de l'article 5.2 des Conditions Particulières du Contrat".

## How to identify products & prices:
- One row = one priced block. A "block" may be the items in a table row, a bullet/list item, bordered callouts, or a short paragraph (≤3 lines) where a label is clearly tied to a
 nearby amount (same line or within the next line). Free-text blocks (natural language) are also valid if the pairing is clear. Create a product row whenever
a description/label is directly tied to a price in the same line/cell/box or the immediately following short line.
If a table in the finantial conditions has some of these: Code, Wording, Quantity, Price per unit Monthly, rent; it's probably a product table.
Business-process tables by country (e.g., “GIS COUNTRY …”) if they have a product description and loyer, rent or amount should be included.
- Do not make rows for “Total / Sous-total / Récapitulatif / recaps /Total abonnement /Total abonnement aux Process métier …”. Only record the underlying 
items that carry their own price or are included. Do not aggregate across blocks: one row per priced block. If a block shows only a total,
 do not produce a row, use the child items that carry their own prices.
- A product row may have missing product_code.
- Price extraction. Take the closest amount to the block. Set tax_basis only if HT/TTC is shown next to that amount.
- One-time vs recurring cases:
  -- **One-time** : Non-recurring or non-priced deliveries:
  --- Trigger when the block is any of: concession/licence/droit d'usage, OTC / mise en œuvre / setup / milestone 
  (e.g., “On order”, “After Design Phase”, “At delivery…”, “End of UAT”, “Production start-up”, “Kick-off”, “Hypercare”),
  or when the price cell shows Inclus/Gratuit/Compris/0.
  --- Set one_shot_service=true for paid-once items; is_included=true for free/included items.
  --- price_unitaire = closest amount only if paid-once; if is_included=true → price_unitaire=null.
  --- Do not populate any loyer* fields for this case. Set loyer=null, loyer_facturation=null, loyer_annuele=null,
  loyer_periodicity=null, billing_frequency=null, is_volume_product=false, term_mode=null.
  --- If a loyer/cadence appears near a one-shot, keep loyer* = null and briefly note the contradiction in evidence_price.
  -- **Recurring**:
  --- Set one_shot_service=false, is_included=false.
  --- billing_frequency from explicit CP/CG billing terms (else null).
  --- Only recurring, consumption-based blocks can be volume products (is_volume_product=True, is_included=False).
  --- Recurring products with is_volume_product=False have a flat fee wich must be put in loyer, with the corresponding periodicity in loyer_periodicity.
  --- If no cadence on or near the block → loyer_periodicity="unknown" (do not infer).
- If wording mentions volume / unité d'œuvre / palier / S1/S2 / dégressif / utilisateur / 
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
 - REMISE COMMERCIALE or oatherwsie a discout with a negative amount must be included as well.

 ## How to identify Volume products (recurring cases having is_volume_product=True):
- Capture each volume product in a separate row with periodized commitments (dates, date ranges, semesters, years) with PU and/or loyer and/or quantity,
 EMIT ONE ROW PER LINE/PERIOD. For example if the CP or AVENANT shows a “Pricing mensuel volumes”
 table with Year and S1/S2 columns,  EMIT ONE ROW FOR EVERY PRICED SEMESTER CELL (e.g., 2015 S1, 2015 S2, 2016 S1, 2016 S2…). Do NOT aggregate these.
 **Save as product row every one of these entires**. If for example the table has 5 years and 2 prices per yer, there should be 5 times 2 = 10 rows.
- product_name: "Abonnement volume <Famille> — <Année> <S1/S2>".
- quantity: the numeric commitment as stated (lines, factures, bills) which should be provided with a given periodicity. For example,
  “Nombre de lignes de préparation expédiées par an” ⇒ quantity (digits only, no spaces) and quantity_periodicity=Annuelle.
  Keep it as an **integer**. Do **not** prorate by S1/S2 percentages (30%/70%). Set quantity_periodicity according to the information on
  the table, for example Annuelle.
- Loyer can for example be "Pricing mensual volumes", since the table states an explicit monthly price for that commitment period.
- Many times, the SLA agreement (which must be included in the output) is found in the volume description, for example: 
"Le montant de l'Abonnement au Volume d'activité est calculé en fonction du nombre mensuel de factures entrantes et sortantes et du Niveau de Services (SLA)"
- If there is a projection/schedule/commitment table (e.g., “Projection financière”, “Échéancier”, lines like “du 01/03/2026 au 31/08/2026” with
 Quantité mensuelle and Loyer), treat each line as a concrete priced row (one row per line).

## How to identify overconsumption (or surconsommation):
- Only present for products having is_volume_product=True.
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
    - usage_notes = short label, e.g. "prix par utilisateur supplémentaire" or "utilisateur supplémentaire 10 €/mois".

## How to handle avenants:
- Avenants are found after the CP. Each one is defined with the tags: "=== DOC: AVENANT — type=avenant ===\n".
  Each of these must be treated independently. Sometimes in the document they may be referred to as "amendment".
- Each avenant creates additional product rows in sequential order, as defined by the signature date of the avenant;
do not overwrite CP rows, even if the product is the same. Do not omit unchanged products already present in the CP.
- The same rules for detecting products, volume and overconsumption in the CP apply to avenants.
- If an avenant changes an already present product in any way, reflect the change in evidence_avenant following evidence guidelines.
- New perimeter / affiliate priced in the amendment: emit a separate one-shot row for that perimeter.
- Restated SLA without price (is_included=true; product_code if present; price_unitaire=null).
- Do NOT deduplicate by product Code or wording; keep all the product lines.

## Edge cases to consider:
- If reconduction_tacite=True, ignore duration/prorata and set date_end_of_contract="2099-12-31". In evidence_date_end_of_contract, cite the reconduction clause.
- If the "Niveau de Service (SLA)" is present, add it as an additional product including the code. Most details about this product will remain empty.
  Common cases of SLA agreement are "SLA GIS Standard" having the code: 04311 or "SLA GIS Premium" having the code: 04317. The type oF SLA agreement (Standard,
  Premium, etc) must be indicated in the product name if possible. It's usually found in the page of the SLA specifications.
- Specially in AVENANT parts of the contract, The phrase “d'un montant forfaitaire mensuel total de : X €” is not a recap when tied to a family/process;
 it's the price of that product line.
- If the contract has no CG, set signature_date_cg = null (do not mirror CP signature into CG).
- If product has is_included=True and/or one_shot_service=True then set to null: reval_method, reval_rate_per, reval_formula, reval_compute_when,
 reval_apply_when, reval_apply_from, reval_source, loyer_facturation, loyer_annuele, loyer_periodicity.
 
The following section contains the description of the fields that populate the json output:
 
## Contract / affair (repeat on every product row)
- company_name (string) — Client legal name from CP “Raison sociale du Client”. If absent, fall back to CG; else null.
- numero_de_contrat (string|null)- The contract string, which usually appear the the beginning of the file under CONTRAT CADRE DE REFERENCE or OPPORTUNITE.
The contract string is usually composed of two numbers like "2014100-39808", this format must be kept.
- reconduction_tacite (bool|null) - Set to true only if the contract explicitly has reconduction tacite, renouvellement automatique, automatic 
reconduction, or similar; meaning it will renew itself unless stipulated otherwise.
This information is by default in the CG, and sometimes it's changed in the CP. Answer True or False.
- devise_de_facturation (enum: EUR, USD, GBP, CHF, CAD, AUD, JPY) — From CP “Devise de facturation”; fall back to CG.
- tax_basis (HT/TTC|null) — If explicitly shown near prices/totals. Never infer.
- signature_date_cg (date|null) — Signature date of CG, if present. If an AVENANT date is present instead, put this to null.
- signature_date_cp (date|null) — Signature date of CP, if present. If an AVENANT date is present instead, put this to null.
- signature_date_av (date|null) — Signature date of AVENANT, if present.
- avenant_number (numeric|null) - If this part of the document is an AVENANT, put the number in this field.
- service_start_date (string date|null) — Start date of services if a concrete date is written (Do not invent):
-- If the block states “à la signature” set to signature_date_cp (or signature_date_av within an AVENANT).
-- If the block prints another explicit start/effective date, use that.
-- Otherwise null. Never copy dates from other blocks (e.g., do not copy a maintenance start into a licence row).
- debut_facturation (string|null) — Write a specific billing start date if available. If the start is an event (e.g.,procede verbal: PV VABF, GO),
 put that instead. In a given contract, different products may have different billing start dates.
- duree_de_service (number or string|null) — Numeric duration in months or "indeterminé" if reconduction_tacite=True. If possible read the CP “Durée des Services …” line,
if absent in CP, fallback to CG. Any additional remainder such as (e.g., “+ prorata de la période en cours”) put into duree_de_service_notes. 
- duree_de_service_notes (string|null) — Any non-numeric tail near duree_de_service data (e.g., "+ prorata de la période en cours").
- date_end_of_contract (string|null) - This field represents the date at which the contract ends for every product. The possible cases are:
    -- is null for every row that has one_shot_service=True (for example for OTC) or is_included=true.
    -- If reconduction_tacite=True (global contract level property), then the contract is of duree "indetermine", there is no end to the contract.
    In this case put "31 dec 2099".
    -- If reconduction_tacite=False then this field is a derived quantity. It must be calculated as the signature date + duree_de_service + prorata. The signature date
      is a date always present in the contract. duree_de_service is usually in months. prorata must be calculated as the difference in month between
      the signature date and the end of that year, in months. Therefore, to calculate date_end_of_contract sum to the signature date the months of 
      duree_de_service and prorata (if present). However, if duree_de_service is not available set it to "unknown".
- term_mode (À échoir, Échu or null) — Billing mode for base subscription, possibly present in the “Terme” column.
For overconsumption lines, set overconsumption_term_mode accordingly. Set to null for one_shot_service=True and/or is_included=True.

## Product identification
- product_name (string, required) — Line label (“Libellé”) in CP pricing sections. Do not invent synthesized labels if the document instead lists multiple dated lines.
Use the original per-line label
- product_code (string|null) — “Code” in the same row if present. Put only the code number, any additional description belongs to product_name.
- is_included (boolean, required) — True when the row shows Inclus/Gratuit/Compris/0, meaning this is a product or service which is being delivered,
but without a price. In this case set price_unitaire=null.
- price_unitaire (number|null) — There are three possible cases:
    -- General case, for a flat fee: Take the unitary price cell on the same row if possible.
    -- If the cell is “Inclus/Gratuit/Compris/0”, set is_included=true and price_unitaire=null.
    -- If is_volume_product=True, then price_unitaire must probably be computed using the loyer and quantity. However, both of this quantities must
    be expressed per month basis, which is not usually the case. Use
    quantity_periodicity to normalize quantity to a single month and loyer_periodicity to normalize loyer to a single month. Having this values
    then compute price_unitaire = loyer_{per month}/quantity_{per month}. for example, if semestrial quantity and monthly loyer,
    then quantity_{per month} = quantity / 6. Compute price_unitaire per single unit of the stated quantity. Do not rebase to “per 100 / 1 000 / 10 000”
    unless the contract explicitly says so (e.g., “€/1000 lignes”). Keep small decimals if needed.
- quantity (number|null) — amount of units of each service, possibly coming from the “Quantité” column of the product table.
It's usually an integer number (01, 02, ..) expressing the a amount of served items or for volume products values like 10000, 15000, 
expressing amount of for example bills. If absent set to null.
- quantity_periodicity (enum: Mensuelle|Trimestrielle|Semestrielle|Annuelle|Unknown|null) — cadence of the quantity measure if explicitly stated
 (e.g., “par an” ⇒ Annuelle). Leave null if unstated.
- is_volume_product (boolean, required) — true only if the row's base price itself is
  defined by measured usage/tiers/paliers. Use the rules found in "How to identify Volume products".
- loyer (number|null) — Final recurring price of the product for its own cadence. Usually in the form of price_unitaire per quantity for a given periodicty.
  Example: if the row states “10 000 € par an”, then loyer=10000 and loyer_periodicity=Annuelle (also set loyer_annuele=10000).
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
If one_shot_service=True or is_included=True, then set this to null, since it's a one time payment.
- one_shot_service (bool|null) — True if one shot product, paid only once, if explicitly listed. Otherwise False
- bon_de_commande (bool|null) - If the product is of type bon commande. This is usually commented in the contract text, referencing
specific products. Binary value (True/False).
- bon_de_commande_code (string|null) - Code associated to the bon de commande, present near the bon de commande reference. For example "bon de commande
201612 054696".

## Usage / surconsommation
- usage_overconsumption_price (string|null) — Unit price for overconsumption only if shown, usually associated to volume products.
- usage_overconsumption_periodicity (enum: Mensuelle|Trimestrielle|Semestrielle|Annuelle|Unknown|null) — Frequency of overconsumption calculation 
(how often surconsommation is computed), usually stated next to the overconsumption price.
- usage_term_mode (string|null) — Set only when an explicit term mode is stated   for included/usage; otherwise null.
It usually is "à terme échu" or simply "échu" since the client volume consumption cannot be known in advance. Do not inherit the product billing term here.
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
- evidence_dates: summarize the evidence of all the dates used to calculate any duration. In particular express the prorata in month: for example
if the contract is signed 01/10/2015 the prorata is the amount of month until the end of the year, so prorata(signed=01/10/2015) = 2 months.
- evidence_contract_errors (array of strings | null) — List of short flags about inconsistencies, conflicts, or cross-section mismatches
  detected in this contract (e.g., "Éditique 920€/mois in Annexe 3.4 vs 919€ elsewhere"). Keep each item ≤140 chars. Add the references where contradictions
  or errors appear, including typos (minly in french). Consider also very clear and explicit conceptual errors within the contract.
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
- Emit one JSON object per product row that maps 1:1 to the record_products.
- When filling tool arguments, do not include raw newlines inside strings; replace internal newlines with spaces or “\n”.
- Each row duplicates the shared affair-level fields (company, dates, currency, etc.) for that product.
- Do not invent fields or keys. For each key, follow the definition exactly; if a value is not explicit on the relevant block, set null.
- Periodized table sanity check. If a projection/schedule table shows N priced lines, the output must include ≥ N rows (ignoring totals). 
If fewer would be output, do not collapse; output one row per line.
- Table-line sanity check: if a table containing products shows N priced lines, output ≥ N rows (ignore only “Total …” recap lines).
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
                                        "unknown",
                                    ],
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
                                "evidence_date_end_of_contract": {
                                    "type": ["string", "null"]
                                },
                                "evidence_avenant": {"type": ["string", "null"]},
                                 #--- Confidences (0–1) ---
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
