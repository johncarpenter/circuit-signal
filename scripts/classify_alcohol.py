"""Classify POS item names into alcohol vs non-alcohol categories."""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "all_item_names.csv"
OUTPUT_DIR = ROOT / "output"

# ---------------------------------------------------------------------------
# Exclusion patterns — checked FIRST to prevent false positives
# ---------------------------------------------------------------------------
EXCLUSIONS = re.compile(
    r"""
    root\s*beer
    | ginger\s*ale
    | beer\s*batt
    | beer\s*cheese
    | beer\s*bread
    | rum\s*cake
    | rum\s*raisin
    | rum\s*extract
    | rum\s*sauce
    | bourbon\s*chicken
    | bourbon\s*sauce
    | bourbon\s*glaze
    | bourbon\s*steak
    | bourbon\s*bbq
    | bourbon\s*glaz
    | wine\s*sauce
    | wine\s*reduct
    | wine\s*vinegar
    | cold\s*brew
    | nitro\s*brew
    | brew\s*coffee
    | home\s*brew
    | (?<!hard\s)kombucha
    | beer\s*float          # root beer float minus "root" already caught
    | champinon             # champignon mushroom, champinones
    | tap\s*water
    | pint\s*rice
    | limoncello\s*cake
    | limoncello\s*sauce
    | amaretto\s*cake
    | amaretto\s*chees
    | kahlua\s*cake
    | baileys\s*cake
    | baileys\s*chees
    | heineken\s*zero
    | non[\s-]*alcohol
    | zero\s*proof
    | n/?a\s+beer
    | mocktail
    | virgin\s
    | vodka\s*sauce
    | pasta\s*vodka
    | penne\s*(?:alla\s*)?vodka
    | shrimp\s*cocktail
    | cocktail\s*(?:sauce|shrimp|prawn)
    | panna[\s-]*(?:750|cotta)
    | acqua\s*panna
    | churro\s*(?:\d|pack|6|12)
    | ginger\s*beer
    | scotch\s*egg
    | scotch\s*tape
    | manhattan\s*(?:clam|chow)
    | beer\s*soup
    | ipa\s*steak
    | steak\s*ipa
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# Alcohol patterns by category
# ---------------------------------------------------------------------------

BEER_PATTERNS = re.compile(
    r"""
    # --- Brands ---
    \bbud\b | \bbudweiser\b | \bbud\s*lt\b | \bbud\s*light\b
    | \bcoors\b | \bmiller\s*lite\b | \bmiller\s*lt\b
    | \bcorona\b | \bmodelo\b | \bheineken\b
    | \bstella\b | \bartois\b
    | \bpbr\b | \bpabst\b
    | \bblue\s*moon\b
    | \bdos\s*equis\b | \bdos\s*xx\b
    | \bguinness\b
    | \bsam\s*adams\b | \bsamuel\s*adams\b | \bsam\s*seasonal\b
    | \bmich\s*ultra\b | \bmichelob\b
    | \bbusch\b
    | \bnegra\s*modelo\b
    | \byuengling\b
    | \blagunitas\b | \bstone\s*ipa\b
    | \bsapporo\b | \basahi\b | \bkirin\b | \btsingtao\b
    | \bperoni\b | \bmoretti\b
    | \bnewcastle\b
    | \bsmithy\b | \bschlafly\b
    | \bshiner\b | \bshiner\s*bock\b
    | \bkona\b | \bbig\s*wave\b
    | \blongboard\b
    | \bsurly\b | \bvoodoo\s*ranger\b
    | \bblue\s*point\b | \bballast\b
    | \bfat\s*tire\b
    | \bpacifico\b | \btecate\b | \bvictoria\b
    | \brecord\s*beer\b
    | \bnatty\s*light\b | \bnatural\s*light\b
    | \bkeystone\b
    | \bhamms\b | \bolympia\b
    | \belysian\b | \bsierra\s*nevada\b
    | \bdeschutes\b | \bdogfish\b
    | \bfounders\b | \bbell.?s\b
    | \bnew\s*belgium\b | \bgoose\s*island\b
    | \bsweetwater\b | \bterrapin\b

    # --- Types ---
    | \blager\b | \bale\b(?!\s*house) | \bipa\b | \bstout\b | \bporter\b
    | \bpilsner\b | \bpilsener\b | \bhefeweizen\b | \bweiss\b | \bwheat\s*beer\b
    | \bdraft\b(?!\s*pick) | \bdraught\b
    | \bbeer\b
    | \bgrowler\b
    | \bpint\b(?=.*(?:beer|draft|ale|ipa|lager|stout|light|lt|bud|coors|miller))
    | \btallboy\b
    | \b(?:6pk|12pk)\b(?=.*(?:beer|can|btl|bud|coors|miller|corona|modelo|ipa|ale|lager))
    | \b(?:6|12)[\s-]*pack\b(?=.*(?:beer|can|btl|bud|coors|miller|corona|modelo|ipa|ale|lager))
    | \bcraft\s*beer\b
    | \bbrews?\s*flight\b
    | \bopen\s*beer\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

WINE_PATTERNS = re.compile(
    r"""
    # --- Varietals ---
    \bcabernet\b | \bcab\s*sauv\b
    | \bchardonnay\b | \bchard\b
    | \bpinot\b
    | \bmerlot\b
    | \bsauv\s*blanc\b | \bsauvignon\b
    | \briesling\b
    | \bzinfandel\b | \bzin\b(?=.*(?:wine|gl|btl|glass|bottle))
    | \bmalbec\b
    | \bshiraz\b | \bsyrah\b
    | \btempranillo\b
    | \bsangiovese\b
    | \bgrenache\b | \bgarnacha\b
    | \bmourvèdre\b | \bmourvedre\b
    | \bviognier\b
    | \bgrüner\b | \bgruner\b
    | \bprosecco\b
    | \bchampagne\b
    | \bspumante\b
    | \bcava\b(?=.*(?:wine|btl|gl|glass|bottle|brut))

    # --- Wine terms ---
    | \bwine\b(?!\s*sauce|\s*reduct|\s*vinegar)
    | \bvino\b
    | \brosé?\b(?=.*(?:wine|gl|btl|glass|bottle|winery|sangria))
    | \brose\b(?=\s+(?:wine|sangria|glass|btl))
    | \bbrut\b
    | \b750\s*ml\b(?=.*(?:wine|chard|cab|pinot|merlot|blanc|riesling|malbec|prosecco|champagne|red|white|rose))
    | (?:wine|chard|cab|pinot|merlot|blanc|riesling|malbec|prosecco|champagne).*\b750\s*ml\b
    | \bgl\b[.\s].*(?:chard|cab|pinot|merlot|malbec|blanc|riesling|rose)
    | (?:chard|cab|pinot|merlot|malbec|blanc|riesling).*\bgl\b
    | \bglass\b.*(?:chard|cab|pinot|merlot|malbec|blanc|riesling|rose)
    | \bbtl\b.*(?:chard|cab|pinot|merlot|malbec|blanc|riesling|rose)
    | \bwinery\b
    | \bhouse\s*(?:red|white)\b
    | \bhh\s*(?:white|red)\b
    | \bmimosa\b
    | \bbellini\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

SPIRITS_PATTERNS = re.compile(
    r"""
    # --- Types ---
    \bvodka\b | \bgin\b(?!\s*ger)(?!seng)
    | \brum\b(?!\s*cake|\s*raisin|\s*extract|\s*sauce|\s*ball)
    | \bwhisk(?:e?y)\b | \bwhsky\b
    | \bbourbon\b(?!\s*chicken|\s*sauce|\s*glaze|\s*steak|\s*bbq)
    | \btequila\b | \bscotch\b
    | \bmezcal\b | \bmezcl\b
    | \bcognac\b | \bbrandy\b | \barmagnac\b
    | \bsake\b | \bsoju\b
    | \babsinthe\b

    # --- Brands ---
    | \btito'?s\b | \btitos\b
    | \bjameson\b
    | \bpatron\b(?!\s*saint)
    | \bdon\s*julio\b
    | \bhennessy\b | \bhenny\b
    | \bgrey\s*goose\b | \bgoose\b(?=.*(?:vodka|martini|up))
    | \bketel\b | \bbelvedere\b
    | \bciroc\b
    | \bjack\s*daniel\b
    | \bcrown\s*royal\b
    | \bmaker'?s\s*mark\b | \bmakers\b
    | \bwoodford\b | \bbulleit\b | \bknob\s*creek\b
    | \bbuffalo\s*trace\b | \beagle\s*rare\b
    | \bjohnnie\s*walker\b | \bjw\s*black\b | \bjw\s*blue\b
    | \bglenfiddich\b | \bglenlivet\b | \bmacallan\b
    | \bcapt(?:ain)?\s*morgan\b
    | \bbacardi\b
    | \bmalibu\b(?!.*chicken)
    | \babsolut\b
    | \bsmirnoff\b(?!\s*ice)
    | \bstoli\b | \bstolichna\b
    | \bcasamigos\b | \bclase\s*azul\b
    | \b1800\b(?=.*(?:tequila|silver|reposado|anejo|margarita))
    | \bpatr[oó]n\b
    | \bfireball\b
    | \bskrewball\b
    | \btanqueray\b | \bbombay\b | \bhendrick\b
    | \bnew\s*amsterdam\b
    | \bspring\s*44\b
    | \bgrand\s*marnier\b
    | \bvida\s*mezcal\b
    | \bfernet\b
    | \bseagram'?s?\b(?!\s*(?:escape|variety|cooler))
    """,
    re.IGNORECASE | re.VERBOSE,
)

COCKTAIL_PATTERNS = re.compile(
    r"""
    \bmargarita\b
    | \bmojito\b
    | \bmartini\b
    | \bold\s*fashioned\b
    | \bmanhattan\b
    | \bnegroni\b
    | \bsangria\b
    | \bpaloma\b
    | \bdaiquiri\b
    | \bgimlet\b
    | \bcosmo(?:politan)?\b
    | \bmule\b(?!.*(?:kick|shoe|stubborn))
    | \bspritz\b
    | \bpina\s*colada\b | \bpiña\s*colada\b
    | \btom\s*collins\b
    | \blong\s*island\b(?=.*(?:tea|iced))
    | \bblood(?:y)?\s*mary\b
    | \birish\s*coffee\b
    | \bhot\s*toddy\b
    | \bmint\s*julep\b
    | \bcrantini\b
    | \bsour\b(?=.*(?:whiskey|bourbon|amaretto|pisco))
    | \bsidecar\b
    | \bsazerac\b
    | \bcocktail\b
    | \bsig\s*cocktail\b
    | \bcaipirinha\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

LIQUEUR_PATTERNS = re.compile(
    r"""
    \bbaileys\b(?!\s*cake|\s*chees)
    | \bkahlua\b(?!\s*cake)
    | \bamaretto\b(?!\s*cake|\s*chees)
    | \baperol\b
    | \bcampari\b
    | \blimoncello\b(?!\s*cake|\s*sauce)
    | \bchartreuse\b
    | \bcointreau\b
    | \btriple\s*sec\b
    | \bblue\s*curacao\b | \bcuraçao\b
    | \bliqueur\b | \bliquor\b
    | \bcordial\b(?=.*(?:glass|shot|drink))
    | \bschnapps\b
    | \bsambuca\b
    | \bjägermeister\b | \bjager\b | \bjäger\b
    | \bfrangelico\b
    | \bdomaine\s*de\s*canton\b
    | \bst[\.\s]*germain\b
    | \bpimm'?s\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

RTD_PATTERNS = re.compile(
    r"""
    # --- Hard seltzers ---
    \bwhite\s*claw\b
    | \btruly\b
    | \bhigh\s*noon\b
    | \bvizzy\b
    | \bnütrl\b | \bnutrl\b
    | \btopo\s*chico\s*hard\b
    | \bbud\s*light\s*seltzer\b
    | \bhard\s*seltzer\b

    # --- Hard cider ---
    | \bangry\s*orchard\b
    | \bhard\s*cider\b
    | \bwoodchuck\b
    | \bbold\s*rock\b
    | \bace\s*cider\b
    | \bstellar\s*cider\b

    # --- Flavored malt beverages ---
    | \btwisted\s*tea\b
    | \bmike'?s\s*hard\b
    | \bsmirnoff\s*ice\b
    | \bfour\s*loko\b
    | \bseagram'?s\s*(?:escape|variety|cooler)\b
    | \bnot\s*your\s*father\b
    | \bzima\b

    # --- Canned/premixed cocktails ---
    | \bcutwater\b
    | \bsurfside\b
    | \branch\s*water\b
    | \blong\s*drink\b(?!.*island)
    | \bfishers?\s*island\b
    | \btip\s*top\b(?=.*(?:cocktail|marg|negroni|old.fash|manhattan))
    | \bon\s*the\s*rocks\b(?=.*(?:cocktail|marg|cosmo|margarita|aviation))
    | \bclubtails\b
    | \bbuzzball\b
    | \bbeatbox\b
    | \bdaily'?s\b(?=.*(?:cocktail|pouch|frozen|marg|pina))
    | \brtd\b
    | \bcanned\s*(?:cocktail|margarita|marg)
    | \bmichellada\b | \bmicheladas?\b | \bmicheladanada\b

    # --- Hard kombucha ---
    | \bjune\s*shine\b | \bjuneshine\b
    | \bhard\s*kombucha\b
    | \bflying\s*ember\b

    # --- Hard lemonade/tea ---
    | \bhard\s*lemon\b
    | \bspiked\b(?=.*(?:seltzer|lemon|tea|punch))

    # --- Canned heat / other ---
    | \bcanned\s*heat\b(?=.*(?:clickah|4p|6p|12p))
    """,
    re.IGNORECASE | re.VERBOSE,
)

GENERIC_ALCOHOL_PATTERNS = re.compile(
    r"""
    \bshot\b(?!\s*(?:gun|put|espresso|espress))(?=.*(?:whsk|brbn|tequila|vodka|fireball|patron|jameson|well|\$))
    | \bwell\b\s+(?:vodka|gin|rum|tequila|whiskey|bourbon|scotch|drink)
    | \bon\s*(?:the\s*)?rocks\b
    | \bhouse\s*(?:wine|pour|red|white|margarita)\b
    | \bhappy\s*hour\b
    | \bhh\b\s+(?:beer|wine|draft|ipa|ale|lager|marg(?!her)|cocktail|well|vodka|gin\b|rum\b|tequila|whiskey|bourbon|bud|coors|miller|corona|modelo|stella|mojito|sangria|martini|mule|spritz|paloma|negroni|old\s*fash|manhattan|seltzer|cider|pint|btl|glass|pour|drink|shot|margarita|skinny|sig|craft|house|white\s*wine|red\s*wine|blue\s*moon|pina|melon|guava)
    | \bopen\s*(?:beer|wine|bar)\b
    | \bbar\s*tab\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Order matters: more specific categories first
CATEGORIES = [
    ("rtd", RTD_PATTERNS),
    ("liqueur", LIQUEUR_PATTERNS),
    ("cocktail", COCKTAIL_PATTERNS),
    ("spirits", SPIRITS_PATTERNS),
    ("wine", WINE_PATTERNS),
    ("beer", BEER_PATTERNS),
    ("other_alcohol", GENERIC_ALCOHOL_PATTERNS),
]


def normalize(name: str) -> str:
    """Lowercase, strip, remove leading numeric/price prefixes."""
    s = name.strip().lower()
    # Remove leading price ($5, $5.00)
    s = re.sub(r"^\$[\d.]+\s*", "", s)
    # Remove leading fractional prefixes like "0 1/2", "1 0/1"
    s = re.sub(r"^\d+\s+\d+/\d+\s*", "", s)
    # Remove leading digits-only prefixes like "# 12"
    s = re.sub(r"^#\s*\d+\s*", "", s)
    return s.strip()


def classify(name: str) -> tuple[str | None, str | None]:
    """Return (category, matched_pattern) or (None, None) if not alcohol."""
    normed = normalize(name)

    # Check exclusions first
    if EXCLUSIONS.search(normed):
        return None, None

    # Check each category
    for category, pattern in CATEGORIES:
        m = pattern.search(normed)
        if m:
            return category, m.group(0).strip()

    return None, None


def main():
    if not INPUT.exists():
        print(f"Input file not found: {INPUT}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    alcohol_items = []
    non_alcohol_items = []
    category_counts: dict[str, int] = {}

    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            category, match = classify(name)
            if category:
                alcohol_items.append({"name": name, "category": category, "matched": match})
                category_counts[category] = category_counts.get(category, 0) + 1
            else:
                non_alcohol_items.append({"name": name})

    # Write alcohol items
    alcohol_path = OUTPUT_DIR / "alcohol_items.csv"
    with open(alcohol_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "category", "matched"])
        writer.writeheader()
        writer.writerows(alcohol_items)

    # Write non-alcohol items
    non_alcohol_path = OUTPUT_DIR / "non_alcohol_items.csv"
    with open(non_alcohol_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name"])
        writer.writeheader()
        writer.writerows(non_alcohol_items)

    # Summary
    total = len(alcohol_items) + len(non_alcohol_items)
    print(f"\nClassified {total:,} items:")
    print(f"  Alcohol:     {len(alcohol_items):,} ({len(alcohol_items)/total*100:.1f}%)")
    print(f"  Non-alcohol: {len(non_alcohol_items):,} ({len(non_alcohol_items)/total*100:.1f}%)")
    print(f"\nAlcohol by category:")
    for cat in ["beer", "wine", "spirits", "cocktail", "rtd", "liqueur", "other_alcohol"]:
        count = category_counts.get(cat, 0)
        print(f"  {cat:16s} {count:,}")
    print(f"\nOutput:")
    print(f"  {alcohol_path}")
    print(f"  {non_alcohol_path}")


if __name__ == "__main__":
    main()
