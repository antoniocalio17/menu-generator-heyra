import json
import os
import unittest
from unittest.mock import MagicMock, patch

from engine.catalogue import Catalogue
from engine.output_format import WeeklyPlan
from engine.groq_llama import PlannerError, _format_products, _prompt_messages, generate


def _make_product(**kwargs) -> dict:
    return {
        "product_id": 1,
        "product_name": "Chicken Breast",
        "ingredient_group": "poultry",
        "cost_per_100g_eur": 0.18,
        "energy_kcal_per_100g": 165.0,
        "dietary_class": "meat",
        "allergen_gluten": 0,
        "allergen_nuts": 0,
        "allergen_dairy": 0,
        **kwargs,
    }


def _veg(product_id: int, name: str, group: str) -> dict:
    return _make_product(
        product_id=product_id,
        product_name=name,
        ingredient_group=group,
        dietary_class="vegan",
    )


def _make_pools() -> dict:
    return {
        "meat": {
            "protein_meat": [_make_product()],
            "carb": [_veg(2, "Rice", "rices")],
            "vegetable": [_veg(3, "Broccoli", "vegetables")],
            "sauce": [_veg(4, "Olive Oil", "oils")],
        },
        "vegetarian": {
            "protein_veg": [_veg(5, "Lentils", "legumes")],
            "carb": [_veg(2, "Rice", "rices")],
            "vegetable": [_veg(3, "Broccoli", "vegetables")],
            "sauce": [_veg(4, "Olive Oil", "oils")],
        },
    }


def _valid_plan_json(week_start: str = "2024-01-15") -> str:
    dish = {
        "dish_name": "Test Dish",
        "ingredients": [
            {"product_id": 1, "quantity_g": 150.0},
            {"product_id": 2, "quantity_g": 100.0},
        ],
    }
    track = {day: dish for day in ("monday", "tuesday", "wednesday", "thursday", "friday")}
    return json.dumps({"week_start": week_start, "meat": track, "vegetarian": track})


class TestFormatProducts(unittest.TestCase):
    def test_contains_product_id(self) -> None:
        self.assertIn("id=1", _format_products([_make_product()]))

    def test_contains_product_name(self) -> None:
        self.assertIn("Chicken Breast", _format_products([_make_product()]))

    def test_no_allergens_shows_none(self) -> None:
        self.assertIn("allergens: none", _format_products([_make_product()]))

    def test_allergens_listed(self) -> None:
        result = _format_products([_make_product(allergen_gluten=1, allergen_dairy=1)])
        self.assertIn("gluten", result)
        self.assertIn("dairy", result)

    def test_empty_list_returns_empty_string(self) -> None:
        self.assertEqual(_format_products([]), "")


class TestBuildMessages(unittest.TestCase):
    def setUp(self) -> None:
        self.messages = _prompt_messages(_make_pools(), "2024-01-15", [])

    def test_two_messages(self) -> None:
        self.assertEqual(len(self.messages), 2)

    def test_correct_roles(self) -> None:
        self.assertEqual(self.messages[0]["role"], "system")
        self.assertEqual(self.messages[1]["role"], "user")

    def test_user_contains_week_start(self) -> None:
        self.assertIn("2024-01-15", self.messages[1]["content"])

    def test_user_contains_product_id(self) -> None:
        self.assertIn("id=1", self.messages[1]["content"])

    def test_user_contains_schema(self) -> None:
        self.assertIn("week_start", self.messages[1]["content"])

    def test_no_error_section_when_empty(self) -> None:
        self.assertNotIn("PREVIOUS ERRORS", self.messages[1]["content"])

    def test_errors_appended_on_retry(self) -> None:
        messages = _prompt_messages(_make_pools(), "2024-01-15", ["quantity_g must be > 0"])
        self.assertIn("PREVIOUS ERRORS", messages[1]["content"])
        self.assertIn("quantity_g must be > 0", messages[1]["content"])


_FAKE_ENV = {"GROQ_API_KEY": "test-key"}


class TestGenerate(unittest.TestCase):
    @patch.dict(os.environ, _FAKE_ENV)
    @patch("engine.groq_llama.OpenAI")
    def test_returns_weekly_plan(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.chat.completions.create.return_value.choices[
            0
        ].message.content = _valid_plan_json()
        result = generate("2024-01-15", catalogue=Catalogue())
        self.assertIsInstance(result, WeeklyPlan)

    @patch.dict(os.environ, _FAKE_ENV)
    @patch("engine.groq_llama.OpenAI")
    def test_retries_on_bad_schema(self, mock_cls: MagicMock) -> None:
        invalid = json.dumps({"week_start": "2024-01-15"})
        mock_cls.return_value.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=MagicMock(content=invalid))]),
            MagicMock(choices=[MagicMock(message=MagicMock(content=_valid_plan_json()))]),
        ]
        result = generate("2024-01-15", catalogue=Catalogue())
        self.assertIsInstance(result, WeeklyPlan)
        self.assertEqual(mock_cls.return_value.chat.completions.create.call_count, 2)

    @patch.dict(os.environ, _FAKE_ENV)
    @patch("engine.groq_llama.OpenAI")
    def test_raises_after_max_retries(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value.chat.completions.create.return_value.choices[
            0
        ].message.content = json.dumps({"bad": "schema"})
        with self.assertRaises(PlannerError):
            generate("2024-01-15", catalogue=Catalogue())


if __name__ == "__main__":
    unittest.main()
