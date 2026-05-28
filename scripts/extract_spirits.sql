-- Extract spirits items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Designed to pair with extract_beer.sql, extract_rtd.sql for category-level analysis

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
    NOT REGEXP_CONTAINS(norm_name, r'(?i)vodka\s*sauce|pasta\s*vodka|penne\s*vodka|rum\s*cake|rum\s*raisin|rum\s*extract|rum\s*sauce|bourbon\s*chicken|bourbon\s*sauce|bourbon\s*glaze?|bourbon\s*steak|bourbon\s*bbq|scotch\s*egg|whiskey\s*glaze|whiskey\s*sauce|tequila\s*lime\s*chicken|tequila\s*lime\s*sauce|brandy\s*sauce|cognac\s*sauce')
    -- Non-alcoholic
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)non[\s-]*alcohol|zero\s*proof|mocktail|virgin\s')
    -- Exclude beer items
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bbud\s*light\b|\bbudweiser\b|\bcoors\b|\bmiller\s*lite?\b|\bcorona\b|\bmodelo\b|\bheineken\b|\bblue\s*moon\b|\bguinness\b|\blager\b|\bstout\b|\bporter\b|\bpilsner\b|\bipa\b')
    -- Exclude RTD items
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

  -- ── Spirit segment: vodka / gin / tequila_mezcal / whiskey_bourbon / scotch / rum / brandy_cognac / liqueur / sake_soju / generic ──
  CASE
    -- Vodka
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btito.?s\b|\btitos\b')               THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrey\s*goose\b|\bgreygoose\b|\bgray\s*goose\b') THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bketel\s*one?\b')                    THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstoli\b|\bstolichnaya\b')           THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\babsolut\b')                         THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbelvedere\b')                       THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bciroc\b')                           THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsmirnoff\b')                        THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnew\s*amsterdam\b|\bnewamsterdam\b') THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspring\s*44\b')                     THEN 'vodka'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvodka\b')                           THEN 'vodka'

    -- Gin
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbombay\b')                          THEN 'gin'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btanqueray\b')                       THEN 'gin'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhendrick.?s?\b')                    THEN 'gin'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgin\b')                             THEN 'gin'

    -- Tequila & mezcal
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpatron\b|\bpatrón\b')              THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdon\s*julio\b|\bdonjulio\b')       THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcasamigos\b')                       THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bclase\s*azul\b|\bclaseazul\b')     THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b1800\b')                            THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmezcal\b|\bvida\s*mezcal\b')       THEN 'tequila_mezcal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btequila\b')                         THEN 'tequila_mezcal'

    -- Whiskey & bourbon
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b')                   THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjameson\b')                         THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcrown\s*royal\b|\bcrownroyal\b')   THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b') THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbulleit\b')                         THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodford\b')                        THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bknob\s*creek\b|\bknobcreek\b')     THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbuffalo\s*trace\b|\bbuffalotrace\b') THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\beagle\s*rare\b')                    THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b')                       THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s?\b|\bseagrams\b')       THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfireball\b')                        THEN 'whiskey_bourbon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbourbon\b|\bwhiske?y\b|\bwhsky\b') THEN 'whiskey_bourbon'

    -- Scotch & single malt
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b')                        THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenlivet\b')                       THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenfiddich\b')                     THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjohnnie\s*walker\b|\bjw\s*black\b|\bjw\s*blue\b|\bjw\s*red\b') THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdewar.?s?\b')                       THEN 'scotch'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bscotch\b')                          THEN 'scotch'

    -- Rum
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbacardi\b')                         THEN 'rum'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcaptain\s*morgan\b|\bcapt\.?\s*morgan\b|\bcaptmorgan\b|\bcaptainmorgan\b') THEN 'rum'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmalibu\b')                          THEN 'rum'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brum\b')                             THEN 'rum'

    -- Brandy & cognac
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhennessy\b|\bhenny\b')             THEN 'brandy_cognac'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrand\s*marnier\b|\bgrandmarnier\b') THEN 'brandy_cognac'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcognac\b|\bbrandy\b|\barmagnac\b') THEN 'brandy_cognac'

    -- Liqueur
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfernet\b')                          THEN 'liqueur'

    -- Sake & soju
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsake\b|\bsoju\b')                  THEN 'sake_soju'

    ELSE 'generic_spirit'
  END AS spirit_segment,

  -- ── Spirit style ──
  CASE
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblanco\b|\bsilver\b|\bslvr\b|\bplata\b') THEN 'blanco'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\breposado\b|\brepo\b')               THEN 'reposado'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\banejo\b|\bañejo\b')                THEN 'anejo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brye\b')                             THEN 'rye'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspiced\b')                          THEN 'spiced'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bflavore?d?\b|\bcitron\b|\bpeppar\b|\bpeach\b|\bberry\b|\bblueberry\b|\borange\b|\bapple\b|\bcoconut\b|\bvanilla\b|\bhoney\b|\bmango\b') THEN 'flavored'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsingle\s*malt\b')                   THEN 'single_malt'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b\d+\s*yr\b|\b\d+\s*year\b|\b12y\b|\b15y\b|\b18y\b|\b25y\b') THEN 'aged'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdark\b')                            THEN 'dark'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blight\b|\bwhite\b')                 THEN 'light'
    ELSE NULL
  END AS spirit_style,

  -- ── Resolved brand name ──
  CASE
    -- Vodka brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btito.?s\b|\btitos\b')               THEN "Tito's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrey\s*goose\b|\bgreygoose\b|\bgray\s*goose\b') THEN 'Grey Goose'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bketel\s*one?\b')                    THEN 'Ketel One'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstoli\b|\bstolichnaya\b')           THEN 'Stolichnaya'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\babsolut\b')                         THEN 'Absolut'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbelvedere\b')                       THEN 'Belvedere'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bciroc\b')                           THEN 'Ciroc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsmirnoff\b')                        THEN 'Smirnoff'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnew\s*amsterdam\b|\bnewamsterdam\b') THEN 'New Amsterdam'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bspring\s*44\b')                     THEN 'Spring 44'

    -- Gin brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbombay\b')                          THEN 'Bombay Sapphire'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btanqueray\b')                       THEN 'Tanqueray'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhendrick.?s?\b')                    THEN "Hendrick's"

    -- Tequila & mezcal brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpatron\b|\bpatrón\b')              THEN 'Patron'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdon\s*julio\b|\bdonjulio\b')       THEN 'Don Julio'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcasamigos\b')                       THEN 'Casamigos'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bclase\s*azul\b|\bclaseazul\b')     THEN 'Clase Azul'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b1800\b')                            THEN '1800'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvida\s*mezcal\b')                   THEN 'Vida Mezcal'

    -- Whiskey & bourbon brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b')                   THEN "Jack Daniel's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjameson\b')                         THEN 'Jameson'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcrown\s*royal\b|\bcrownroyal\b')   THEN 'Crown Royal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b') THEN "Maker's Mark"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbulleit\b')                         THEN 'Bulleit'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodford\b')                        THEN 'Woodford Reserve'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bknob\s*creek\b|\bknobcreek\b')     THEN 'Knob Creek'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbuffalo\s*trace\b|\bbuffalotrace\b') THEN 'Buffalo Trace'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\beagle\s*rare\b')                    THEN 'Eagle Rare'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b')                       THEN 'Skrewball'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bseagram.?s?\b|\bseagrams\b')       THEN "Seagram's"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfireball\b')                        THEN 'Fireball'

    -- Scotch brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b')                        THEN 'Macallan'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenlivet\b')                       THEN 'Glenlivet'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bglenfiddich\b')                     THEN 'Glenfiddich'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*blue\b')                       THEN 'Johnnie Walker Blue'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjw\s*black\b')                      THEN 'Johnnie Walker Black'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjohnnie\s*walker\b|\bjw\s*red\b')  THEN 'Johnnie Walker'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdewar.?s?\b')                       THEN "Dewar's"

    -- Rum brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbacardi\b')                         THEN 'Bacardi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcaptain\s*morgan\b|\bcapt\.?\s*morgan\b|\bcaptmorgan\b|\bcaptainmorgan\b') THEN 'Captain Morgan'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmalibu\b')                          THEN 'Malibu'

    -- Brandy & cognac brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bhennessy\b|\bhenny\b')             THEN 'Hennessy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrand\s*marnier\b|\bgrandmarnier\b') THEN 'Grand Marnier'

    ELSE NULL
  END AS spirit_brand

