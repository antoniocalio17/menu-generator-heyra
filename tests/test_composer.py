import unittest
from typing import cast

from engine.catalogue import Catalogue, Product
from engine.composer import ComposedDish, compose_week
from engine.constants import CUISINE_ROTATION, MEAT_GROUPS
from engine.output_format import Dish


def _make_product(**kwargs: object) -> Product:
    return cast(Product, {
        "product_id": 1,
        "product_name": "Test Product",
        "ingredient_group": "meat",
        "cuisine_tag": "universal",
        "cost_per_100g_eur": 1.0,
        "energy_kcal_per_100g": 100.0,
        "dietary_class": "meat",
        "allergen_gluten": 0,
        "allergen_nuts": 0,
        "allergen_dairy": 0,
        **kwargs,
    })


class TestComposedDish(unittest.TestCase):

    def test_ingredient_set_returns_frozenset_of_ids(self) -> None:
        p1 = _make_product(product_id=10)
        p2 = _make_product(product_id=20)
        dish = ComposedDish(cuisine="asian", products=[(p1, 150.0), (p2, 120.0)])
        self.assertEqual(dish.ingredient_set(), frozenset({10, 20}))

    def test_ingredient_set_ignores_quantities(self) -> None:
        p = _make_product(product_id=5)
        dish_a = ComposedDish(cuisine="nordic", products=[(p, 100.0)])
        dish_b = ComposedDish(cuisine="nordic", products=[(p, 999.0)])
        self.assertEqual(dish_a.ingredient_set(), dish_b.ingredient_set())

    def test_to_dish_maps_name_and_ingredients(self) -> None:
        p1 = _make_product(product_id=1)
        p2 = _make_product(product_id=2)
        dish = ComposedDish(cuisine="mediterranean", products=[(p1, 150.0), (p2, 120.0)])
        result = dish.to_dish("Chicken Pasta")
        self.assertIsInstance(result, Dish)
        self.assertEqual(result.dish_name, "Chicken Pasta")
        self.assertEqual(len(result.ingredients), 2)
        self.assertEqual(result.ingredients[0].product_id, 1)
        self.assertEqual(result.ingredients[0].quantity_g, 150.0)
        self.assertEqual(result.ingredients[1].product_id, 2)
        self.assertEqual(result.ingredients[1].quantity_g, 120.0)


class TestComposeWeek(unittest.TestCase):
    cat: Catalogue
    meat_dishes: list[ComposedDish]
    veg_dishes: list[ComposedDish]

    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = Catalogue()
        cls.meat_dishes = compose_week("meat", cls.cat)
        cls.veg_dishes = compose_week("vegetarian", cls.cat)

    def test_returns_five_dishes_per_track(self) -> None:
        self.assertEqual(len(self.meat_dishes), 5)
        self.assertEqual(len(self.veg_dishes), 5)

    def test_each_dish_has_four_products(self) -> None:
        for dish in self.meat_dishes + self.veg_dishes:
            self.assertEqual(len(dish.products), 4)

    def test_all_dishes_have_unique_ingredient_sets(self) -> None:
        for track, dishes in [("meat", self.meat_dishes), ("vegetarian", self.veg_dishes)]:
            sets = [d.ingredient_set() for d in dishes]
            self.assertEqual(
                len(sets), len(set(sets)),
                f"{track}: duplicate ingredient sets found across the week",
            )

    def test_cuisine_follows_rotation(self) -> None:
        for dish, expected in zip(self.meat_dishes, CUISINE_ROTATION, strict=True):
            self.assertEqual(dish.cuisine, expected)
        for dish, expected in zip(self.veg_dishes, CUISINE_ROTATION, strict=True):
            self.assertEqual(dish.cuisine, expected)

    def test_meat_track_protein_is_from_meat_group(self) -> None:
        for i, dish in enumerate(self.meat_dishes):
            protein, _ = dish.products[0]
            self.assertIn(
                protein["ingredient_group"],
                MEAT_GROUPS,
                f"Day {i+1}: meat track protein '{protein['product_name']}' "
                f"is in group '{protein['ingredient_group']}' — not a meat group",
            )

    def test_vegetarian_track_contains_no_meat(self) -> None:
        for i, dish in enumerate(self.veg_dishes):
            for product, _ in dish.products:
                self.assertNotEqual(
                    product["dietary_class"],
                    "meat",
                    f"Day {i+1}: vegetarian track contains meat product "
                    f"'{product['product_name']}'",
                )

    def test_all_product_ids_exist_in_catalogue(self) -> None:
        for dish in self.meat_dishes + self.veg_dishes:
            for product, _ in dish.products:
                pid = product["product_id"]
                self.assertIsNotNone(
                    self.cat.get_product_by_id(pid),
                    f"product_id {pid} not found in catalogue",
                )

    def test_all_quantities_are_positive(self) -> None:
        for dish in self.meat_dishes + self.veg_dishes:
            for product, qty in dish.products:
                self.assertGreater(
                    qty, 0,
                    f"Non-positive quantity {qty}g for '{product['product_name']}'",
                )
