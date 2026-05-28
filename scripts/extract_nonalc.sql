-- Extract non-alcoholic / low-alc drink items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Targets products marketed as alcohol alternatives — NA beers, non-alc spirits,
-- zero-proof cocktails, premium mixers — NOT regular sodas/juices/water.

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
  WHERE NOT REGEXP_CONTAINS(norm_name, r'(?i)\bsoda\b|\bpop\b|\bjuice\b|\bsmoothie\b|\bmilk\b|\benergy\b|\bsprite\b|\bcoke\b|\bpepsi\b|\bdr\s*pepper\b|\b7[\s-]*up\b|\bmountain\s*dew\b|\bfanta\b|\bsunkist\b|\bminute\s*maid\b|\bgatorade\b|\bpowerade\b|\bkool[\s-]*aid\b|\bcapri\s*sun\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)root\s*beer|ginger\s*ale|beer\s*batt|beer\s*cheese|beer\s*bread|beer\s*soup')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bcoffee\b|\btea\b|\bwater\b|\blemonade\b')
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
    -- NA Beer — brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bheineken\s*(zero|0\.?0|n/?a|non)')   THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b(zero|0\.?0|n/?a|non).*heineken')    THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bo.?doul.?s?\b')                      THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bodouls\b')                           THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bclausthaler\b')                      THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bathletic\s*(brew|run|free|light|all)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbeck.?s\s*(n/?a|non|free|zero|0)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbitburger\s*(n/?a|non|drive|0|zero)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbitburgerna\b')                      THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bguinness\s*(0|zero|n/?a|na|non)\b')  THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b(0|zero|n/?a|non).*guinness\b')      THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgruvi\b')                            THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsam\s*adams\s*(just|n/?a|zero)\b')   THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbrooklyn\s*special\s*effects\b')     THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpartake\b')                          THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbravus\b')                           THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blagunitas\s*(hoppy|ipna|n/?a|non|zero)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bipna\b')                             THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbrewdog\s*(punk|nanny|n/?a|zero|af)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnanny\s*state\b')                    THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbusch\s*(n/?a|non|free|zero)\b')     THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*(edge|n/?a|non|zero)\b')     THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bst\s*pauli\b.*\b(n/?a|non|free|zero|alcohol)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\berdinger\s*(non|alko|free|n/?a|zero)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwellbeing\b')                        THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurreal\s*brew\b')                   THEN 'na_beer'

    -- NA Beer — generic terms
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bn/?a\s+beer\b')                      THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bna\s+beer\b')                        THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(beer|brew|lager|ale|ipa|stout)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\balcohol[\s-]*free\s*(beer|brew|lager|ale|ipa|stout)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b0[.\s]0\s*%?\s*(beer|brew|lager|ale|ipa|stout|abv)\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b(beer|brew|lager|ale|ipa|stout).*\b0[.\s]0\b') THEN 'na_beer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnonalcohol\w*\s*beer\b')             THEN 'na_beer'

    -- NA Wine — brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfre\b\s*(wine|chard|cab|merlot|brut|ros[eé]|sparkling|red|white|pinot)') THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bariel\b\s*(wine|chard|cab|merlot|brut|ros[eé]|sparkling|red|white)') THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurely\b.*(wine|sparkling|ros[eé]|brut|sauv|non|n/?a)') THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bproxies\b')                          THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnoughty\b')                          THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bthomson\s*&?\s*scott\b')             THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgiesen\b.*(non|zero|n/?a|0)')        THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bst\.?\s*regis\b.*(wine|chard|cab|merlot|brut|sparkling)') THEN 'na_wine'

    -- NA Wine — generic terms
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(wine|prosecco|champagne|sparkling)\b') THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\balcohol[\s-]*free\s*(wine|prosecco|champagne|sparkling)\b') THEN 'na_wine'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b0[.\s]0\s*%?\s*(wine|prosecco|sparkling|champagne)\b') THEN 'na_wine'

    -- NA Spirits — brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseedlip\b')                          THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blyre.?s\b')                          THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmonday\b\s*(gin|whiskey|mezcal|zero|non|spirit)') THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\britual\s*(zero|non)\b')              THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspiritless\b')                       THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfree\s*spirits\b')                   THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bceders?\b.*(gin|spirit|non|alt)')    THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdhos\b')                             THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bproteau\b')                          THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bthree\s*spirit\b')                   THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwilfred.?s\b')                       THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwilderton\b')                        THEN 'na_spirits'

    -- NA Spirits — generic terms
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(spirit|whiskey|whisky|bourbon|gin|rum|tequila|vodka)\b') THEN 'na_spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bzero[\s-]*proof\b')                  THEN 'na_spirits'

    -- NA Cocktails / Mocktails — brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcurious\s*elixir\b')                 THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkin\s*(euphorics|bloom|dream|lightwave|spritz)\b') THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bghia\b')                             THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bde\s*soi\b')                         THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhop\s*wtr\b|\bhopwtr\b')             THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blagunitas\s*hoppy\s*refresher\b')    THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsans\s*bar\b')                       THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\baplos\b|\bapl[oó]s\b')              THEN 'na_cocktail'

    -- NA Cocktails — generic terms
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmocktail\b')                         THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+(margarita|mojito|mule|pina\s*colada|daiquiri|mary|cocktail|sangria|paloma|spritz)\b') THEN 'na_cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(cocktail|margarita|mojito|mule|spritz)\b') THEN 'na_cocktail'

    -- Premium Mixers
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfever[\s-]*tree\b')                  THEN 'premium_mixer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bq\s+(tonic|mixer|ginger|club|bitter|elderflower|hibiscus|grapefruit|lemon)\b') THEN 'premium_mixer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bq\s+mixers?\b')                      THEN 'premium_mixer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfentimans?\b')                       THEN 'premium_mixer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*rudy\b')                      THEN 'premium_mixer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfee\s*brothers\b')                   THEN 'premium_mixer'

    -- Low-alc / session
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bradler\b')                           THEN 'low_alc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bshandy\b|\bshandies\b')             THEN 'low_alc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bschofferhofer\b|\bsch[oö]fferhofer\b') THEN 'low_alc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstiegl\s*radler\b')                  THEN 'low_alc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blow[\s-]*alc\w*\b')                  THEN 'low_alc'

    -- Generic NA catch-all
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alcohol\w*\b')              THEN 'generic_na'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\balcohol[\s-]*free\b')                THEN 'generic_na'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bzero\s*alcohol\b')                   THEN 'generic_na'

    ELSE 'other_nonalc'
  END AS nonalc_type,

  CASE
    -- NA Beer brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bheineken\s*(zero|0\.?0|n/?a|non)')   THEN 'Heineken 0.0'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b(zero|0\.?0|n/?a|non).*heineken')    THEN 'Heineken 0.0'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bo.?doul.?s?\b')                      THEN "O'Doul's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bodouls\b')                           THEN "O'Doul's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bclausthaler\b')                      THEN 'Clausthaler'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bathletic\s*(brew|run|free|light|all)\b') THEN 'Athletic Brewing'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbeck.?s\s*(n/?a|non|free|zero|0)\b') THEN "Beck's NA"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbitburger\s*(n/?a|non|drive|0|zero)\b') THEN 'Bitburger Drive'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbitburgerna\b')                      THEN 'Bitburger Drive'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bguinness\s*(0|zero|n/?a|na|non)\b')  THEN 'Guinness 0.0'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b(0|zero|n/?a|non).*guinness\b')      THEN 'Guinness 0.0'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgruvi\b')                            THEN 'Gruvi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsam\s*adams\s*(just|n/?a|zero)\b')   THEN 'Sam Adams Just The Haze'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbrooklyn\s*special\s*effects\b')     THEN 'Brooklyn Special Effects'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpartake\b')                          THEN 'Partake'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbravus\b')                           THEN 'Bravus'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blagunitas\s*(hoppy|ipna|n/?a|non|zero)\b') THEN 'Lagunitas IPNA'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bipna\b')                             THEN 'Lagunitas IPNA'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbrewdog\s*(punk|nanny|n/?a|zero|af)\b') THEN 'BrewDog AF'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnanny\s*state\b')                    THEN 'BrewDog Nanny State'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbusch\s*(n/?a|non|free|zero)\b')     THEN 'Busch NA'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*(edge|n/?a|non|zero)\b')     THEN 'Coors Edge'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bst\s*pauli\b.*\b(n/?a|non|free|zero|alcohol)\b') THEN 'St. Pauli NA'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\berdinger\s*(non|alko|free|n/?a|zero)\b') THEN 'Erdinger NA'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwellbeing\b')                        THEN 'WellBeing Brewing'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurreal\s*brew\b')                   THEN 'Surreal Brewing'

    -- NA Wine brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfre\b\s*(wine|chard|cab|merlot|brut|ros[eé]|sparkling|red|white|pinot)') THEN 'Fre Wines'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bariel\b\s*(wine|chard|cab|merlot|brut|ros[eé]|sparkling|red|white)') THEN 'Ariel'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurely\b.*(wine|sparkling|ros[eé]|brut|sauv|non|n/?a)') THEN 'Surely'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bproxies\b')                          THEN 'Proxies'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnoughty\b')                          THEN 'Noughty'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgiesen\b.*(non|zero|n/?a|0)')        THEN 'Giesen 0%'

    -- NA Spirit brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseedlip\b')                          THEN 'Seedlip'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blyre.?s\b')                          THEN "Lyre's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmonday\b\s*(gin|whiskey|mezcal|zero|non|spirit)') THEN 'Monday'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\britual\s*(zero|non)\b')              THEN 'Ritual Zero Proof'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspiritless\b')                       THEN 'Spiritless'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfree\s*spirits\b')                   THEN 'Free Spirits'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdhos\b')                             THEN 'Dhos'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bproteau\b')                          THEN 'Proteau'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bthree\s*spirit\b')                   THEN 'Three Spirit'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwilderton\b')                        THEN 'Wilderton'

    -- NA Cocktail brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcurious\s*elixir\b')                 THEN 'Curious Elixirs'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bghia\b')                             THEN 'Ghia'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bde\s*soi\b')                         THEN 'De Soi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhop\s*wtr\b|\bhopwtr\b')             THEN 'HopWTR'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsans\s*bar\b')                       THEN 'Sans Bar'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\baplos\b|\bapl[oó]s\b')              THEN 'Aplos'

    -- Premium Mixer brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfever[\s-]*tree\b')                  THEN 'Fever-Tree'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bq\s+(tonic|mixer|ginger|club|bitter|elderflower|hibiscus|grapefruit|lemon)\b') THEN 'Q Mixers'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bq\s+mixers?\b')                      THEN 'Q Mixers'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfentimans?\b')                       THEN 'Fentimans'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*rudy\b')                      THEN 'Jack Rudy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfee\s*brothers\b')                   THEN 'Fee Brothers'

    -- Low-alc brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstiegl\s*radler\b')                  THEN 'Stiegl Radler'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bschofferhofer\b|\bsch[oö]fferhofer\b') THEN 'Schofferhofer'

    -- Generic fallbacks
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmocktail\b')                         THEN 'Generic Mocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+mary\b')                    THEN 'Virgin Mary'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+mojito\b')                  THEN 'Virgin Mojito'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+margarita\b')               THEN 'Virgin Margarita'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+mule\b')                    THEN 'Virgin Mule'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+paloma\b')                  THEN 'Virgin Paloma'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+daiquiri\b')                THEN 'Virgin Daiquiri'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+pina\s*colada\b')           THEN 'Virgin Pina Colada'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+cocktail\b')                THEN 'Virgin Cocktail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bradler\b')                           THEN 'Generic Radler'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bshandy\b|\bshandies\b')             THEN 'Generic Shandy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bn/?a\s+beer\b|\bna\s+beer\b')       THEN 'Generic NA Beer'
    ELSE 'Other'
  END AS nonalc_brand

