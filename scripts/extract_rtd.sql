-- Extract RTD (ready-to-drink) items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)

WITH normalized AS (
  SELECT
    *,
    -- Strip leading prices ($5, $5.00), fractional prefixes (0 1/2), hash prefixes (# 12)
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          LOWER(TRIM(name)),
          r'^\$[\d.]+\s*', ''),
        r'^\d+\s+\d+/\d+\s*', ''),
      r'^#\s*\d+\s*', ''
    ) AS norm_name
  FROM `YOUR_PROJECT.YOUR_DATASET.YOUR_TABLE`
  WHERE _fivetran_deleted IS NOT TRUE
),

exclusions AS (
  SELECT *
  FROM normalized
  WHERE NOT REGEXP_CONTAINS(norm_name, r'(?i)root\s*beer|ginger\s*ale|ginger\s*beer|beer\s*batt|beer\s*cheese|beer\s*bread|beer\s*soup|rum\s*cake|rum\s*raisin|rum\s*extract|rum\s*sauce|bourbon\s*chicken|bourbon\s*sauce|bourbon\s*glaze?|bourbon\s*steak|bourbon\s*bbq|wine\s*sauce|wine\s*reduct|wine\s*vinegar|cold\s*brew|nitro\s*brew|brew\s*coffee|vodka\s*sauce|pasta\s*vodka|penne\s*vodka|shrimp\s*cocktail|cocktail\s*sauce|scotch\s*egg|non[\s-]*alcohol|zero\s*proof|mocktail|virgin\s')
    -- Exclude plain kombucha but allow hard kombucha
    AND NOT (REGEXP_CONTAINS(norm_name, r'(?i)kombucha') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)hard\s*kombucha'))
)

SELECT
  business_id,
  store_id,
  posorder_id,
  posid,
  created,
  name,
  quantity,
  amount,
  CASE
    -- Hard seltzers
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b')              THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btruly\b')                     THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhigh\s*noon\b')               THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvizzy\b')                     THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bn[uü]trl\b')                 THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btopo\s*chico\s*hard\b')       THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbud\s*light\s*seltzer\b')     THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*seltzer\b')            THEN 'hard_seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspiked\b.*(seltzer|lemon|tea|punch)') THEN 'hard_seltzer'

    -- Hard cider
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bangry\s*orchard\b')           THEN 'hard_cider'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*cider\b')              THEN 'hard_cider'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodchuck\b')                 THEN 'hard_cider'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbold\s*rock\b')               THEN 'hard_cider'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bace\s*cider\b')              THEN 'hard_cider'

    -- Flavored malt beverages
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b')             THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmike.?s\s*hard\b')            THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsmirnoff\s*ice\b')            THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfour\s*loko\b')               THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s\s*(escape|variety|cooler)\b') THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bzima\b')                      THEN 'fmb'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnot\s*your\s*father\b')       THEN 'fmb'

    -- Canned / premixed cocktails
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcutwater\b')                  THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurfside\b')                  THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\branch\s*water\b')             THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blong\s*drink\b')              THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfishers?\s*island\b')         THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bclubtails\b')                 THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbuzzball\b')                  THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbeatbox\b')                   THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brtd\b')                       THEN 'canned_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcanned\s*(cocktail|margarita|marg)\b') THEN 'canned_cocktail'

    -- Michelada (beer cocktail, RTD-adjacent — premixed in US restaurants)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmicheladas?\b|\bmichellada\b|\bmicheladanada\b') THEN 'michelada'

    -- Hard kombucha
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjune\s*shine\b|\bjuneshine\b') THEN 'hard_kombucha'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bflying\s*ember\b')            THEN 'hard_kombucha'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*kombucha\b')           THEN 'hard_kombucha'

    -- Hard lemonade / tea (generic, not brand-specific)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*lemon\b')              THEN 'hard_lemonade'

    ELSE 'other_rtd'
  END AS rtd_type,

  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b')              THEN 'White Claw'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btruly\b')                     THEN 'Truly'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhigh\s*noon\b')               THEN 'High Noon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvizzy\b')                     THEN 'Vizzy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bn[uü]trl\b')                 THEN 'Nutrl'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btopo\s*chico\s*hard\b')       THEN 'Topo Chico Hard'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbud\s*light\s*seltzer\b')     THEN 'Bud Light Seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bangry\s*orchard\b')           THEN 'Angry Orchard'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodchuck\b')                 THEN 'Woodchuck'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbold\s*rock\b')               THEN 'Bold Rock'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b')             THEN 'Twisted Tea'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmike.?s\s*hard\b')            THEN "Mike's Hard"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsmirnoff\s*ice\b')            THEN 'Smirnoff Ice'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfour\s*loko\b')               THEN 'Four Loko'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcutwater\b')                  THEN 'Cutwater'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurfside\b')                  THEN 'Surfside'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\branch\s*water\b')             THEN 'Ranch Water'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blong\s*drink\b')              THEN 'Long Drink'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfishers?\s*island\b')         THEN 'Fishers Island'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmicheladas?\b|\bmichellada\b|\bmicheladanada\b') THEN 'Michelada'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjune\s*shine\b|\bjuneshine\b') THEN 'JuneShine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bflying\s*ember\b')            THEN 'Flying Embers'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*seltzer\b')            THEN 'Generic Hard Seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*cider\b')              THEN 'Generic Hard Cider'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*kombucha\b')           THEN 'Generic Hard Kombucha'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*lemon\b')              THEN 'Generic Hard Lemonade'
    ELSE 'Other'
  END AS rtd_brand

FROM exclusions
WHERE
  -- Master RTD match — all patterns in one predicate for the WHERE filter
  REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b|\btruly\b|\bhigh\s*noon\b|\bvizzy\b|\bn[uü]trl\b|\btopo\s*chico\s*hard\b|\bbud\s*light\s*seltzer\b|\bhard\s*seltzer\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bangry\s*orchard\b|\bhard\s*cider\b|\bwoodchuck\b|\bbold\s*rock\b|\bace\s*cider\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b|\bmike.?s\s*hard\b|\bsmirnoff\s*ice\b|\bfour\s*loko\b|\bzima\b|\bnot\s*your\s*father\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s\s*(escape|variety|cooler)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcutwater\b|\bsurfside\b|\branch\s*water\b|\blong\s*drink\b|\bfishers?\s*island\b|\bclubtails\b|\bbuzzball\b|\bbeatbox\b|\brtd\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcanned\s*(cocktail|margarita|marg)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmicheladas?\b|\bmichellada\b|\bmicheladanada\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjune\s*shine\b|\bjuneshine\b|\bflying\s*ember\b|\bhard\s*kombucha\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bhard\s*lemon\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bspiked\b.*(seltzer|lemon|tea|punch)')
