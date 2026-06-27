"""
Validates a WeeklyPlan against the catalogue.
Checks that all product_ids exist, meat track has meat, vegetarian track has no meat.
"""

from engine.catalogue import Catalogue
from engine.constants import DAYS, MEAT_GROUPS
from engine.output_format import Dish, TrackPlan, WeeklyPlan


class PlanValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def validate(plan: WeeklyPlan, catalogue: Catalogue) -> None:
    """Raise PlanValidationError listing all constraint violations found in the plan."""
    errors: list[str] = []
    _check_track(plan.meat, "meat", catalogue, errors)
    _check_track(plan.vegetarian, "vegetarian", catalogue, errors)
    if errors:
        raise PlanValidationError(errors)


def _check_track(
    track: TrackPlan, track_name: str, catalogue: Catalogue, errors: list[str]
) -> None:
    for day in DAYS:
        _check_dish(getattr(track, day), day, track_name, catalogue, errors)


def _check_dish(
    dish: Dish, day: str, track_name: str, catalogue: Catalogue, errors: list[str]
) -> None:
    has_meat_protein = False

    for ing in dish.ingredients:
        product = catalogue.get_product_by_id(ing.product_id)
        if product is None:
            errors.append(
                f"{track_name}/{day}/{dish.dish_name}: "
                f"product_id {ing.product_id} not found in catalogue"
            )
            continue

        if product["ingredient_group"] in MEAT_GROUPS:
            has_meat_protein = True

        if track_name == "vegetarian" and product["dietary_class"] == "meat":
            errors.append(
                f"{track_name}/{day}/{dish.dish_name}: "
                f"'{product['product_name']}' (id={ing.product_id}) is a meat product "
                f"— not allowed in the vegetarian track"
            )

    if track_name == "meat" and not has_meat_protein:
        errors.append(
            f"{track_name}/{day}/{dish.dish_name}: "
            f"no meat/poultry/fish/seafood/charcuterie ingredient found"
        )
