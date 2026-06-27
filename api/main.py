"""
FastAPI app — exposes the menu generation pipeline and serves the chef UI.
Run with: uvicorn api.main:app --reload  (from the menu-generator/ directory)
"""

import json
import logging
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.logging_config import setup_logging
from engine.catalogue import Catalogue
from engine.exporter import build_summary, summary_to_dict
from engine.fallback import FallbackError, build_fallback_plan
from engine.groq_llama import PlannerError, generate
from engine.output_format import WeeklyPlan
from engine.suggester import rename_dish, suggest_substitutes
from engine.validator import PlanValidationError, validate

MENUS_DIR = Path(__file__).parent.parent / "data" / "menus"
STATIC_DIR = Path(__file__).parent.parent / "web_app"
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"

setup_logging(LOG_DIR)
logger = logging.getLogger(__name__)

app = FastAPI(title="Heyra Menu Generator")
catalogue = Catalogue()
logger.info("Heyra Menu Generator started — catalogue loaded")


def _week_start(year: int, week: int) -> date:
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError as e:
        raise HTTPException(400, f"Invalid week {week} for year {year}") from e


def _menu_path(year: int, week: int) -> Path:
    return MENUS_DIR / f"{year}_w{week:02d}.json"


# Generation and Retrieval
@app.post("/api/generate/{year}/{week}")
def generate_week(year: int, week: int) -> dict:
    """Run the full pipeline for the given ISO year + week and store the result."""
    MENUS_DIR.mkdir(parents=True, exist_ok=True)
    week_start = _week_start(year, week)

    logger.info("Generate request — year=%d week=%d", year, week)
    fallback_used = False
    try:
        plan = generate(week_start.isoformat(), catalogue=catalogue)
        logger.info("LLM plan ready — year=%d week=%d", year, week)
    except PlannerError as planner_err:
        logger.warning("LLM failed (%s) — attempting fallback", planner_err)
        try:
            plan = build_fallback_plan(
                week_start.isoformat(),
                menus_dir=MENUS_DIR,
                exclude_path=_menu_path(year, week),
            )
            fallback_used = True
            logger.warning("Fallback plan built for year=%d week=%d", year, week)
        except FallbackError as fb_err:
            logger.error("Fallback failed: %s", fb_err)
            raise HTTPException(503, str(fb_err)) from fb_err

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        logger.warning("Validation failed for year=%d week=%d: %s", year, week, e.errors)
        raise HTTPException(422, {"errors": e.errors}) from e

    _menu_path(year, week).write_text(plan.model_dump_json())
    logger.info("Menu saved — year=%d week=%d fallback=%s", year, week, fallback_used)
    result = summary_to_dict(build_summary(plan, catalogue), week)
    if fallback_used:
        result["fallback"] = True
    return result


@app.get("/api/menu/{year}/{week}")
def get_week(year: int, week: int) -> dict:
    """Return the stored menu for a year+week (404 if not yet generated)."""
    path = _menu_path(year, week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")
    plan = WeeklyPlan.model_validate_json(path.read_text())
    return summary_to_dict(build_summary(plan, catalogue), week)


# ---------------------------------------------------------------------------
# Chef customization
# ---------------------------------------------------------------------------


class IngredientPayload(BaseModel):
    product_id: int
    quantity_g: float


class DishUpdate(BaseModel):
    dish_name: str
    description: str = ""
    ingredients: list[IngredientPayload]


@app.put("/api/menu/{year}/{week}/{track}/{day}")
def update_dish(year: int, week: int, track: str, day: str, body: DishUpdate) -> dict:
    """Chef edits a single dish. Validates constraints before saving."""
    path = _menu_path(year, week)
    if not path.exists():
        raise HTTPException(404, "Menu not generated yet for this week")

    if track not in ("meat", "vegetarian"):
        raise HTTPException(400, f"Unknown track: '{track}'")
    if day not in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        raise HTTPException(400, f"Unknown day: '{day}'")

    data = json.loads(path.read_text())
    data[track][day] = {
        "dish_name": body.dish_name,
        "description": body.description,
        "ingredients": [
            {"product_id": i.product_id, "quantity_g": i.quantity_g}
            for i in body.ingredients
        ],
    }

    try:
        plan = WeeklyPlan.model_validate(data)
    except Exception as e:
        raise HTTPException(422, {"errors": [str(e)]}) from e

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        raise HTTPException(422, {"errors": e.errors}) from e

    path.write_text(plan.model_dump_json())
    logger.info("Dish updated — year=%d week=%d %s/%s", year, week, track, day)
    return summary_to_dict(build_summary(plan, catalogue), week)


# ---------------------------------------------------------------------------
# AI ingredient substitution suggestions
# ---------------------------------------------------------------------------


class SuggestRequest(BaseModel):
    track: str
    target_product_id: int
    ingredients: list[IngredientPayload]


@app.post("/api/suggest")
def suggest(body: SuggestRequest) -> dict:
    """Return AI-ranked substitute candidates for one ingredient slot."""
    if body.track not in ("meat", "vegetarian"):
        raise HTTPException(400, f"Unknown track: '{body.track}'")

    ingredients = [
        {"product_id": i.product_id, "quantity_g": i.quantity_g}
        for i in body.ingredients
    ]

    try:
        candidates = suggest_substitutes(
            ingredients, body.target_product_id, body.track, catalogue
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error("Suggester error: %s", e)
        raise HTTPException(503, "AI suggestion unavailable — try again in a moment") from e

    logger.info(
        "Suggest — track=%s target=%d candidates=%d",
        body.track, body.target_product_id, len(candidates),
    )
    return {"candidates": candidates}


class RenameRequest(BaseModel):
    track: str
    ingredients: list[IngredientPayload]


@app.post("/api/rename-dish")
def rename(body: RenameRequest) -> dict:
    """Re-generate dish name and description after an ingredient swap."""
    if body.track not in ("meat", "vegetarian"):
        raise HTTPException(400, f"Unknown track: '{body.track}'")

    ingredients = [
        {"product_id": i.product_id, "quantity_g": i.quantity_g}
        for i in body.ingredients
    ]

    try:
        result = rename_dish(ingredients, body.track, catalogue)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error("Rename error: %s", e)
        raise HTTPException(503, "AI rename unavailable — try again in a moment") from e

    logger.info("Rename — track=%s → %s", body.track, result["dish_name"])
    return result


# ---------------------------------------------------------------------------
# Catalogue (used by the UI to populate ingredient search)
# ---------------------------------------------------------------------------


@app.get("/api/catalogue")
def get_catalogue() -> dict:
    return {"products": catalogue.get_all_products()}


# ---------------------------------------------------------------------------
# Static frontend — must be last so API routes take priority
# ---------------------------------------------------------------------------


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
