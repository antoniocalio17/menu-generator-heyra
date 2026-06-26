"""
EDA — ingredient group cuisine mapping.

Run with: python eda.py
Prints a summary of each ingredient group and the assigned cuisine tag,
then writes the enriched products.csv in-place (adds cuisine_tag column).
"""

from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).parent / "data" / "products.csv"

# ── Cuisine tag mapping ───────────────────────────────────────────────────────
# One tag per ingredient group.
# "universal" = ingredient fits any cuisine and is used as a fallback
# when a cuisine pool is thin during dish composition.

CUISINE_BY_GROUP: dict[str, str] = {
    # ── Proteins — meat ───────────────────────────────────────────────────────
    "meat":                 "universal",       # beef / lamb / pork — used in all cuisines
    "poultry":              "universal",       # chicken / turkey — used in all cuisines
    "fish":                 "nordic",          # salmon, cod, trout — Northern European
    "seafood":              "mediterranean",   # shrimp, prawns, mussels — Med / Asian coasts
    "charcuterie":          "nordic",          # bacon, pancetta, cured meats — Northern EU

    # ── Proteins — vegetarian ─────────────────────────────────────────────────
    "legumes":              "middle_eastern",  # chickpeas, lentils, beans
    "eggs":                 "universal",
    "plant proteins":       "asian",           # tofu, tempeh, seitan
    "cheeses":              "mediterranean",   # mozzarella, feta, parmesan
    "nuts":                 "middle_eastern",  # almonds, cashews, pine nuts

    # ── Carbs ─────────────────────────────────────────────────────────────────
    "grains":               "middle_eastern",  # bulgur, farro, couscous
    "rices":                "asian",           # jasmine, basmati, white rice
    "pastas":               "mediterranean",   # spaghetti, penne, gnocchi
    "breads":               "universal",       # pita, baguette, flatbread — all cuisines

    # ── Vegetables ────────────────────────────────────────────────────────────
    "vegetables":           "universal",
    "mushrooms":            "asian",           # shiitake, oyster — Asian-forward

    # ── Sauces & condiments ───────────────────────────────────────────────────
    "sauces":               "mediterranean",   # tomato sauce, marinara
    "condiments":           "universal",       # mustard, vinegar, hot sauce
    "oils":                 "mediterranean",   # olive oil dominant
    "herbs":                "mediterranean",   # basil, oregano, thyme, rosemary
    "spices":               "middle_eastern",  # cumin, turmeric, coriander, paprika
    "creams and butters":   "nordic",          # heavy cream, butter — Northern European
    "milks":                "universal",
    "yogurts":              "middle_eastern",  # labneh, tzatziki base
    "sweeteners":           "universal",
    "flours":               "universal",
    "seeds":                "universal",       # chia, flax, hemp — cross-cuisine
    "fruits":               "universal",
    "plant-based beverages":"universal",
}

# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    df = pd.read_csv(CSV_PATH)

    print("=" * 70)
    print("INGREDIENT GROUPS — cuisine tag assignment")
    print("=" * 70)

    tag_counts: dict[str, int] = {}

    for group in sorted(df["ingredient_group"].unique()):
        tag = CUISINE_BY_GROUP.get(group, "UNMAPPED")
        samples = df[df["ingredient_group"] == group]["product_name"].head(3).tolist()
        count = int((df["ingredient_group"] == group).sum())
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        print(f"\n  {group:<25} → [{tag}]  ({count} products)")
        for s in samples:
            print(f"      • {s}")

    unmapped = [g for g in df["ingredient_group"].unique() if g not in CUISINE_BY_GROUP]
    if unmapped:
        print(f"\n  WARNING — unmapped groups: {unmapped}")
        return

    print("\n" + "=" * 70)
    print("TAG DISTRIBUTION across groups")
    print("=" * 70)
    for tag, n in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:<20} {n} groups")

    print("\n" + "=" * 70)
    print(f"Writing cuisine_tag to {CSV_PATH} ...")
    df["cuisine_tag"] = df["ingredient_group"].map(CUISINE_BY_GROUP)
    df.to_csv(CSV_PATH, index=False)
    print("Done.")


if __name__ == "__main__":
    main()