FROM exclusions
WHERE
  -- ── Vodka ──
  REGEXP_CONTAINS(norm_name, r'(?i)\btito.?s\b|\btitos\b|\bgrey\s*goose\b|\bgreygoose\b|\bgray\s*goose\b|\bketel\s*one?\b|\bstoli\b|\bstolichnaya\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\babsolut\b|\bbelvedere\b|\bciroc\b|\bsmirnoff\b|\bnew\s*amsterdam\b|\bnewamsterdam\b|\bspring\s*44\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bvodka\b')
  -- ── Gin ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbombay\b|\btanqueray\b|\bhendrick.?s?\b')
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bgin\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bginger\b|\bgin\s*house\b|\bvirgin\b|\borigin\b'))
  -- ── Tequila & mezcal ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bpatron\b|\bpatrón\b|\bdon\s*julio\b|\bdonjulio\b|\bcasamigos\b|\bclase\s*azul\b|\bclaseazul\b|\b1800\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\btequila\b|\bmezcal\b|\bvida\s*mezcal\b')
  -- ── Whiskey & bourbon ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjack\s*daniel\b|\bjameson\b|\bcrown\s*royal\b|\bcrownroyal\b|\bmaker.?s?\s*mark\b|\bmakersmark\b|\bmakers\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbulleit\b|\bwoodford\b|\bknob\s*creek\b|\bknobcreek\b|\bbuffalo\s*trace\b|\bbuffalotrace\b|\beagle\s*rare\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bskrewball\b|\bseagram.?s?\b|\bseagrams\b|\bfireball\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbourbon\b|\bwhiske?y\b|\bwhsky\b')
  -- ── Scotch ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bmacallan\b|\bglenlivet\b|\bglenfiddich\b|\bjohnnie\s*walker\b|\bjw\s*black\b|\bjw\s*blue\b|\bjw\s*red\b|\bdewar.?s?\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bscotch\b')
  -- ── Rum ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbacardi\b|\bcaptain\s*morgan\b|\bcapt\.?\s*morgan\b|\bcaptmorgan\b|\bcaptainmorgan\b|\bmalibu\b')
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\brum\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\brum\s*cake\b|\brum\s*raisin\b|\brum\s*extract\b|\brum\s*sauce\b|\bdrum\b|\bforum\b|\bserum\b'))
  -- ── Brandy & cognac ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bhennessy\b|\bhenny\b|\bgrand\s*marnier\b|\bgrandmarnier\b|\bcognac\b|\bbrandy\b|\barmagnac\b')
  -- ── Liqueur ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bfernet\b')
  -- ── Sake & soju ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsake\b|\bsoju\b')
