-- Extract beer items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Designed to pair with extract_rtd.sql for RTD-vs-beer analysis

WITH normalized AS (
  SELECT
    *,
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          LOWER(TRIM(name)),
          r'^\$[\d.]+\s*', ''),
        r'^\d+\s+\d+/\d+\s*', ''),
      r'^#\s*\d+\s*', ''
    ) AS norm_name
  FROM `circuitpay-dev.master_data_dev.stg_item`
  WHERE _fivetran_deleted IS NOT TRUE
),

exclusions AS (
  SELECT *
  FROM normalized
  WHERE
    -- General false positives
    NOT REGEXP_CONTAINS(norm_name, r'(?i)root\s*beer|ginger\s*ale|ginger\s*beer|beer\s*batt|beer\s*cheese|beer\s*bread|beer\s*soup|beer\s*float|non[\s-]*alcohol|zero\s*proof|n/?a\s+beer|na\s+beer|mocktail|heineken\s*zero|ipa\s*steak|steak\s*ipa')
    -- Exclude RTD items so beer and RTD are mutually exclusive
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b|\btruly\b|\bhigh\s*noon\b|\bvizzy\b|\bn[uü]trl\b|\btopo\s*chico\s*hard\b|\bbud\s*light\s*seltzer\b|\bhard\s*seltzer\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bangry\s*orchard\b|\bhard\s*cider\b|\bwoodchuck\b|\bbold\s*rock\b|\bace\s*cider\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b|\bmike.?s\s*hard\b|\bsmirnoff\s*ice\b|\bfour\s*loko\b|\bzima\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bcutwater\b|\bsurfside\b|\branch\s*water\b|\blong\s*drink\b|\bfishers?\s*island\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bjune\s*shine\b|\bjuneshine\b|\bhard\s*kombucha\b|\bhard\s*lemon\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bmicheladas?\b|\bmichellada\b|\bmicheladanada\b')
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

  -- ── Beer segment: domestic macro / import / craft / generic ──
  CASE
    -- Domestic macro
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbud\b|\bbudweiser\b|\bbud\s*lt\b|\bbud\s*light\b') THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\b')                     THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmiller\s*lite?\b|\bmiller\s*lt\b') THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmich\s*ultra\b|\bmichelob\b') THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbusch\b')                     THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnatty\s*light\b|\bnatural\s*light\b') THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkeystone\b')                  THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpbr\b|\bpabst\b')            THEN 'domestic_macro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhamms\b|\bolympia\b')        THEN 'domestic_macro'

    -- Import
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcorona\b')                    THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmodelo\b|\bnegra\s*modelo\b') THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bheineken\b')                  THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstella\b|\bartois\b')         THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdos\s*equis\b|\bdos\s*xx\b') THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bguinness\b')                  THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsapporo\b|\basahi\b|\bkirin\b|\btsingtao\b') THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bperoni\b|\bmoretti\b')        THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnewcastle\b')                 THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpacifico\b|\btecate\b')       THEN 'import'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvictoria\b')                  THEN 'import'

    -- Craft
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsam\s*adams\b|\bsamuel\s*adams\b|\bsam\s*seasonal\b') THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\byuengling\b')                 THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*moon\b')               THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blagunitas\b')                 THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstone\s*ipa\b')               THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bschlafly\b')                  THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bshiner\b')                    THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkona\b|\bbig\s*wave\b|\blongboard\b') THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurly\b|\bvoodoo\s*ranger\b') THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*point\b|\bballast\b')  THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfat\s*tire\b')                THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\belysian\b|\bsierra\s*nevada\b') THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdeschutes\b|\bdogfish\b')     THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfounders\b|\bbell.?s\b')     THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnew\s*belgium\b|\bgoose\s*island\b') THEN 'craft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsweetwater\b|\bterrapin\b')   THEN 'craft'

    -- Generic beer (style/format terms without a brand)
    ELSE 'generic_beer'
  END AS beer_segment,

  -- ── Beer style ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bipa\b')                       THEN 'ipa'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstout\b')                     THEN 'stout'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bporter\b')                    THEN 'porter'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpilsner\b|\bpilsener\b')     THEN 'pilsner'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhefeweizen\b|\bweiss\b|\bwheat\s*beer\b') THEN 'wheat'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blager\b')                     THEN 'lager'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bale\b')                       THEN 'ale'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmich\s*ultra\b|\bmichelob\b|\blight\b|\blt\b|\bnatty\b|\bkeystone\b') THEN 'light'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdraft\b|\bdraught\b')         THEN 'draft'
    ELSE NULL
  END AS beer_style,

  -- ── Resolved brand name ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbud\s*light\b|\bbud\s*lt\b|\bbudlight\b') THEN 'Bud Light'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbudweiser\b|\bbud\b')         THEN 'Budweiser'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\b')                     THEN 'Coors'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmiller\s*lite?\b|\bmiller\s*lt\b') THEN 'Miller Lite'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmich\s*ultra\b')              THEN 'Michelob Ultra'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmichelob\b')                  THEN 'Michelob'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnegra\s*modelo\b')            THEN 'Negra Modelo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmodelo\b')                    THEN 'Modelo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcorona\b')                    THEN 'Corona'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bheineken\b')                  THEN 'Heineken'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstella\b|\bartois\b')         THEN 'Stella Artois'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdos\s*equis\b|\bdos\s*xx\b') THEN 'Dos Equis'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bguinness\b')                  THEN 'Guinness'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*moon\b')               THEN 'Blue Moon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsam\s*adams\b|\bsamuel\s*adams\b|\bsam\s*seasonal\b') THEN 'Sam Adams'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\byuengling\b')                 THEN 'Yuengling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blagunitas\b')                 THEN 'Lagunitas'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsapporo\b')                   THEN 'Sapporo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\basahi\b')                     THEN 'Asahi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkirin\b')                     THEN 'Kirin'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btsingtao\b')                  THEN 'Tsingtao'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bperoni\b')                    THEN 'Peroni'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmoretti\b')                   THEN 'Moretti'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnewcastle\b')                 THEN 'Newcastle'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpacifico\b')                  THEN 'Pacifico'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btecate\b')                    THEN 'Tecate'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvictoria\b')                  THEN 'Victoria'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpbr\b|\bpabst\b')            THEN 'PBR'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbusch\b')                     THEN 'Busch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnatty\s*light\b|\bnatural\s*light\b') THEN 'Natural Light'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkeystone\b')                  THEN 'Keystone'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhamms\b')                     THEN "Hamm's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bolympia\b')                   THEN 'Olympia'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bschlafly\b')                  THEN 'Schlafly'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bshiner\b')                    THEN 'Shiner'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkona\b|\bbig\s*wave\b')      THEN 'Kona'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blongboard\b')                 THEN 'Longboard'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstone\s*ipa\b')               THEN 'Stone'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsurly\b')                     THEN 'Surly'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvoodoo\s*ranger\b')           THEN 'Voodoo Ranger'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*point\b')              THEN 'Blue Point'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bballast\b')                   THEN 'Ballast Point'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfat\s*tire\b')                THEN 'Fat Tire'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\belysian\b')                   THEN 'Elysian'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsierra\s*nevada\b')           THEN 'Sierra Nevada'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdeschutes\b')                 THEN 'Deschutes'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdogfish\b')                   THEN 'Dogfish Head'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfounders\b')                  THEN 'Founders'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbell.?s\b')                   THEN "Bell's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnew\s*belgium\b')             THEN 'New Belgium'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgoose\s*island\b')            THEN 'Goose Island'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsweetwater\b')                THEN 'SweetWater'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bterrapin\b')                  THEN 'Terrapin'
    ELSE NULL
  END AS beer_brand

