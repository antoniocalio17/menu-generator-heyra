"""
Shared constants used across engine modules.
Import from here — do not redefine in individual modules.
"""

# LLM prompts
NAMING_SYSTEM_PROMPT = (
    "You are a creative professional chef reviewing pre-composed canteen dishes.\n"
    "For each dish you receive a list of ingredients already selected. Your job:\n"
    "1. Give the dish an appetizing, creative name (3-6 words). "
    "Vary your naming style across dishes — avoid repeating the same pattern "
    "(e.g. do not always lead with a cooking verb). "
    "Draw from different styles: ingredient-led, regional, technique-led, or evocative.\n"
    "2. Write a 1-2 sentence recipe overview — mention the key cooking technique "
    "(e.g. pan-seared, slow-cooked, roasted, marinated) and how the components come together. "
    "If contrasting flavour notes are present (e.g. salty + acidic, creamy + spicy), briefly "
    "mention how they are balanced. Be concise and practical. Do NOT describe the eating "
    "experience, do NOT add generic closing sentences like 'creating a delicious meal'.\n"
    "3. Return the ingredient IDs exactly as given — you may drop one if it truly does not"
    " belong\n"
    "4. A skilled chef can make most combinations work — default to valid=true and show how "
    "the flavours (salty, acidic, creamy, bitter, sweet, umami) come together. "
    "Mark valid=false ONLY when there is genuinely no culinary technique that could make this "
    "a coherent savoury main dish: e.g. sweet dessert elements (jam, chocolate, ice cream, "
    "candy) paired with a savoury protein, or components that are simply inedible together "
    "regardless of technique. Bold or unusual pairings are a creative challenge — not a "
    "reason to reject. Provide a brief reason only when marking invalid.\n"
    "Respond with a JSON object only."
)

NAMING_OUTPUT_FORMAT = (
    'Return a JSON object with exactly this structure:\n'
    '{\n'
    '  "meat": [\n'
    '    {"dish_name": "...", "description": "...", "ingredients": [id1, id2, id3, id4],'
    ' "valid": true},\n'
    '    ... (5 objects total, one per day Mon-Fri)\n'
    '  ],\n'
    '  "vegetarian": [\n'
    '    {"dish_name": "...", "description": "...", "ingredients": [id1, id2, id3, id4],'
    ' "valid": true},\n'
    '    ... (5 objects total, one per day Mon-Fri)\n'
    '  ]\n'
    '}\n'
    'Add "reason": "..." only when valid=false. Preserve dish order.'
)

RENAME_SYSTEM_PROMPT = (
    "You are a professional canteen chef. "
    "Name and briefly describe a dish based on its ingredients. "
    "Respond with JSON only."
)

RENAME_SCHEMA = (
    '\n\nGive this dish:\n'
    '1. A creative name (3-6 words)\n'
    '2. A 1-2 sentence description — mention the key cooking technique and how '
    'the components come together. Be concise. No generic closing sentences.\n\n'
    'Return JSON only:\n'
    '{ "dish_name": "...", "description": "..." }'
)

SUGGEST_SCHEMA = (
    '\nReturn JSON:\n'
    '{\n'
    '  "candidates": [\n'
    '    { "product_id": <int from pool>, "reason": "..." },\n'
    '    ...\n'
    '  ]\n'
    '}'
)

# Variables

DAYS: list[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]

VEGETARIAN_CLASSES: frozenset[str] = frozenset({"vegan", "vegetarian"})

PROTEIN_ROLE: dict[str, str] = {
    "meat": "protein_meat",
    "vegetarian": "protein_veg",
}

DISH_ROLES: list[str] = ["carb", "vegetable", "sauce"]

# All 29 ingredient groups mapped to the 5 recipe roles.
ROLE_GROUPS: dict[str, list[str]] = {
    "protein_meat": ["meat", "poultry", "fish", "seafood", "charcuterie"],
    "protein_veg":  ["legumes", "eggs", "plant proteins", "cheeses", "nuts"],
    "carb":         ["grains", "rices", "pastas", "breads"],
    "vegetable":    ["vegetables", "mushrooms"],
    "sauce": [
        "sauces",
        "condiments",
        "oils",
        "herbs",
        "spices",
        "creams and butters",
        "yogurts",
    ],
}

# Ingredient groups that count as meat protein (used by validator)
MEAT_GROUPS: frozenset[str] = frozenset(ROLE_GROUPS["protein_meat"])

# Weekly budget considering 35dkk per meal per employee (4.68€)
WEEKLY_BUDGET_EUR: float = 20.10

# Cuisine target per day slot (Mon→Fri). Mediterranean appears twice — richest pool.
CUISINE_ROTATION: list[str] = [
    "mediterranean",
    "asian",
    "nordic",
    "middle_eastern",
    "mediterranean",
]