FROM exclusions
WHERE
  -- Master non-alc match — all patterns in one predicate for the WHERE filter

  -- NA Beer brands
  REGEXP_CONTAINS(norm_name, r'(?i)\bheineken\s*(zero|0\.?0|n/?a|non)|\b(zero|0\.?0|n/?a|non).*heineken|\bo.?doul.?s?\b|\bodouls\b|\bclausthaler\b|\bathletic\s*(brew|run|free|light|all)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbeck.?s\s*(n/?a|non|free|zero|0)\b|\bbitburger\s*(n/?a|non|drive|0|zero)\b|\bbitburgerna\b|\bguinness\s*(0|zero|n/?a|na|non)\b|\b(0|zero|n/?a|non).*guinness\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bgruvi\b|\bsam\s*adams\s*(just|n/?a|zero)\b|\bbrooklyn\s*special\s*effects\b|\bpartake\b|\bbravus\b|\blagunitas\s*(hoppy|ipna|n/?a|non|zero)\b|\bipna\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbrewdog\s*(punk|nanny|n/?a|zero|af)\b|\bnanny\s*state\b|\bbusch\s*(n/?a|non|free|zero)\b|\bcoors\s*(edge|n/?a|non|zero)\b|\bst\s*pauli\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\berdinger\s*(non|alko|free|n/?a|zero)\b|\bwellbeing\b|\bsurreal\s*brew\b')

  -- NA Beer generic
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bn/?a\s+beer\b|\bna\s+beer\b|\bnon[\s-]*alc\w*\s*(beer|brew|lager|ale|ipa|stout)\b|\balcohol[\s-]*free\s*(beer|brew|lager|ale|ipa|stout)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\b0[.\s]0\s*%?\s*(beer|brew|lager|ale|ipa|stout|abv)\b|\b(beer|brew|lager|ale|ipa|stout).*\b0[.\s]0\b|\bnonalcohol\w*\s*beer\b')

  -- NA Wine
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bfre\b\s*(wine|chard|cab|merlot|brut|ros)|\bariel\b\s*(wine|chard|cab|merlot|brut|ros)|\bsurely\b|\bproxies\b|\bnoughty\b|\bgiesen\b.*(non|zero|n/?a|0)')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(wine|prosecco|champagne|sparkling)\b|\balcohol[\s-]*free\s*(wine|prosecco|champagne|sparkling)\b|\b0[.\s]0\s*%?\s*(wine|prosecco|sparkling|champagne)\b')

  -- NA Spirits
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bseedlip\b|\blyre.?s\b|\britual\s*(zero|non)\b|\bspiritless\b|\bfree\s*spirits\b|\bdhos\b|\bproteau\b|\bthree\s*spirit\b|\bwilderton\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmonday\b\s*(gin|whiskey|mezcal|zero|non|spirit)|\bceders?\b.*(gin|spirit|non|alt)|\bzero[\s-]*proof\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(spirit|whiskey|whisky|bourbon|gin|rum|tequila|vodka)\b')

  -- NA Cocktails
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmocktail\b|\bcurious\s*elixir\b|\bghia\b|\bde\s*soi\b|\bhop\s*wtr\b|\bhopwtr\b|\bsans\s*bar\b|\baplos\b|\bapl[oó]s\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bkin\s*(euphorics|bloom|dream|lightwave|spritz)\b|\blagunitas\s*hoppy\s*refresher\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bvirgin\s+(margarita|mojito|mule|pina\s*colada|daiquiri|mary|cocktail|sangria|paloma|spritz)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alc\w*\s*(cocktail|margarita|mojito|mule|spritz)\b')

  -- Premium Mixers
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bfever[\s-]*tree\b|\bq\s+(tonic|mixer|ginger|club|bitter|elderflower|hibiscus|grapefruit|lemon)\b|\bq\s+mixers?\b|\bfentimans?\b|\bjack\s*rudy\b|\bfee\s*brothers\b')

  -- Low-alc
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bradler\b|\bshandy\b|\bshandies\b|\bschofferhofer\b|\bsch[oö]fferhofer\b|\bstiegl\s*radler\b|\blow[\s-]*alc\w*\b')

  -- Generic NA
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnon[\s-]*alcohol\w*\b|\balcohol[\s-]*free\b|\bzero\s*alcohol\b')
