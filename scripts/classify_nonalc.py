"""Classify POS item names into non-alcoholic / low-alc drink categories.

Targets products marketed as alcohol alternatives — NA beers, non-alc spirits,
zero-proof cocktails, premium mixers — NOT regular sodas/juices/water.
"""

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
    | ginger\s*ale(?!\s*(?:fever|premium|craft))
    | \bsoda\b(?!\s*(?:tonic|fever|craft|premium|artisan))
    | \bpop\b(?!\s*(?:tonic|fever))
    | \bjuice\b
    | \bsmoothie\b
    | \bmilk\b
    | \bcoffee\b(?!\s*(?:non|zero|spirit|seedlip|lyre|ritual))
    | \btea\b(?!\s*(?:non|zero|spirit|seedlip|lyre|ritual|tree))
    | \bwater\b(?!\s*(?:tonic|fever|q\s))
    | \blemonade\b(?!\s*(?:fever|non|zero|craft|premium|artisan))
    | \benergy\b
    | \bsprite\b
    | \bcoke\b
    | \bpepsi\b
    | \bdr\s*pepper\b
    | \b7[\s-]*up\b
    | \bmountain\s*dew\b
    | \bfanta\b
    | \bsunkist\b
    | \bminute\s*maid\b
    | \bgatorade\b
    | \bpowerade\b
    | \bkool[\s-]*aid\b
    | \bcapri\s*sun\b
    | \bhi[\s-]*c\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# Non-alc / low-alc drink patterns by category
# ---------------------------------------------------------------------------

