"""
This module is used to sample at random n products for each role in the menu.
We are retrieving the data to pass it to the LLM to generate the menu.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import pandas as pd

from engine.constants import DISH_ROLES, PROTEIN_ROLE, ROLE_GROUPS, VEGETARIAN_CLASSES

DATA_PATH = Path(__file__).parent.parent / "data" / "products.csv"


class Product(TypedDict):
    product_id: int
    product_name: str
    ingredient_group: str
    cuisine_tag: str
    cost_per_100g_eur: float
    energy_kcal_per_100g: float
    dietary_class: str
    allergen_gluten: int
    allergen_nuts: int
    allergen_dairy: int


class IngredientInput(TypedDict):
    product_id: int
    quantity_g: float


@dataclass(frozen=True)
class MealStats:
    cost_eur: float
    calories_kcal: float


TrackPool = dict[str, list[Product]]
WeeklyPools = dict[str, TrackPool]

_COLUMNS: list[str] = list(Product.__annotations__)


class Catalogue:
    def __init__(self, csv_path: Path = DATA_PATH) -> None:
        df = pd.read_csv(csv_path)
        self._df: pd.DataFrame = df[df["is_available"] == 1].reset_index(drop=True)
        self._by_id: pd.DataFrame = self._df.set_index("product_id")

    def get_candidates_by_role(
        self,
        role: str,
        track: str,
        n: int = 15,
        exclude_ids: set[int] | None = None,
    ) -> list[Product]:
        if role not in ROLE_GROUPS:
            raise ValueError(f"Unknown role '{role}'. Valid: {sorted(ROLE_GROUPS)}")
        if track not in PROTEIN_ROLE:
            raise ValueError(f"Unknown track '{track}'. Valid: {sorted(PROTEIN_ROLE)}")
        df = self._df[self._df["ingredient_group"].isin(ROLE_GROUPS[role])].copy()
        if track == "vegetarian":
            df = df[df["dietary_class"].isin(VEGETARIAN_CLASSES)]
        elif role == "protein_meat":
            df = df[df["dietary_class"] == "meat"]
        if exclude_ids:
            df = df[df["product_id"].map(lambda pid: pid not in exclude_ids)]
        if df.empty:
            return []
        return cast(list[Product], df.sample(min(n, len(df)))[_COLUMNS].to_dict("records"))

    def build_weekly_pools(
        self,
        n_per_role: int = 15,
        exclude_ids: set[int] | None = None,
    ) -> WeeklyPools:
        def _pool(track: str) -> TrackPool:
            roles = [PROTEIN_ROLE[track]] + DISH_ROLES
            return {
                role: self.get_candidates_by_role(
                    role, track, n=n_per_role, exclude_ids=exclude_ids
                )
                for role in roles
            }
        return {"meat": _pool("meat"), "vegetarian": _pool("vegetarian")}

    def get_product_by_id(self, product_id: int) -> Product | None:
        try:
            row = self._by_id.loc[product_id].to_dict()
            row["product_id"] = product_id
            return cast(Product, row)
        except KeyError:
            return None

    def get_cheaper_in_group(
        self, ingredient_group: str, max_cost: float, track: str
    ) -> list[Product]:
        """Return all products in the same ingredient_group costing less than max_cost.
        Sorted cheapest first. Vegetarian track is filtered to vegan/vegetarian only.
        """
        df = self._df[self._df["ingredient_group"] == ingredient_group].copy()
        if track == "vegetarian":
            df = df[df["dietary_class"].isin(VEGETARIAN_CLASSES)]
        df = df[df["cost_per_100g_eur"] < max_cost]
        df = df.sort_values("cost_per_100g_eur")
        return cast(list[Product], df[_COLUMNS].to_dict("records"))

    def get_products_by_group(
        self,
        group: str,
        track: str,
        exclude_ids: set[int] | None = None,
        limit: int = 20,
    ) -> list[Product]:
        """All available products in the given ingredient_group, filtered by track."""
        df = self._df[self._df["ingredient_group"] == group].copy()
        if track == "vegetarian":
            df = df[df["dietary_class"].isin(VEGETARIAN_CLASSES)]
        if exclude_ids:
            df = df[df["product_id"].map(lambda pid: pid not in exclude_ids)]
        return cast(list[Product], df[_COLUMNS].head(limit).to_dict("records"))

    def get_all_products(self) -> list[Product]:
        return cast(list[Product], self._df[_COLUMNS].to_dict("records"))

    def compute_meal_stats(self, ingredients: list[IngredientInput]) -> MealStats:
        cost = kcal = 0.0
        for item in ingredients:
            product = self.get_product_by_id(item["product_id"])
            if product is None:
                raise ValueError(f"Unknown product_id: {item['product_id']}")
            g = item["quantity_g"]
            cost += product["cost_per_100g_eur"] * g / 100
            kcal += product["energy_kcal_per_100g"] * g / 100
        return MealStats(cost_eur=round(cost, 4), calories_kcal=round(kcal, 1))
