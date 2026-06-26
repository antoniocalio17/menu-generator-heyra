import unittest

from parameterized import parameterized

from engine.catalogue import (
    Catalogue,
    IngredientInput,
)
from engine.constants import DISH_ROLES as _DISH_ROLES
from engine.constants import PROTEIN_ROLE as _PROTEIN_ROLE


class TestCatalogue(unittest.TestCase):
    cat: Catalogue

    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = Catalogue()

    def test_returns_at_most_n(self) -> None:
        results = self.cat.get_candidates_by_role("carb", "meat", n=5)
        self.assertLessEqual(len(results), 5)

    @parameterized.expand(
        [
            ("meat", "protein_meat"),
            ("vegetarian", "protein_veg"),
        ]
    )
    def test_track_roles(self, track: str, expected_protein_role: str) -> None:
        pools = self.cat.build_weekly_pools()
        expected = set([expected_protein_role] + _DISH_ROLES)
        self.assertEqual(set(pools[track].keys()), expected)

    @parameterized.expand(
        [
            ("protein_veg", "vegetarian", {"vegan", "vegetarian"}),
            ("protein_meat", "meat", {"meat"}),
        ]
    )
    def test_dietary_constraints(self, role: str, track: str, allowed: set[str]) -> None:
        results = self.cat.get_candidates_by_role(role, track, n=50)
        self.assertTrue(results)
        classes = {p["dietary_class"] for p in results}
        self.assertTrue(classes.issubset(allowed))

    def test_unknown_role_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown role"):
            self.cat.get_candidates_by_role("proteinn_veg", "meat")

    def test_unknown_track_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown track"):
            self.cat.get_candidates_by_role("carb", "vegitarian")

    def test_exclude_ids_respected(self) -> None:
        all_products = self.cat.get_candidates_by_role("carb", "meat", n=500)
        exclude = {all_products[0]["product_id"]}
        results = self.cat.get_candidates_by_role("carb", "meat", n=500, exclude_ids=exclude)
        returned_ids = {p["product_id"] for p in results}
        self.assertTrue(returned_ids.isdisjoint(exclude))

    def test_only_available_products_loaded(self) -> None:
        import pandas as pd

        from engine.catalogue import DATA_PATH

        df = pd.read_csv(DATA_PATH)
        unavailable_id = int(df[df["is_available"] == 0]["product_id"].iloc[0])
        self.assertIsNone(self.cat.get_product_by_id(unavailable_id))

    def test_unknown_product_raises(self) -> None:
        ingredient: IngredientInput = {"product_id": 9_999_999, "quantity_g": 100.0}
        with self.assertRaisesRegex(ValueError, "Unknown product_id"):
            self.cat.compute_meal_stats([ingredient])

    def test_protein_role_by_track(self) -> None:
        self.assertEqual(_PROTEIN_ROLE["meat"], "protein_meat")
        self.assertEqual(_PROTEIN_ROLE["vegetarian"], "protein_veg")


if __name__ == "__main__":
    unittest.main()