NA_BEER_PATTERNS = re.compile(
    r"""
    # --- Generic NA beer terms ---
    \bn/?a\s+beer\b
    | \bnon[\s-]*alc(?:oholic)?\s*(?:beer|brew|lager|ale|ipa|stout|wheat|pils|hef)\b
    | \balcohol[\s-]*free\s*(?:beer|brew|lager|ale|ipa|stout|wheat|pils|hef)\b
    | \bzero[\s-]*(?:alc|alcohol)\s*(?:beer|brew|lager|ale|ipa|stout)\b
    | \bde[\s-]*alcohol\w*\s*(?:beer|brew|lager|ale|ipa)\b
    | \b0[\s.]0\s*%?\s*(?:beer|brew|lager|ale|ipa|stout|abv)\b
    | \b(?:beer|brew|lager|ale|ipa|stout).*\b0[\s.]0\b

    # --- NA beer brands ---
    | \bathletic\s*(?:brew|run|free|light|all)\b
    | \bclausthaler\b
    | \bo'?doul'?s\b | \bodoul\b
    | \bbeck'?s\s*(?:n/?a|non|free|zero|0)\b
    | \bbusch\s*(?:n/?a|non|free|zero)\b
    | \bcoors\s*(?:edge|n/?a|non|zero)\b
    | \bheineken\s*(?:zero|0\.?0|n/?a|non)\b
    | \b(?:zero|0\.?0|n/?a|non).*heineken\b
    | \berdinger\s*(?:non|alko|free|n/?a|zero)\b
    | \bbrooklyn\s*special\s*effects\b
    | \bpartake\s*(?:brew|pale|ipa|stout|blonde|red)\b | \bpartake\b
    | \bbravus\b
    | \bsurreal\s*brew\b | \bsurreal\b(?=.*(?:beer|brew|n/?a|non))
    | \bwellbeing\s*brew\b | \bwellbeing\b(?=.*(?:beer|brew|n/?a|non))
    | \bgruvi\b
    | \bbest\s*day\s*brew\b
    | \brescue\s*club\b
    | \buntitled\s*art\b(?=.*(?:n/?a|non|beer|brew))
    | \bsam\s*adams\s*(?:just|n/?a|zero)\b
    | \bguinness\s*(?:0|zero|n/?a|non)\b
    | \b(?:0|zero|n/?a|non).*guinness\b
    | \blagunitas\s*(?:hoppy|ipna|n/?a|non|zero)\b
    | \bipna\b
    | \bbrewdog\s*(?:punk|nanny|n/?a|zero|af)\b
    | \bnanny\s*state\b
    | \bbitburger\s*(?:drive|0|zero|n/?a)\b
    | \bpaulaner\s*(?:non|0|zero|n/?a|free)\b
    | \bkrombacher\s*(?:non|0|zero|n/?a|free)\b
    | \bweihenstephan\w*\s*(?:non|0|zero|n/?a|free)\b
    | \bbbudvar\s*(?:non|0|zero|n/?a|free)\b
    | \bsapporo\s*(?:premium\s*)?(?:non|0|zero|n/?a)\b
    | \bsuntory\s*(?:all[\s-]*free|non|zero)\b
    | \ball[\s-]*free\b(?=.*(?:beer|suntory))
    | \bsans\s*(?:beer|brew)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

NA_WINE_PATTERNS = re.compile(
    r"""
    # --- Generic NA wine terms ---
    \bnon[\s-]*alc(?:oholic)?\s*(?:wine|prosecco|champagne|sparkling|rosé?|red|white|sangria)\b
    | \balcohol[\s-]*free\s*(?:wine|prosecco|champagne|sparkling|rosé?|red|white)\b
    | \bzero[\s-]*(?:alc|alcohol|proof)\s*(?:wine|prosecco|sparkling|rosé?)\b
    | \bde[\s-]*alcohol\w*\s*(?:wine|prosecco|sparkling|champagne)\b
    | \b0[\s.]0\s*%?\s*(?:wine|prosecco|sparkling|champagne)\b

    # --- NA wine brands ---
    | \bfre\b(?=\s*(?:wine|chard|cab|merlot|brut|rosé?|sparkling|red|white|pinot))
    | \bariel\b(?=\s*(?:wine|chard|cab|merlot|brut|rosé?|sparkling|red|white))
    | \bsurely\b(?=.*(?:wine|sparkling|rosé?|brut|sauv|non|n/?a))
    | \bproxies\b
    | \bjukes\b(?=.*(?:cordialsetter|wine|non))
    | \bleitz\b(?=.*(?:eins|zero|non|n/?a))
    | \bnoughty\b
    | \bthomson\s*&?\s*scott\b
    | \bgrüvi\b(?=.*(?:wine|prosecco|rosé?|bubbly))
    | \bgruvi\b(?=.*(?:wine|prosecco|rosé?|bubbly))
    | \boldenburg\b(?=.*(?:non|n/?a|0|zero))
    | \bst\.?\s*regis\b(?=.*(?:wine|chard|cab|merlot|brut|sparkling))
    | \bgiesen\b(?=.*(?:non|zero|n/?a|0))
    """,
    re.IGNORECASE | re.VERBOSE,
)

NA_SPIRITS_PATTERNS = re.compile(
    r"""
    # --- Generic NA spirit terms ---
    \bnon[\s-]*alc(?:oholic)?\s*(?:spirit|whiskey|whisky|bourbon|gin|rum|tequila|vodka|aperitif|apéritif)\b
    | \balcohol[\s-]*free\s*(?:spirit|whiskey|whisky|bourbon|gin|rum|tequila|vodka)\b
    | \bzero[\s-]*proof\b
    | \bzero[\s-]*(?:alc|alcohol)\s*(?:spirit|whiskey|whisky|bourbon|gin|rum|tequila|vodka)\b

    # --- NA spirit brands ---
    | \bseedlip\b
    | \blyre'?s\b
    | \bmonday\b(?=\s*(?:gin|whiskey|mezcal|zero|non|spirit))
    | \britual\s*(?:zero|non)\b
    | \bspiritless\b
    | \bfree\s*spirits\b
    | \bceder'?s\b(?=.*(?:gin|spirit|non|alt|crisp|wild|classic))
    | \bagnesi\s*1799\b
    | \barkay\b(?=.*(?:zero|non|spirit))
    | \bben[\s-]*&?\s*lomond\b(?=.*(?:non|zero|spirit))
    | \bdhos\b
    | \bgist\b(?=.*(?:non|zero|spirit))
    | \boptimist\b(?=.*(?:bright|fresh|spirit|non|zero|botanica))
    | \bpathfinder\b(?=.*(?:hemp|spirit|non|zero))
    | \bproteau\b
    | \breal\s*(?:elf|spirit)\b(?=.*(?:non|zero))
    | \bthree\s*spirit\b
    | \bwilfred'?s\b
    | \bimpossibrew\b
    | \bceders\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

NA_COCKTAIL_PATTERNS = re.compile(
    r"""
    # --- Generic NA cocktail terms ---
    \bmocktail\b
    | \bnon[\s-]*alc(?:oholic)?\s*(?:cocktail|margarita|mojito|mule|spritz|paloma|negroni|old\s*fash)\b
    | \balcohol[\s-]*free\s*(?:cocktail|margarita|mojito|mule|spritz)\b
    | \bzero[\s-]*proof\s*(?:cocktail|margarita|mojito|mule|spritz|paloma)\b
    | \bvirgin\s+(?:margarita|mojito|mule|pina\s*colada|daiquiri|mary|cocktail|sangria|paloma|spritz)\b

    # --- NA cocktail / functional drink brands ---
    | \bcurious\s*elixir\b
    | \bkin\s*(?:euphorics|bloom|dream|lightwave|spritz)\b
    | \bghia\b
    | \bde\s*soi\b
    | \bhop\s*wtr\b | \bhopwtr\b
    | \blagunitas\s*hoppy\s*refresher\b
    | \bhella\s*(?:cocktail|bitters|spritz)\b
    | \bfree\s*rain\b
    | \bbetter\s*rhodes\b
    | \bsans\s*bar\b
    | \bwilderton\b
    | \bsovereign\b(?=.*(?:non|zero|mocktail))
    | \bsirene\b(?=.*(?:non|zero|mocktail|spirit))
    | \baplós\b | \baplos\b
    | \bst\.\s*agrestis\b
    | \bnon[\s-]*alc(?:oholic)?\s*(?:drink|beverage|option)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

PREMIUM_MIXER_PATTERNS = re.compile(
    r"""
    # --- Fever-Tree ---
    \bfever[\s-]*tree\b

    # --- Other premium mixer brands ---
    | \bq\s+(?:tonic|mixer|ginger|club|bitter|elderflower|hibiscus|grapefruit|lemon)\b
    | \bq\s+mixers?\b
    | \bfentimans?\b
    | \bjack\s*rudy\b
    | \bfee\s*brothers\b
    | \bregatta\b(?=.*(?:ginger|craft|mixer))
    | \bsquare\s*root\b(?=.*(?:tonic|soda|mixer))
    | \btop\s*note\b(?=.*(?:tonic|mixer))
    | \bstirring\w*\b(?=.*(?:tonic|ginger|mixer|soda))
    | \belderflower\s*tonic\b
    | \bindian\s*tonic\b
    | \bpremium\s*(?:tonic|mixer|ginger\s*beer|ginger\s*ale)\b
    | \bcraft\s*tonic\b
    | \btonic\s*water\b(?=.*(?:fever|premium|craft|artisan|q\s|fentiman))
    | \bbitter\s*lemon\b(?=.*(?:fever|premium|craft|fentiman))
    """,
    re.IGNORECASE | re.VERBOSE,
)

LOW_ALC_PATTERNS = re.compile(
    r"""
    # --- Low-alc / session / light designations ---
    \blow[\s-]*alc(?:ohol)?\b
    | \blight\s*beer\b.*\b(?:n/?a|non|zero|session)\b
    | \bsession\b(?=.*(?:ipa|ale|lager|beer|sour|brew))
    | \bmid[\s-]*strength\b
    | \bhalf[\s-]*(?:pint|strength)\b(?=.*(?:beer|ale|lager|ipa))

    # --- Radlers / Shandies ---
    | \bradler\b
    | \bshandy\b | \bshandies\b
    | \bstiegl\s*radler\b
    | \bschofferhofer\b | \bschöfferhofer\b

    # --- Specific low-alc brands ---
    | \brecreational\b(?=.*(?:beer|brew))
    | \bslightly\s*mighty\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

GENERIC_NA_PATTERNS = re.compile(
    r"""
    # --- Catch-all generic terms ---
    \bnon[\s-]*alcohol\w*\b
    | \balcohol[\s-]*free\b
    | \b0[\s.]0\s*%\b(?=.*(?:beer|wine|spirit|brew|prosecco|champagne|lager|ale|ipa))
    | \bn/?a\s+(?:option|alternative|version|selection)\b
    | \baf\b(?=\s*(?:beer|brew|lager|ale|ipa|wine|spirit))
    | \bzero\s*alcohol\b
    | \bno[\s-]*abv\b
    | \babv\s*0\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Order matters: more specific categories first
CATEGORIES = [
    ("na_beer", NA_BEER_PATTERNS),
    ("na_wine", NA_WINE_PATTERNS),
    ("na_spirits", NA_SPIRITS_PATTERNS),
    ("na_cocktail", NA_COCKTAIL_PATTERNS),
    ("premium_mixer", PREMIUM_MIXER_PATTERNS),
    ("low_alc", LOW_ALC_PATTERNS),
    ("generic_na", GENERIC_NA_PATTERNS),
]


def normalize(name: str) -> str:
    """Lowercase, strip, remove leading numeric/price prefixes."""
    s = name.strip().lower()
    s = re.sub(r"^\$[\d.]+\s*", "", s)
    s = re.sub(r"^\d+\s+\d+/\d+\s*", "", s)
    s = re.sub(r"^#\s*\d+\s*", "", s)
    return s.strip()


def classify(name: str) -> tuple[str | None, str | None]:
    """Return (category, matched_pattern) or (None, None) if not a non-alc drink."""
    normed = normalize(name)

    if EXCLUSIONS.search(normed):
        return None, None

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

    nonalc_items = []
    other_items = []
    category_counts: dict[str, int] = {}

    with open(INPUT, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            category, match = classify(name)
            if category:
                nonalc_items.append({"name": name, "category": category, "matched": match})
                category_counts[category] = category_counts.get(category, 0) + 1
            else:
                other_items.append({"name": name})

    # Write non-alc items
    nonalc_path = OUTPUT_DIR / "nonalc_items.csv"
    with open(nonalc_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "category", "matched"])
        writer.writeheader()
        writer.writerows(nonalc_items)

    # Write everything else
    other_path = OUTPUT_DIR / "nonalc_excluded_items.csv"
    with open(other_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name"])
        writer.writeheader()
        writer.writerows(other_items)

    # Summary
    total = len(nonalc_items) + len(other_items)
    print(f"\nClassified {total:,} items:")
    print(f"  Non-alc/Low-alc: {len(nonalc_items):,} ({len(nonalc_items)/total*100:.1f}%)")
    print(f"  Other:           {len(other_items):,} ({len(other_items)/total*100:.1f}%)")
    print(f"\nNon-alc by category:")
    for cat in ["na_beer", "na_wine", "na_spirits", "na_cocktail", "premium_mixer", "low_alc", "generic_na"]:
        count = category_counts.get(cat, 0)
        print(f"  {cat:16s} {count:,}")
    print(f"\nOutput:")
    print(f"  {nonalc_path}")
    print(f"  {other_path}")


if __name__ == "__main__":
    main()
