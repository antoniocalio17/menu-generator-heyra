"""
Composes weekly dish plans from the catalogue using weighted cuisine matching.

Each dish is built by picking one product per role (protein, carb, vegetable, sauce).
Products from the target cuisine get a higher selection weight; cross-cuisine
combinations are still possible but less likely.

The LLM is NOT involved here — it receives the composed dishes and only names them.
"""

import logging
import random
from dataclasses import dataclass, field

from engine.catalogue import Catalogue, Product
from engine.constants import CUISINE_ROTATION, DAYS, WEEKLY_BUDGET_EUR
from engine.output_format import Dish, Ingredient

logger = logging.getLogger(__name__)

_ROLE_QUANTITY: dict[str, float] = {
    "protein_meat": 100.0,
    "protein_veg":  100.0,
    "carb":          80.0,
    "vegetable":     60.0,
    "sauce":         10.0,
}

_WEIGHT_MATCH:     int = 3   
_WEIGHT_UNIVERSAL: int = 2   
_WEIGHT_OTHER:     int = 1   


class ComposerError(Exception):
    pass


@dataclass
class ComposedDish:
    """A fully formed dish (ingredients + quantities) waiting to be named by the LLM."""
    cuisine: str
    products: list[tuple[Product, float]] = field(default_factory=list)


    def ingredient_set(self) -> frozenset[int]:
        return frozenset(p["product_id"] for p, _ in self.products)

    def to_dish(self, name: str, description: str = "") -> Dish:
        return Dish(
            dish_name=name,
            description=description,
            ingredients=[
                Ingredient(product_id=p["product_id"], quantity_g=q)
                for p, q in self.products
            ],
        )


def _weighted_choice(products: list[Product], target_cuisine: str) -> Product:
    """Sample one product, giving higher weight to target-cuisine and universal products."""
    weights = []
    for p in products:
        tag = p["cuisine_tag"]
        if tag == target_cuisine:
            weights.append(_WEIGHT_MATCH)
        elif tag == "universal":
            weights.append(_WEIGHT_UNIVERSAL)
        else:
            weights.append(_WEIGHT_OTHER)
    return random.choices(products, weights=weights, k=1)[0]


def _compose_dish(
    track: str,
    cuisine: str,
    catalogue: Catalogue,
    seen_sets: list[frozenset[int]],
    max_attempts: int = 20,
) -> ComposedDish:
    """
    Build one ComposedDish for the given track and target cuisine.
    Retries up to max_attempts times to avoid duplicating a previously seen ingredient set.
    """
    protein_role = "protein_meat" if track == "meat" else "protein_veg"
    roles = [protein_role, "carb", "vegetable", "sauce"]

    # Pre-fetch candidate pools once (reused across attempts)
    pools: dict[str, list[Product]] = {
        role: catalogue.get_candidates_by_role(role, track, n=30)
        for role in roles
    }

    for role, pool in pools.items():
        if not pool:
            raise ComposerError(
                f"Empty candidate pool for role='{role}' track='{track}'. "
                "Check the catalogue CSV."
            )

    for attempt in range(1, max_attempts + 1):
        products = [
            (_weighted_choice(pools[role], cuisine), _ROLE_QUANTITY[role])
            for role in roles
        ]
        dish = ComposedDish(cuisine=cuisine, products=products)
        if dish.ingredient_set() not in seen_sets:
            if attempt > 1:
                logger.debug(
                    "Unique dish found on attempt %d (track=%s cuisine=%s)",
                    attempt, track, cuisine,
                )
            return dish
        logger.debug(
            "Duplicate ingredient set on attempt %d — retrying (track=%s cuisine=%s)",
            attempt, track, cuisine,
        )

    raise ComposerError(
        f"Could not compose a unique dish for track='{track}' cuisine='{cuisine}' "
        f"after {max_attempts} attempts."
    )


def _fit_protein_to_budget(dish: ComposedDish) -> ComposedDish:
    """Scale protein quantity down if this dish alone would bust the daily budget."""
    daily_budget = WEEKLY_BUDGET_EUR / len(DAYS)
    fixed_cost = sum(p["cost_per_100g_eur"] * qty / 100 for p, qty in dish.products[1:])
    remaining = daily_budget - fixed_cost
    protein, protein_qty = dish.products[0]
    if protein["cost_per_100g_eur"] * protein_qty / 100 <= remaining:
        return dish
    new_qty = round(remaining / (protein["cost_per_100g_eur"] / 100), 1)
    logger.debug(
        "Protein qty capped %.0fg→%.1fg (%s) to fit daily budget",
        protein_qty, new_qty, protein["product_name"],
    )
    return ComposedDish(cuisine=dish.cuisine, products=[(protein, new_qty)] + list(dish.products[1:]))


def compose_single_dish(
    track: str,
    cuisine: str,
    catalogue: Catalogue,
    seen_sets: list[frozenset[int]],
) -> ComposedDish:
    """Re-compose one dish slot (used when LLM flags a dish as incoherent)."""
    return _compose_dish(track, cuisine, catalogue, seen_sets)


def compose_week(track: str, catalogue: Catalogue) -> list[ComposedDish]:
    """
    Compose 5 distinct dishes for one track, cycling through cuisine targets.
    Returns a list of 5 ComposedDish objects in day order (Mon → Fri).
    """
    logger.info("Composing week — track=%s", track)
    seen_sets: list[frozenset[int]] = []
    dishes: list[ComposedDish] = []

    for day, cuisine in zip(DAYS, CUISINE_ROTATION, strict=True):
        dish = _fit_protein_to_budget(_compose_dish(track, cuisine, catalogue, seen_sets))
        seen_sets.append(dish.ingredient_set())
        dishes.append(dish)
        ingredients_str = " + ".join(p["product_name"] for p, _ in dish.products)
        logger.info(
            "  %s [%s]: %s",
            day.capitalize(), cuisine, ingredients_str,
        )

    logger.info("Composition complete — track=%s (%d dishes)", track, len(dishes))
    return dishes
