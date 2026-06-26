"""
Builds a structured WeekSummary from a validated WeeklyPlan.
Renders to Markdown (text export) or a dict suitable for JSON serialization (API).
"""

from dataclasses import dataclass
from datetime import date

from engine.catalogue import Catalogue, Product
from engine.constants import DAYS
from engine.output_format import Dish, TrackPlan, WeeklyPlan

_ALLERGEN_LABELS: dict[str, str] = {
    "allergen_gluten": "gluten",
    "allergen_nuts": "nuts",
    "allergen_dairy": "dairy",
}


@dataclass(frozen=True)
class IngredientDetail:
    product_id: int
    name: str
    quantity_g: float
    cost_eur: float
    calories_kcal: float
    allergens: list[str]


@dataclass(frozen=True)
class DishDetail:
    dish_name: str
    description: str
    ingredients: list[IngredientDetail]
    total_cost_eur: float
    total_calories_kcal: float
    allergens: list[str]


@dataclass(frozen=True)
class TrackSummary:
    dishes: dict[str, DishDetail]
    weekly_cost_eur: float
    weekly_calories_kcal: float
    allergens: list[str]


@dataclass(frozen=True)
class WeekSummary:
    week_start: date
    meat: TrackSummary
    vegetarian: TrackSummary


def _allergens_from_product(product: Product) -> list[str]:
    return [label for field, label in _ALLERGEN_LABELS.items() if product.get(field) == 1]


def _build_dish_detail(dish: Dish, catalogue: Catalogue) -> DishDetail:
    ingredient_details: list[IngredientDetail] = []
    for ing in dish.ingredients:
        product = catalogue.get_product_by_id(ing.product_id)
        if product is None:
            continue
        g = ing.quantity_g
        cost = round(product["cost_per_100g_eur"] * g / 100, 4)
        kcal = round(product["energy_kcal_per_100g"] * g / 100, 1)
        ingredient_details.append(
            IngredientDetail(
                product_id=ing.product_id,
                name=product["product_name"],
                quantity_g=g,
                cost_eur=cost,
                calories_kcal=kcal,
                allergens=_allergens_from_product(product),
            )
        )

    total_cost = round(sum(i.cost_eur for i in ingredient_details), 4)
    total_kcal = round(sum(i.calories_kcal for i in ingredient_details), 1)

    seen: set[str] = set()
    dish_allergens: list[str] = []
    for i in ingredient_details:
        for a in i.allergens:
            if a not in seen:
                seen.add(a)
                dish_allergens.append(a)

    return DishDetail(
        dish_name=dish.dish_name,
        description=dish.description,
        ingredients=ingredient_details,
        total_cost_eur=total_cost,
        total_calories_kcal=total_kcal,
        allergens=dish_allergens,
    )


def _build_track_summary(track: TrackPlan, catalogue: Catalogue) -> TrackSummary:
    dishes: dict[str, DishDetail] = {}
    for day in DAYS:
        dish = getattr(track, day)
        dishes[day] = _build_dish_detail(dish, catalogue)

    weekly_cost = round(sum(d.total_cost_eur for d in dishes.values()), 4)
    weekly_kcal = round(sum(d.total_calories_kcal for d in dishes.values()), 1)

    seen: set[str] = set()
    week_allergens: list[str] = []
    for d in dishes.values():
        for a in d.allergens:
            if a not in seen:
                seen.add(a)
                week_allergens.append(a)

    return TrackSummary(
        dishes=dishes,
        weekly_cost_eur=weekly_cost,
        weekly_calories_kcal=weekly_kcal,
        allergens=week_allergens,
    )


def build_summary(plan: WeeklyPlan, catalogue: Catalogue) -> WeekSummary:
    return WeekSummary(
        week_start=plan.week_start,
        meat=_build_track_summary(plan.meat, catalogue),
        vegetarian=_build_track_summary(plan.vegetarian, catalogue),
    )


def summary_to_dict(summary: WeekSummary, week_number: int) -> dict:
    """Serialize a WeekSummary to a JSON-compatible dict for the API."""

    def ing_to_dict(i: IngredientDetail) -> dict:
        return {
            "product_id": i.product_id,
            "name": i.name,
            "quantity_g": i.quantity_g,
            "cost_eur": i.cost_eur,
            "calories_kcal": i.calories_kcal,
            "allergens": i.allergens,
        }

    def dish_to_dict(d: DishDetail) -> dict:
        return {
            "dish_name": d.dish_name,
            "description": d.description,
            "ingredients": [ing_to_dict(i) for i in d.ingredients],
            "total_cost_eur": d.total_cost_eur,
            "total_calories_kcal": d.total_calories_kcal,
            "allergens": d.allergens,
        }

    def track_to_dict(t: TrackSummary) -> dict:
        return {
            "weekly_cost_eur": t.weekly_cost_eur,
            "weekly_calories_kcal": t.weekly_calories_kcal,
            "allergens": t.allergens,
            "dishes": {day: dish_to_dict(d) for day, d in t.dishes.items()},
        }

    return {
        "week_number": week_number,
        "week_start": summary.week_start.isoformat(),
        "meat": track_to_dict(summary.meat),
        "vegetarian": track_to_dict(summary.vegetarian),
    }


def to_markdown(summary: WeekSummary) -> str:
    lines: list[str] = [
        f"# Weekly Menu — {summary.week_start}",
        "",
    ]

    for track_name, track in [("Meat", summary.meat), ("Vegetarian", summary.vegetarian)]:
        lines.append(f"## {track_name} Track")
        lines.append(
            f"Weekly total: {track.weekly_cost_eur:.2f} EUR | "
            f"{track.weekly_calories_kcal:.0f} kcal"
        )
        if track.allergens:
            lines.append(f"Allergens this week: {', '.join(track.allergens)}")
        lines.append("")

        for day in DAYS:
            dish = track.dishes[day]
            allergen_note = f" | allergens: {', '.join(dish.allergens)}" if dish.allergens else ""
            meta = (
                f"  ({dish.total_cost_eur:.2f} EUR"
                f" | {dish.total_calories_kcal:.0f} kcal{allergen_note})"
            )
            lines.append(f"### {day.capitalize()} — {dish.dish_name}{meta}")
            for ing in dish.ingredients:
                allergen_note_ing = f" [{', '.join(ing.allergens)}]" if ing.allergens else ""
                lines.append(
                    f"  - {ing.name}: {ing.quantity_g:.0f}g"
                    f" — {ing.cost_eur:.2f} EUR | {ing.calories_kcal:.0f} kcal{allergen_note_ing}"
                )
            lines.append("")

    return "\n".join(lines)
