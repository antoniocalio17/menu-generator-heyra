"""
JSON schema that the LLM must return, validated by Pydantic.
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    product_id: int
    quantity_g: Annotated[float, Field(gt=0)]


class Dish(BaseModel):
    dish_name: Annotated[str, Field(min_length=1)]
    description: str = ""
    ingredients: Annotated[list[Ingredient], Field(min_length=1)]
    needs_review: bool = False
    chef_note: str = ""


class TrackPlan(BaseModel):
    monday: Dish
    tuesday: Dish
    wednesday: Dish
    thursday: Dish
    friday: Dish


class WeeklyPlan(BaseModel):
    week_start: date
    meat: TrackPlan
    vegetarian: TrackPlan
