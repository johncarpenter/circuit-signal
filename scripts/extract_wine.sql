-- Extract wine items from POS line items
-- BigQuery RE2 regex (no lookaheads/lookbehinds)
-- Designed as a companion to extract_beer.sql and extract_rtd.sql

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
    -- General false positives: cooking, accessories, non-alcoholic
    NOT REGEXP_CONTAINS(norm_name, r'(?i)wine\s*sauce|wine\s*vinegar|wine\s*reduction|cooking\s*wine|mulled\s*wine|wine\s*glass|wine\s*opener|wine\s*key|wine\s*rack|wine\s*bag|wine\s*tote|wine\s*charm')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)non[\s-]*alcohol|zero\s*proof|n/?a\s+wine|dealcohol|wine\s*stain')
    -- Exclude beer items so beer and wine are mutually exclusive
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bbeer\b|\bipa\b|\bstout\b|\bporter\b|\bpilsner\b|\bhefeweizen\b')
    AND NOT (REGEXP_CONTAINS(norm_name, r'(?i)\blager\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwine\b'))
    -- Exclude RTD / hard seltzer items
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*claw\b|\btruly\b|\bhigh\s*noon\b|\bvizzy\b|\bhard\s*seltzer\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\btwisted\s*tea\b|\bmike.?s\s*hard\b|\bsmirnoff\s*ice\b|\bfour\s*loko\b')
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bcutwater\b|\bsurfside\b|\branch\s*water\b')
    -- Exclude wine coolers (not real wine)
    AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwine\s*cooler\b|\bbartles\b|\bseagram.?s\s*cooler\b')
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

  -- ── Wine segment: red / white / rosé / sparkling / dessert_fortified / generic_wine ──
  CASE
    -- Sparkling (check first — some brands are always sparkling)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchampagne\b|\bprosecco\b|\bcava\b|\bsparkling\b|\bbrut\b|\bextra\s*dry\b.*\bwine\b') THEN 'sparkling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bveuve\b|\bclicquot\b|\bmoet\b|\bmoët\b|\bdom\s*p[eé]rignon\b') THEN 'sparkling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bla\s*marca\b|\bschramsberg\b|\bmumm\b|\bruinart\b|\btaittinger\b|\bperrier[\s-]*jou[eë]t\b') THEN 'sparkling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgruet\b|\bfreixenet\b|\bsegura\s*viudas\b|\bmionetto\b|\bchandon\b') THEN 'sparkling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkorbel\b|\bandr[eé]\b|\bcook.?s\b.*\bsparkling\b') THEN 'sparkling'

    -- Rosé
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bros[eé]\b|\brosato\b') THEN 'rosé'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhispering\s*angel\b|\bmiraval\b') THEN 'rosé'

    -- Dessert / Fortified
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bport\s*wine\b|\btawny\s*port\b|\bruby\s*port\b|\bporto\b') THEN 'dessert_fortified'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsherry\b|\bmadeira\b|\bmarsala\b') THEN 'dessert_fortified'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bice\s*wine\b|\bsauternes\b|\btokaji\b|\blate\s*harvest\b') THEN 'dessert_fortified'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmoscato\b|\bmuscat\b') THEN 'dessert_fortified'

    -- Red varietals
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcabernet\b|\bcab\s*sauv\b|\bcab\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmerlot\b|\bpinot\s*noir\b|\bpinot\s*n\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmalbec\b|\bsyrah\b|\bshiraz\b|\bzinfandel\b|\bzin\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btempranillo\b|\bsangiovese\b|\bnebbiolo\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrenache\b|\bgarnacha\b|\bcab\s*franc\b|\bcabernet\s*franc\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpetit\s*verdot\b|\bpetite?\s*sirah\b|\bmourv[eè]dre\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bred\s*wine\b|\bred\s*blend\b|\bhouse\s*red\b|\bglass\s*red\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbordeaux\b|\brioja\b|\bchianti\b|\bbarolo\b|\bbarbaresco\b|\bsuper\s*tuscan\b|\bbrunello\b') THEN 'red'

    -- White varietals
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchardonnay\b|\bchard\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsauvignon\s*blanc\b|\bsauv\s*blanc\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpinot\s*grigio\b|\bpinot\s*gris\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\briesling\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bviognier\b|\bchenin\s*blanc\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgew[uü]rz\b|\bgew[uü]rztraminer\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\balba[rñ]i[nñ]o\b|\bgr[uü]ner\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvermentino\b|\btrebbiano\b|\bvernaccia\b|\bsoave\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*wine\b|\bwhite\s*blend\b|\bhouse\s*white\b|\bglass\s*white\b') THEN 'white'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsancerre\b|\bchablis\b|\bpouilly[\s-]*fum[eé]\b|\bpouilly[\s-]*fuiss[eé]\b') THEN 'white'

    -- Brand-based fallback (brands strongly associated with one color)
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcaymus\b|\bsilver\s*oak\b|\bstag.?s\s*leap\b|\bdaou\b') THEN 'red'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkim\s*crawford\b|\bcloudy\s*bay\b') THEN 'white'

    ELSE 'generic_wine'
  END AS wine_segment,

  -- ── Wine varietal ──
  CASE
    -- Red varietals
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcabernet\s*sauvignon\b|\bcab\s*sauv\b') THEN 'cabernet_sauvignon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcabernet\s*franc\b|\bcab\s*franc\b')    THEN 'cabernet_franc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcabernet\b|\bcab\b')                    THEN 'cabernet_sauvignon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmerlot\b')                              THEN 'merlot'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpinot\s*noir\b|\bpinot\s*n\b')          THEN 'pinot_noir'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmalbec\b')                              THEN 'malbec'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsyrah\b|\bshiraz\b')                    THEN 'syrah'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bzinfandel\b|\bzin\b')                   THEN 'zinfandel'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btempranillo\b')                         THEN 'tempranillo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsangiovese\b')                          THEN 'sangiovese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bnebbiolo\b')                            THEN 'nebbiolo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgrenache\b|\bgarnacha\b')               THEN 'grenache'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpetit\s*verdot\b')                      THEN 'petit_verdot'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpetite?\s*sirah\b')                     THEN 'petite_sirah'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmourv[eè]dre\b')                        THEN 'mourvedre'

    -- White varietals
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchardonnay\b|\bchard\b')                THEN 'chardonnay'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsauvignon\s*blanc\b|\bsauv\s*blanc\b')  THEN 'sauvignon_blanc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpinot\s*grigio\b|\bpinot\s*gris\b')     THEN 'pinot_grigio'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\briesling\b')                            THEN 'riesling'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bviognier\b')                            THEN 'viognier'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchenin\s*blanc\b')                      THEN 'chenin_blanc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgew[uü]rz\b|\bgew[uü]rztraminer\b')    THEN 'gewurztraminer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\balba[rñ]i[nñ]o\b')                      THEN 'albarino'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgr[uü]ner\b')                           THEN 'gruner_veltliner'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bvermentino\b')                          THEN 'vermentino'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmoscato\b|\bmuscat\b')                  THEN 'moscato'

    -- Sparkling types
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchampagne\b')                           THEN 'champagne'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bprosecco\b')                            THEN 'prosecco'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcava\b')                                THEN 'cava'

    -- Blends
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bred\s*blend\b')                         THEN 'red_blend'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhite\s*blend\b')                       THEN 'white_blend'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bros[eé]\b|\brosato\b')                  THEN 'rosé'

    -- Region-implied varietals
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchianti\b')                             THEN 'sangiovese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbarolo\b|\bbarbaresco\b')               THEN 'nebbiolo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbrunello\b')                            THEN 'sangiovese'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brioja\b')                               THEN 'tempranillo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbordeaux\b')                            THEN 'bordeaux_blend'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsauternes\b')                           THEN 'sauternes'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsancerre\b|\bpouilly[\s-]*fum[eé]\b')   THEN 'sauvignon_blanc'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchablis\b|\bpouilly[\s-]*fuiss[eé]\b')  THEN 'chardonnay'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsoave\b')                               THEN 'garganega'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bport\s*wine\b|\btawny\b|\bruby\s*port\b|\bporto\b') THEN 'port'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsherry\b')                              THEN 'sherry'

    ELSE NULL
  END AS wine_varietal,

  -- ── Resolved brand name ──
  CASE
    -- Value / popular
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbarefoot\b')                            THEN 'Barefoot'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwoodbridge\b')                          THEN 'Woodbridge'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsutter\s*home\b')                       THEN 'Sutter Home'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\byellow\s*tail\b|\byellowtail\b')        THEN 'Yellow Tail'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfranzia\b')                             THEN 'Franzia'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbota\s*box\b')                          THEN 'Bota Box'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bblack\s*box\b')                         THEN 'Black Box'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcupcake\b')                             THEN 'Cupcake'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcavit\b')                               THEN 'Cavit'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\becco\s*domani\b')                       THEN 'Ecco Domani'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bberinger\b')                            THEN 'Beringer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdark\s*horse\b')                        THEN 'Dark Horse'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmenage\s*a\s*trois\b|\bménage\b')       THEN 'Ménage à Trois'

    -- Mid-range / premium
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjosh\s*cellars?\b')                     THEN 'Josh Cellars'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjosh\b')                                THEN 'Josh Cellars'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmeiomi\b')                              THEN 'Meiomi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkendall[\s-]*jackson\b|\bkj\b')         THEN 'Kendall-Jackson'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bapothic\b')                             THEN 'Apothic'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\b19\s*crimes\b')                         THEN '19 Crimes'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkim\s*crawford\b')                      THEN 'Kim Crawford'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bla\s*crema\b')                          THEN 'La Crema'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdecoy\b')                               THEN 'Decoy'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjoel\s*gott\b')                         THEN 'Joel Gott'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brombauer\b')                            THEN 'Rombauer'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bthe?\s*prisoner\b')                     THEN 'The Prisoner'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbread\s*[&+]\s*butter\b')               THEN 'Bread & Butter'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmark\s*west\b')                         THEN 'Mark West'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bbogle\b')                               THEN 'Bogle'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcolumbia\s*crest\b')                    THEN 'Columbia Crest'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bste[\s.]*michelle\b|chateau\s*ste\b')   THEN 'Chateau Ste. Michelle'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\brobert\s*mondavi\b|\bmondavi\b')        THEN 'Robert Mondavi'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcoppola\b')                             THEN 'Coppola'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blayer\s*cake\b')                        THEN 'Layer Cake'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\beducated\s*guess\b')                    THEN 'Educated Guess'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdaou\b')                                THEN 'DAOU'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjustin\b')                              THEN 'Justin'

    -- Luxury / estate
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcaymus\b')                              THEN 'Caymus'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsilver\s*oak\b')                        THEN 'Silver Oak'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bopus\s*one\b')                          THEN 'Opus One'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bduckhorn\b')                            THEN 'Duckhorn'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcakebread\b')                           THEN 'Cakebread'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfar\s*niente\b')                        THEN 'Far Niente'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjoseph\s*phelps\b|\bphelps\b')          THEN 'Joseph Phelps'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bstag.?s\s*leap\b')                      THEN "Stag's Leap"
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bjordan\b')                              THEN 'Jordan'

    -- Sparkling brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bveuve\b|\bclicquot\b')                  THEN 'Veuve Clicquot'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdom\s*p[eé]rignon\b')                   THEN 'Dom Pérignon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmoet\b|\bmoët\b')                       THEN 'Moët & Chandon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bla\s*marca\b')                          THEN 'La Marca'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bchandon\b')                             THEN 'Chandon'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bschramsberg\b')                         THEN 'Schramsberg'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bgruet\b')                               THEN 'Gruet'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bfreixenet\b')                           THEN 'Freixenet'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmionetto\b')                            THEN 'Mionetto'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bkorbel\b')                              THEN 'Korbel'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\btaittinger\b')                          THEN 'Taittinger'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bruinart\b')                             THEN 'Ruinart'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bperrier[\s-]*jou[eë]t\b')              THEN 'Perrier-Jouët'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmumm\b')                                THEN 'Mumm'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bandr[eé]\b')                            THEN 'André'

    -- Rosé brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bwhispering\s*angel\b')                  THEN 'Whispering Angel'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmiraval\b')                             THEN 'Miraval'

    -- Import brands
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bsanta\s*margherita\b')                  THEN 'Santa Margherita'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bruffino\b')                             THEN 'Ruffino'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bantinori\b|\btignanello\b')             THEN 'Antinori'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcloudy\s*bay\b')                        THEN 'Cloudy Bay'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\boyster\s*bay\b')                        THEN 'Oyster Bay'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bpenfolds\b')                            THEN 'Penfolds'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcampo\s*viejo\b')                       THEN 'Campo Viejo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bmarqu[eé]s\s*de\s*riscal\b')            THEN 'Marqués de Riscal'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bconcha\s*y\s*toro\b')                   THEN 'Concha y Toro'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bcasillero\b')                           THEN 'Casillero del Diablo'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\blouis\s*jadot\b|\bjadot\b')             THEN 'Louis Jadot'
    WHEN REGEXP_CONTAINS(norm_name, r'(?i)\bdr[\.\s]*loosen\b|\bloosen\b')          THEN 'Dr. Loosen'

    ELSE NULL
  END AS wine_brand

