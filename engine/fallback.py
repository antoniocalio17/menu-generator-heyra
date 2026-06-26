"""
Fallback plan builder — used when the LLM is for some reason unavailable.
Samples distinct dishes from previously saved weekly menus.
"""

import logging
import random
from pathlib import Path

from engine.constants import DAYS
from engine.output_format import Dish, WeeklyPlan

logger = logging.getLogger(__name__)


class FallbackError(Exception):
    pass


def _load_past_dishes(menus_dir: Path, exclude_path: Path | None) -> dict[str, list[Dish]]:
    """Collect every dish from all saved menus, skipping the current week's file."""
    pool: dict[str, list[Dish]] = {"meat": [], "vegetarian": []}
    loaded = 0

    for path in sorted(menus_dir.glob("*.json")):
        if path == exclude_path:
            continue
        try:
            plan = WeeklyPlan.model_validate_json(path.read_text())
        except Exception as e:
            logger.warning("Skipping unreadable menu file %s: %s", path.name, e)
            continue
        for day in DAYS:
            pool["meat"].append(getattr(plan.meat, day))
            pool["vegetarian"].append(getattr(plan.vegetarian, day))
        loaded += 1

    logger.debug("Loaded dishes from %d past menu file(s)", loaded)
    return pool


def _pick_distinct(dishes: list[Dish], n: int) -> list[Dish]:
    """Pick n dishes with unique ingredient sets (by product_id), in random order."""
    shuffled = list(dishes)
    random.shuffle(shuffled)
    seen: set[frozenset[int]] = set()
    result: list[Dish] = []
    for dish in shuffled:
        key = frozenset(ing.product_id for ing in dish.ingredients)
        if key not in seen:
            seen.add(key)
            result.append(dish)
            if len(result) == n:
                return result
    raise FallbackError(
        f"Not enough distinct past dishes to build a fallback menu "
        f"(need {n}, found {len(result)} unique across all saved weeks)"
    )


def build_fallback_plan(
    week_start: str,
    menus_dir: Path,
    exclude_path: Path | None = None,
) -> WeeklyPlan:
    """
    Build a WeeklyPlan by randomly sampling distinct dishes from past weeks.
    Raises FallbackError if there are not enough saved menus to draw from.
    """
    pool = _load_past_dishes(menus_dir, exclude_path)

    meat_dishes = _pick_distinct(pool["meat"], n=5)
    veg_dishes = _pick_distinct(pool["vegetarian"], n=5)
    logger.info(
        "Fallback plan assembled — %d meat dishes, %d veg dishes",
        len(meat_dishes), len(veg_dishes),
    )

    data = {
        "week_start": week_start,
        "meat": {day: dish.model_dump() for day, dish in zip(DAYS, meat_dishes, strict=True)},
        "vegetarian": {day: dish.model_dump() for day, dish in zip(DAYS, veg_dishes, strict=True)},
    }
    return WeeklyPlan.model_validate(data)
