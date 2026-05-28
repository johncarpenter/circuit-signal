-- Extract whiskey & bourbon items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Subset of extract_spirits.sql focused on whiskey_bourbon segment
-- Brands verified against data/alcohol_items.csv master product list

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
    -- Food false positives
    NOT REGEXP_CONTAINS(norm_name, r'(?i)bourbon\s*chicken|bourbon\s*sauce|bourbon\s*glaze?|bourbon\s*steak|bourbon\s*bbq|whiskey\s*glaze|whiskey\s*sauce|whiskey\s*peppercorn|whisky\s*bbq')
    -- Non-alcoholic
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)non[\s-]*alcohol|zero\s*proof|mocktail|virgin\s')
    -- Exclude beer items
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bbud\s*light\b|\bbudweiser\b|\bcoors\b|\bmiller\s*lite?\b|\bcorona\b|\bmodelo\b|\bheineken\b|\bblue\s*moon\b|\bguinness\b|\blager\b|\bstout\b|\bporter\b|\bpilsner\b|\bipa\b')
    -- Exclude RTD items
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b|\btruly\b|\bhigh\s*noon\b|\bvizzy\b|\bn[uü]trl\b|\btopo\s*chico\s*hard\b|\bbud\s*light\s*seltzer\b|\bhard\s*seltzer\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b|\bmike.?s\s*hard\b|\bsmirnoff\s*ice\b|\bfour\s*loko\b|\bzima\b')
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

  -- ── Whiskey sub-segment: bourbon / rye / irish / scotch / japanese / canadian / generic ──
  CASE
    -- Scotch & single malt
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b')                        THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenlivet\b')                       THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenfiddich\b')                     THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjohnnie\s*walker\b|\bjwalker\b|\bjw\s*bl(?:ac)?k\b|\bjw\s*blue\b|\bjw\s*red\b|\bjwb(?:lack)?\b|\bjw\s*(?:high\s*rye|double\s*black|plat(?:inum)?|green|18)\b|\bjw\b') THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdewar.?s?\b')                       THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bscotch\b')                          THEN 'scotch'

    -- Irish whiskey
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjameson\b')                         THEN 'irish'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bslane.?s?\b')                       THEN 'irish'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\birish\s*whiske?y\b')               THEN 'irish'

    -- Japanese whisky
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhakushu\b')                         THEN 'japanese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btoki\b')                            THEN 'japanese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkaiyo\b')                           THEN 'japanese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjap\w*\s*whisk[ey]y\b')            THEN 'japanese'

    -- Canadian
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcrown\s*royal\b|\bcrownroyal\b')   THEN 'canadian'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s?\s*(7|vo|v0|v\.o)\b|\bseagrams?\s*(7|vo|v0|v\.o)\b') THEN 'canadian'

    -- Rye (check before bourbon — some bourbons also match rye, but explicit rye labels take priority)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brye\s*whiske?y\b')                 THEN 'rye'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bx?bull(?:ei|ie|i)t\s*rye\b')             THEN 'rye'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodford\s*rye\b')                 THEN 'rye'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsazerac\s*rye\b')                  THEN 'rye'

    -- Bourbon (named brands)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b') THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bx?bull(?:ei|ie|i)t\b')                    THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodford\b')                        THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bknob\s*creek\b|\bknobcreek\b')     THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbuffalo\s*trace\b|\bbuffalotrace\b') THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\beagle\s*rare\b')                    THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b1792\b')                            THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bangel.?s?\s*envy\b')               THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblanton.?s?\b')                     THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbooker.?s?\b')                      THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbreckenridge\b')                    THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfour\s*roses\b')                    THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhigh\s*w\w*\b')                     THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhudson\s*bourbon\b')               THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmichter.?s?\b')                     THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brieger.?s?\b')                      THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bboulder\s*bourbon\b')              THEN 'bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbourbon\b')                         THEN 'bourbon'

    -- Flavored / specialty whiskey
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b|\bscrewball\b')        THEN 'flavored'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfireball\b')                        THEN 'flavored'

    -- Generic whiskey
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b')                   THEN 'tennessee'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhiske?y\b|\bwhsky\b')            THEN 'whiskey'

    ELSE 'whiskey'
  END AS whiskey_segment,

  -- ── Whiskey style ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brye\b')                             THEN 'rye'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsingle\s*(barrel|malt)\b')         THEN 'single_barrel'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdouble?\s*oak\b|\bdbl\s*oak\b|\bdub\s*oak\b') THEN 'double_oak'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcask\s*strength\b')                THEN 'cask_strength'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsmall?\s*batch\b|\bsm\s*btch\b')  THEN 'small_batch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b\d+\s*yr\b|\b\d+\s*year\b|\b10y\b|\b12y\b|\b15y\b|\b17y\b|\b18y\b|\b25y\b') THEN 'aged'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bapple\b')                          THEN 'flavored'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhoney\b')                          THEN 'flavored'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpeach\b|\bberry\b|\bcherry\b|\bvanilla\b|\bpeanut\s*butter\b|\bpb\b|\bcinnamon\b') THEN 'flavored'
    ELSE NULL
  END AS whiskey_style,

  -- ── Resolved brand name ──
  CASE
    -- Tennessee
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b')                   THEN "Jack Daniel's"

    -- Irish
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjameson\b')                         THEN 'Jameson'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bslane.?s?\b')                       THEN 'Slane'

    -- Canadian
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcrown\s*royal\b|\bcrownroyal\b')   THEN 'Crown Royal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s?\b|\bseagrams\b')       THEN "Seagram's"

    -- Bourbon brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b') THEN "Maker's Mark"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bx?bull(?:ei|ie|i)t\b')                    THEN 'Bulleit'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodford\b')                        THEN 'Woodford Reserve'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bknob\s*creek\b|\bknobcreek\b')     THEN 'Knob Creek'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbuffalo\s*trace\b|\bbuffalotrace\b') THEN 'Buffalo Trace'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\beagle\s*rare\b')                    THEN 'Eagle Rare'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b1792\b')                            THEN '1792'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bangel.?s?\s*envy\b')               THEN "Angel's Envy"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblanton.?s?\b')                     THEN "Blanton's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbooker.?s?\b')                      THEN "Booker's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbreckenridge\b')                    THEN 'Breckenridge'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfour\s*roses\b')                    THEN 'Four Roses'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhigh\s*w\w*\b')                     THEN 'High West'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhudson\s*bourbon\b')               THEN 'Hudson'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmichter.?s?\b')                     THEN "Michter's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brieger.?s?\b')                      THEN "Rieger's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bboulder\s*bourbon\b')              THEN 'Boulder'

    -- Scotch brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b')                        THEN 'Macallan'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenlivet\b')                       THEN 'Glenlivet'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenfiddich\b')                     THEN 'Glenfiddich'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*blue\b|\bjwalker\s*blue\b|blue\s*label\s*jw')  THEN 'Johnnie Walker Blue'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*bl(?:ac)?k\b|\bjwalker\s*black\b|\bjwb(?:lack)?\b|\bjw\s*double\s*black\b') THEN 'Johnnie Walker Black'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*red\b|\bjwalker\s*red\b')     THEN 'Johnnie Walker Red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*(?:high\s*rye|plat(?:inum)?|green|18)\b') THEN 'Johnnie Walker'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjohnnie\s*walker\b|\bjwalker\b|\bjw\b') THEN 'Johnnie Walker'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdewar.?s?\b')                       THEN "Dewar's"

    -- Japanese brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhakushu\b')                         THEN 'Hakushu'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btoki\b')                            THEN 'Toki'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkaiyo\b')                           THEN 'Kaiyo'

    -- Flavored
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b|\bscrewball\b')        THEN 'Skrewball'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfireball\b')                        THEN 'Fireball'

    ELSE NULL
  END AS whiskey_brand