FROM exclusions
WHERE
  -- ── Brand matches ──
  REGEXP_CONTAINS(norm_name, r'(?i)\bbud\b|\bbudweiser\b|\bbud\s*lt\b|\bbud\s*light\b|\bcoors\b|\bmiller\s*lite?\b|\bmiller\s*lt\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcorona\b|\bmodelo\b|\bheineken\b|\bstella\b|\bartois\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bpbr\b|\bpabst\b|\bblue\s*moon\b|\bdos\s*equis\b|\bdos\s*xx\b|\bguinness\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsam\s*adams\b|\bsamuel\s*adams\b|\bsam\s*seasonal\b|\bmich\s*ultra\b|\bmichelob\b|\bbusch\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnegra\s*modelo\b|\byuengling\b|\blagunitas\b|\bstone\s*ipa\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsapporo\b|\basahi\b|\bkirin\b|\btsingtao\b|\bperoni\b|\bmoretti\b|\bnewcastle\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bschlafly\b|\bshiner\b|\bkona\b|\bbig\s*wave\b|\blongboard\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsurly\b|\bvoodoo\s*ranger\b|\bblue\s*point\b|\bballast\b|\bfat\s*tire\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bpacifico\b|\btecate\b|\bvictoria\b|\bnatty\s*light\b|\bnatural\s*light\b|\bkeystone\b|\bhamms\b|\bolympia\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\belysian\b|\bsierra\s*nevada\b|\bdeschutes\b|\bdogfish\b|\bfounders\b|\bbell.?s\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bnew\s*belgium\b|\bgoose\s*island\b|\bsweetwater\b|\bterrapin\b')
  -- ── Style / format matches ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\blager\b|\bipa\b|\bstout\b|\bporter\b|\bpilsner\b|\bpilsener\b|\bhefeweizen\b|\bweiss\b|\bwheat\s*beer\b')
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bale\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bale\s*house\b'))
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bdraft\b|\bdraught\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bdraft\s*pick\b'))
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbeer\b|\bgrowler\b|\btallboy\b|\bcraft\s*beer\b|\bbrews?\s*flight\b|\bopen\s*beer\b')
