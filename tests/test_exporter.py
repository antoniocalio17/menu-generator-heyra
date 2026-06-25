import unittest

from engine.catalogue import Catalogue
from engine.exporter import WeekSummary, build_summary, summary_to_dict, to_markdown
from engine.output_format import WeeklyPlan

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def _dish(name: str, product_ids: list[int], quantity_g: float = 150.0) -> dict:
    return {
        "dish_name": name,
        "ingredients": [{"product_id": pid, "quantity_g": quantity_g} for pid in product_ids],
    }


def _track(dishes: list[dict]) -> dict:
    return {day: dish for day, dish in zip(_DAYS, dishes, strict=True)}


class TestExporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = Catalogue()
        df = cls.cat._df
        meat_row = df[df["ingredient_group"].isin(["meat", "poultry"])].iloc[0]
        veg_row = df[df["dietary_class"] == "vegan"].iloc[0]
        carb_row = df[df["ingredient_group"].isin(["rices", "pastas"])].iloc[0]
        cls.meat_id = int(meat_row["product_id"])
        cls.veg_id = int(veg_row["product_id"])
        cls.carb_id = int(carb_row["product_id"])

    def _make_plan(self) -> WeeklyPlan:
        return WeeklyPlan.model_validate(
            {
                "week_start": "2024-01-15",
                "meat": _track([_dish(f"M{i}", [self.meat_id, self.carb_id]) for i in range(5)]),
                "vegetarian": _track(
                    [_dish(f"V{i}", [self.veg_id, self.carb_id]) for i in range(5)]
                ),
            }
        )

    def test_build_summary_returns_week_summary(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        self.assertIsInstance(summary, WeekSummary)

    def test_summary_has_five_days_per_track(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        self.assertEqual(len(summary.meat.dishes), 5)
        self.assertEqual(len(summary.vegetarian.dishes), 5)

    def test_dish_cost_is_positive(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        for dish in summary.meat.dishes.values():
            self.assertGreater(dish.total_cost_eur, 0)

    def test_dish_calories_is_positive(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        for dish in summary.meat.dishes.values():
            self.assertGreater(dish.total_calories_kcal, 0)

    def test_weekly_cost_equals_sum_of_dishes(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        expected = round(sum(d.total_cost_eur for d in summary.meat.dishes.values()), 4)
        self.assertAlmostEqual(summary.meat.weekly_cost_eur, expected, places=3)

    def test_ingredient_detail_has_product_id(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        for dish in summary.meat.dishes.values():
            for ing in dish.ingredients:
                self.assertIsInstance(ing.product_id, int)
                self.assertGreater(ing.product_id, 0)

    def test_ingredient_name_is_non_empty_string(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        for dish in summary.meat.dishes.values():
            for ing in dish.ingredients:
                self.assertIsInstance(ing.name, str)
                self.assertTrue(len(ing.name) > 0)

    def test_allergens_are_valid_labels(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        valid = {"gluten", "nuts", "dairy"}
        for dish in summary.meat.dishes.values():
            for a in dish.allergens:
                self.assertIn(a, valid)

    def test_to_markdown_contains_week_start(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        self.assertIn("2024-01-15", to_markdown(summary))

    def test_to_markdown_contains_both_tracks(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        md = to_markdown(summary)
        self.assertIn("Meat Track", md)
        self.assertIn("Vegetarian Track", md)

    def test_to_markdown_contains_all_days(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        md = to_markdown(summary)
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            self.assertIn(day, md)

    def test_summary_to_dict_structure(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        d = summary_to_dict(summary, 3)
        self.assertEqual(d["week_number"], 3)
        self.assertEqual(d["week_start"], "2024-01-15")
        self.assertIn("meat", d)
        self.assertIn("vegetarian", d)
        self.assertIn("dishes", d["meat"])
        self.assertIn("monday", d["meat"]["dishes"])

    def test_summary_to_dict_ingredients_have_product_id(self) -> None:
        summary = build_summary(self._make_plan(), self.cat)
        d = summary_to_dict(summary, 1)
        monday = d["meat"]["dishes"]["monday"]
        for ing in monday["ingredients"]:
            self.assertIn("product_id", ing)
            self.assertIsInstance(ing["product_id"], int)

    def test_summary_to_dict_is_json_serializable(self) -> None:
        import json
        summary = build_summary(self._make_plan(), self.cat)
        d = summary_to_dict(summary, 1)
        # Should not raise
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()
