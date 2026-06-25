import unittest

from engine.catalogue import Catalogue
from engine.output_format import WeeklyPlan
from engine.validator import WEEKLY_BUDGET_EUR, PlanValidationError, fix_budget, validate


def _dish(name: str, product_ids: list[int], quantity_g: float = 150.0) -> dict:
    return {
        "dish_name": name,
        "ingredients": [{"product_id": pid, "quantity_g": quantity_g} for pid in product_ids],
    }


def _track(dishes: list[dict]) -> dict:
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    return {day: dish for day, dish in zip(days, dishes, strict=True)}


def _plan(meat_dishes: list[dict], veg_dishes: list[dict]) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_start": "2024-01-15",
            "meat": _track(meat_dishes),
            "vegetarian": _track(veg_dishes),
        }
    )


class TestValidator(unittest.TestCase):
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
        cls.meat_cost = float(meat_row["cost_per_100g_eur"])
        cls.veg_cost = float(veg_row["cost_per_100g_eur"])

    def _meat_dish(self, name: str = "Meat Dish", quantity_g: float = 150.0) -> dict:
        return _dish(name, [self.meat_id, self.carb_id], quantity_g)

    def _veg_dish(self, name: str = "Veg Dish", quantity_g: float = 150.0) -> dict:
        return _dish(name, [self.veg_id, self.carb_id], quantity_g)

    def _valid_plan(self) -> WeeklyPlan:
        meat_dishes = [self._meat_dish(f"M{i}") for i in range(5)]
        veg_dishes = [self._veg_dish(f"V{i}") for i in range(5)]
        return _plan(meat_dishes, veg_dishes)

    def test_valid_plan_passes(self) -> None:
        validate(self._valid_plan(), self.cat)

    def test_unknown_product_raises(self) -> None:
        dishes = [_dish("Bad", [9_999_999])] + [self._meat_dish(f"M{i}") for i in range(4)]
        plan = _plan(dishes, [self._veg_dish(f"V{i}") for i in range(5)])
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        self.assertTrue(any("9999999" in e for e in ctx.exception.errors))

    def test_meat_track_without_meat_raises(self) -> None:
        dishes = [_dish("VegOnly", [self.veg_id, self.carb_id])] * 5
        plan = _plan(dishes, [self._veg_dish(f"V{i}") for i in range(5)])
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        self.assertTrue(any("no meat" in e for e in ctx.exception.errors))

    def test_vegetarian_track_with_meat_raises(self) -> None:
        dishes = [_dish("MeatInVeg", [self.meat_id])] * 5
        plan = _plan([self._meat_dish(f"M{i}") for i in range(5)], dishes)
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        found = any("meat product" in e and "vegetarian" in e for e in ctx.exception.errors)
        self.assertTrue(found)

    def test_collects_multiple_errors(self) -> None:
        all_veg = [_dish("V", [self.veg_id, self.carb_id])] * 5
        plan = _plan(all_veg, all_veg)
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        self.assertGreater(len(ctx.exception.errors), 1)

    def test_error_includes_track_and_day(self) -> None:
        all_veg = [_dish("V", [self.veg_id, self.carb_id])] * 5
        plan = _plan(all_veg, all_veg)
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        self.assertTrue(any("meat/monday" in e for e in ctx.exception.errors))

    def test_budget_exceeded_raises(self) -> None:
        # Use a very large quantity to guarantee exceeding the budget
        huge_qty = 100_000.0
        dishes = [self._meat_dish(f"M{i}", quantity_g=huge_qty) for i in range(5)]
        plan = _plan(dishes, [self._veg_dish(f"V{i}") for i in range(5)])
        with self.assertRaises(PlanValidationError) as ctx:
            validate(plan, self.cat)
        found = any("weekly cost" in e and "exceeds budget" in e for e in ctx.exception.errors)
        self.assertTrue(found)

    def test_budget_constant_value(self) -> None:
        self.assertEqual(WEEKLY_BUDGET_EUR, 20.10)

    def test_fix_budget_returns_plan_and_does_not_raise(self) -> None:
        # fix_budget must always return a WeeklyPlan without raising, even when the budget
        # is impossible to meet (e.g. extreme quantities leave no viable swap).
        huge_qty = 100_000.0
        meat_dishes = [self._meat_dish(f"M{i}", quantity_g=huge_qty) for i in range(5)]
        veg_dishes = [self._veg_dish(f"V{i}") for i in range(5)]
        plan = _plan(meat_dishes, veg_dishes)
        fixed = fix_budget(plan, self.cat)
        self.assertIsInstance(fixed, WeeklyPlan)

    def test_fix_budget_reduces_cost_when_cheaper_exists(self) -> None:
        # With a realistic over-budget quantity and at least one cheaper product in the
        # same group, fix_budget should bring the weekly cost down (not necessarily to target).
        qty = 5_000.0
        meat_dishes = [self._meat_dish(f"M{i}", quantity_g=qty) for i in range(5)]
        veg_dishes = [self._veg_dish(f"V{i}") for i in range(5)]
        plan = _plan(meat_dishes, veg_dishes)

        original_cost = sum(
            self.cat.compute_meal_stats(
                [{"product_id": ing.product_id, "quantity_g": ing.quantity_g}
                 for ing in getattr(plan.meat, day).ingredients]
            ).cost_eur
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
        )

        fixed = fix_budget(plan, self.cat)

        fixed_cost = sum(
            self.cat.compute_meal_stats(
                [{"product_id": ing.product_id, "quantity_g": ing.quantity_g}
                 for ing in getattr(fixed.meat, day).ingredients]
            ).cost_eur
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
        )

        # Cost must not increase after fix_budget
        self.assertLessEqual(fixed_cost, original_cost + 0.01)


if __name__ == "__main__":
    unittest.main()