FROM exclusions
WHERE
  -- ── Brand matches ──
  REGEXP_CONTAINS(norm_name, r'(?i)\bbarefoot\b|\bwoodbridge\b|\bsutter\s*home\b|\byellow\s*tail\b|\byellowtail\b|\bfranzia\b|\bbota\s*box\b|\bblack\s*box\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcupcake\b|\bcavit\b|\becco\s*domani\b|\bberinger\b|\bdark\s*horse\b|\bmenage\s*a\s*trois\b|\bménage\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bjosh\s*cellars?\b|\bmeiomi\b|\bkendall[\s-]*jackson\b|\bapothic\b|\b19\s*crimes\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bkim\s*crawford\b|\bla\s*crema\b|\bdecoy\b|\bjoel\s*gott\b|\brombauer\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bthe?\s*prisoner\b|\bbread\s*[&+]\s*butter\b|\bmark\s*west\b|\bbogle\b|\blayer\s*cake\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcolumbia\s*crest\b|\bste[\s.]*michelle\b|\bmondavi\b|\bcoppola\b|\beducated\s*guess\b|\bdaou\b|\bjustin\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcaymus\b|\bsilver\s*oak\b|\bopus\s*one\b|\bduckhorn\b|\bcakebread\b|\bfar\s*niente\b|\bjoseph\s*phelps\b|\bphelps\b|\bstag.?s\s*leap\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bveuve\b|\bclicquot\b|\bdom\s*p[eé]rignon\b|\bmoet\b|\bmoët\b|\bla\s*marca\b|\bchandon\b|\bschramsberg\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bgruet\b|\bfreixenet\b|\bmionetto\b|\bkorbel\b|\btaittinger\b|\bruinart\b|\bperrier[\s-]*jou[eë]t\b|\bmumm\b|\bandr[eé]\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bwhispering\s*angel\b|\bmiraval\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsanta\s*margherita\b|\bruffino\b|\bantinori\b|\btignanello\b|\bcloudy\s*bay\b|\boyster\s*bay\b|\bpenfolds\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcampo\s*viejo\b|\bmarqu[eé]s\s*de\s*riscal\b|\bconcha\s*y\s*toro\b|\bcasillero\b|\blouis\s*jadot\b|\bjadot\b|\bloosen\b')
  -- ── Varietal / style matches ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcabernet\b|\bcab\s*sauv\b|\bmerlot\b|\bpinot\s*noir\b|\bpinot\s*n\b|\bmalbec\b|\bsyrah\b|\bshiraz\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bzinfandel\b|\btempranillo\b|\bsangiovese\b|\bnebbiolo\b|\bgrenache\b|\bgarnacha\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bcab\s*franc\b|\bcabernet\s*franc\b|\bpetit\s*verdot\b|\bpetite?\s*sirah\b|\bmourv[eè]dre\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bchardonnay\b|\bchard\b|\bsauvignon\s*blanc\b|\bsauv\s*blanc\b|\bpinot\s*grigio\b|\bpinot\s*gris\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\briesling\b|\bviognier\b|\bchenin\s*blanc\b|\bgew[uü]rz\b|\balba[rñ]i[nñ]o\b|\bgr[uü]ner\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bvermentino\b|\btrebbiano\b|\bvernaccia\b|\bsoave\b|\bmoscato\b|\bmuscat\b')
  -- ── Sparkling / category terms ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bchampagne\b|\bprosecco\b|\bcava\b|\bsparkling\s*wine\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bros[eé]\b.*\bwine\b|\brosato\b')
  -- ── Region terms (strongly imply wine) ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbordeaux\b|\brioja\b|\bchianti\b|\bbarolo\b|\bbarbaresco\b|\bbrunello\b|\bsuper\s*tuscan\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsancerre\b|\bchablis\b|\bpouilly[\s-]*fum[eé]\b|\bpouilly[\s-]*fuiss[eé]\b|\bsauternes\b|\btokaji\b')
  -- ── Fortified / dessert ──
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bport\s*wine\b|\btawny\s*port\b|\bruby\s*port\b|\bporto\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bsherry\b|\bmadeira\b|\bmarsala\b|\bice\s*wine\b|\blate\s*harvest\b')
  -- ── Generic wine terms ──
  OR (REGEXP_CONTAINS(norm_name, r'(?i)\bwine\b') AND NOT REGEXP_CONTAINS(norm_name, r'(?i)\bwine\s*list\b|\bwine\s*menu\b'))
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bred\s*blend\b|\bwhite\s*blend\b|\bhouse\s*red\b|\bhouse\s*white\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bbtg\b|\bby\s*the\s*glass\b|\bglass\s*(?:red|white)\b')
  OR REGEXP_CONTAINS(norm_name, r'(?i)\bvino\b|\bsangria\b')