FROM exclusions
WHERE
  -- ── Named brands: bourbon ──
  REGEXP_CONTAINS(norm_name, r'(?i)\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b|\bx?bull(?:ei|ie|i)t\b|\bwoodford\b|\bknob\s*creek\b|\bknobcreek\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbuffalo\s*trace\b|\bbuffalotrace\b|\beagle\s*rare\b|\b1792\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bangel.?s?\s*envy\b|\bblanton.?s?\b|\bbooker.?s?\b|\bbreckenridge\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bfour\s*roses\b|\bhigh\s*w\w*\s*bourbon\b|\bhudson\s*bourbon\b|\bmichter.?s?\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\brieger.?s?\s*bourbon\b|\bboulder\s*bourbon\b')
  -- ── Named brands: tennessee ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b')
  -- ── Named brands: irish ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjameson\b|\bslane.?s?\s*irish\b')
  -- ── Named brands: canadian ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcrown\s*royal\b|\bcrownroyal\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s?\s*(7|vo|v0|v\.o)\b|\bseagrams?\s*(7|vo|v0|v\.o)\b')
  -- ── Named brands: scotch ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b|\bglenlivet\b|\bglenfiddich\b|\bjohnnie\s*walker\b|\bjwalker\b|\bdewar.?s?\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*bl(?:ac)?k\b|\bjw\s*blue\b|\bjw\s*red\b|\bjwb(?:lack)?\b|\bjw\s*(?:high\s*rye|double\s*black|plat(?:inum)?|green|18)\b')
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bjw\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*(?:ginger|pepper|ranch)\b'))
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bscotch\b')
  -- ── Named brands: japanese ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bhakushu\b|\btoki\s*whisk[ey]y\b|\bkaiyo\b')
  -- ── Named brands: flavored ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b|\bscrewball\b|\bfireball\b')
  -- ── Generic terms ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbourbon\b')
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bwhiske?y\b|\bwhsky\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bvodka\b|\bgin\b|\brum\b|\btequila\b'))
