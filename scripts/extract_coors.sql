-- Extract Molson Coors portfolio items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Brands: Coors Light, Miller Lite, Blue Moon, Keystone, Hamm's, Madri Excepcional
-- Not found in data: Molson Canadian, Carling, Staropramen, Leinenkugel's,
--   Hop Valley, Creemore Springs, Granville Island, Terrapin, Pravha,
--   Miller High Life, Milwaukee's Best, Icehouse, Old Style Pilsner

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

  -- ── Coors portfolio brand ──
  CASE
    -- Coors family
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*light\b|\bcoors\s*lt\b|\bcoors\s*lite\b|\bcoors\s*lgt\b') THEN 'Coors Light'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*banq\b|\bcoors\s*bqt\b|\bcoors\s*original\b|\bcoors\s*orig\b|\bcoors\s*orignial\b|\bbanquet\s*beer\b') THEN 'Coors Banquet'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*seltzer\b') THEN 'Coors Seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\b') THEN 'Coors Light'  -- bare "coors" defaults to Coors Light

    -- Miller family
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmiller\s*lite?\b|\bmiller\s*lt\b|\bmillerlite\b') THEN 'Miller Lite'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmiller\s*high\s*life\b') THEN 'Miller High Life'

    -- Blue Moon family
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*moon\s*light\s*sky\b') THEN 'Blue Moon LightSky'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*moon\b|\bbluemoon\b') THEN 'Blue Moon'

    -- Other Coors portfolio
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkeystone\b') THEN 'Keystone'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhamms?\b') THEN "Hamm's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmadri\b') THEN 'Madri Excepcional'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmolson\b') THEN 'Molson Canadian'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcarling\b') THEN 'Carling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstaropramen\b') THEN 'Staropramen'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bleinenkugel\b') THEN "Leinenkugel's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhop\s*valley\b') THEN 'Hop Valley'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcreemore\b') THEN 'Creemore Springs'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgranville\s*island\b') THEN 'Granville Island'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bterrapin\b') THEN 'Terrapin'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpravha\b') THEN 'Pravha'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmilwaukee.?s?\s*best\b') THEN "Milwaukee's Best"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bicehouse\b') THEN 'Icehouse'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bold\s*style\b') THEN 'Old Style Pilsner'
    ELSE 'unknown'
  END AS coors_brand,

  -- ── Beer style ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bipa\b')                       THEN 'ipa'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstout\b')                     THEN 'stout'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bporter\b')                    THEN 'porter'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpilsner\b|\bpilsener\b')     THEN 'pilsner'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhefeweizen\b|\bweiss\b|\bwheat\s*beer\b') THEN 'wheat'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blager\b')                     THEN 'lager'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bale\b')                       THEN 'ale'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bshandy\b')                    THEN 'shandy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseltzer\b')                   THEN 'seltzer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blight\b|\blt\b|\blite\b')    THEN 'light'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdraft\b|\bdraught\b')         THEN 'draft'
    ELSE NULL
  END AS beer_style,

  -- ── Format ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdraft\b|\bdraught\b|\bdrft\b|\btap\b') THEN 'draft'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbtl\b|\bbottle\b|\bbt\b|\bnr\b') THEN 'bottle'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcan\b|\b\d+c\b|\b\d+pk\b')  THEN 'can'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrowler\b')                  THEN 'growler'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbucket\b')                   THEN 'bucket'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpitch(?:er)?\b')             THEN 'pitcher'
    ELSE NULL
  END AS serve_format

FROM normalized
WHERE
  -- ── Coors family ──
  REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\b')
  -- ── Miller family ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmiller\s*lite?\b|\bmiller\s*lt\b|\bmillerlite\b|\bmiller\s*high\s*life\b')
  -- ── Blue Moon family ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bblue\s*moon\b|\bbluemoon\b')
  -- ── Other portfolio brands ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bkeystone\b|\bhamms?\b|\bmadri\b|\bmolson\b|\bcarling\b|\bstaropramen\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bleinenkugel\b|\bhop\s*valley\b|\bcreemore\b|\bgranville\s*island\b|\bterrapin\b|\bpravha\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmilwaukee.?s?\s*best\b|\bicehouse\b|\bold\s*style\b')
  -- ── Exclude false positives ──
  AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bcoors\s*field\b|\bcoors\s*event\b')
  AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bbanquet\s*liquor\b|\bbanquet\s*wine\b|\bbanquet\s*room\b')
  AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bgranville\s*chard\b')
