"""
Calls the Groq LLM to name and describe pre-composed dishes.
The composer builds the ingredient sets; the LLM only handles naming,
description, and coherence validation.
"""

import logging
import os
import time
from pathlib import Path
from typing import Annotated, cast

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, Field, ValidationError

from engine.catalogue import Catalogue
from engine.composer import ComposedDish, ComposerError, compose_single_dish, compose_week
from engine.constants import CUISINE_ROTATION, DAYS
from engine.output_format import WeeklyPlan

load_dotenv(Path(__file__).parent / ".env")

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL = "llama-3.3-70b-versatile"
_TEMPERATURE = 0.4
_MAX_RETRIES = 3
_RATE_LIMIT_BACKOFF: list[float] = [2.0, 5.0, 10.0]

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    pass

class NamedDish(BaseModel):
    dish_name: Annotated[str, Field(min_length=1)]
    description: str
    ingredients: list[int]
    valid: bool
    reason: str = ""


class NamingResponse(BaseModel):
    meat: Annotated[list[NamedDish], Field(min_length=5, max_length=5)]
    vegetarian: Annotated[list[NamedDish], Field(min_length=5, max_length=5)]


def _format_dish(dish: ComposedDish, idx: int) -> str:
    lines = [f"Dish {idx} [{dish.cuisine}]"]
    for product, qty in dish.products:
        lines.append(
            f"  {product['ingredient_group']} ({qty:.0f}g): "
            f"{product['product_name']} (id={product['product_id']})"
        )
    return "\n".join(lines)


def _prompt(
    meat_dishes: list[ComposedDish],
    veg_dishes: list[ComposedDish],
    errors: list[str],
) -> list[ChatCompletionMessageParam]:
    system = (
        "You are a creative professional chef reviewing pre-composed canteen dishes.\n"
        "For each dish you receive a list of ingredients already selected. Your job:\n"
        "1. Give the dish an appetizing, creative name (3-6 words)\n"
        "2. Write a 1-2 sentence recipe overview — mention the key cooking technique "
        "(e.g. pan-seared, slow-cooked, roasted, marinated) and how the components come together. "
        "Be concise and practical. Do NOT describe the eating experience, do NOT add generic "
        "closing sentences like 'creating a delicious meal' or 'satisfying and flavorful'.\n"
        "3. Return the ingredient IDs exactly as given — you may drop one if it truly does not"
        " belong\n"
        "4. Mark valid=false ONLY if the combination is genuinely inedible or absurd as a savoury "
        "main dish (e.g. candy, ice cream, or confectionery mixed with proteins and carbs). "
        "Provide a brief reason when marking invalid.\n"
        "   Cross-cuisine pairings, unusual flavour profiles, and imperfect matches are all "
        "ACCEPTABLE — mark them valid=true.\n"
        "Respond with a JSON object only."
    )

    meat_section = "MEAT TRACK\n" + "\n\n".join(
        _format_dish(d, i + 1) for i, d in enumerate(meat_dishes)
    )
    veg_section = "VEGETARIAN TRACK\n" + "\n\n".join(
        _format_dish(d, i + 1) for i, d in enumerate(veg_dishes)
    )

    output_format = (
        'Return a JSON object with exactly this structure:\n'
        '{\n'
        '  "meat": [\n'
        '    {"dish_name": "...", "description": "...", "ingredients": [id1, id2, id3, id4],'
        ' "valid": true},\n'
        '    ... (5 objects total, one per day Mon-Fri)\n'
        '  ],\n'
        '  "vegetarian": [\n'
        '    {"dish_name": "...", "description": "...", "ingredients": [id1, id2, id3, id4],'
        ' "valid": true},\n'
        '    ... (5 objects total, one per day Mon-Fri)\n'
        '  ]\n'
        '}\n'
        'Add "reason": "..." only when valid=false. Preserve dish order.'
    )

    error_section = ""
    if errors:
        error_lines = "\n".join(f"- {e}" for e in errors)
        error_section = f"\nPREVIOUS ERRORS — fix these before responding:\n{error_lines}"

    user = f"{meat_section}\n\n{veg_section}\n\n{output_format}{error_section}"

    return [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": user}),
    ]


def _validate_ids(
    naming: NamingResponse,
    meat_dishes: list[ComposedDish],
    veg_dishes: list[ComposedDish],
    catalogue: Catalogue,
) -> list[str]:
    """Validate the ingredient in the llm response."""
    errors: list[str] = []
    for track_name, named_list, composed_list in (
        ("meat", naming.meat, meat_dishes),
        ("vegetarian", naming.vegetarian, veg_dishes),
    ):
        for i, (named, composed) in enumerate(zip(named_list, composed_list, strict=True)):
            composed_ids = {p["product_id"] for p, _ in composed.products}
            for pid in named.ingredients:
                if catalogue.get_product_by_id(pid) is None:
                    errors.append(
                        f"{track_name} dish {i + 1}: product_id {pid} not in catalogue"
                    )
                elif pid not in composed_ids:
                    errors.append(
                        f"{track_name} dish {i + 1}: product_id {pid} was not in the "
                        "composed set — use only the IDs provided"
                    )
    return errors

def _assemble_plan(
    week_start: str,
    meat_dishes: list[ComposedDish],
    naming: NamingResponse,
    veg_dishes: list[ComposedDish],
    flagged: dict[str, list[int]] | None = None,
) -> WeeklyPlan:
    flagged = flagged or {}

    def build_track(dishes: list[ComposedDish], named: list[NamedDish], track: str) -> dict:
        result = {}
        for i, day in enumerate(DAYS):
            dish = dishes[i].to_dish(named[i].dish_name, named[i].description)
            if i in flagged.get(track, []):
                dish = dish.model_copy(update={
                    "needs_review": True,
                    "chef_note": (
                        "This dish was flagged as potentially incoherent. "
                        "Please modify or at least review before serving."
                    ),
                })
            result[day] = dish.model_dump()
        return result

    return WeeklyPlan.model_validate({
        "week_start": week_start,
        "meat": build_track(meat_dishes, naming.meat, "meat"),
        "vegetarian": build_track(veg_dishes, naming.vegetarian, "vegetarian"),
    })

def generate(week_start: str, catalogue: Catalogue | None = None) -> WeeklyPlan:
    if catalogue is None:
        catalogue = Catalogue()

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=_GROQ_BASE_URL)

    logger.info("Composing dishes for week_start=%s", week_start)
    meat_dishes = compose_week("meat", catalogue)
    veg_dishes = compose_week("vegetarian", catalogue)

    # llama-3.3-70b-versatile only supports json_object, not json_schema.
    # Structural validation is handled by NamingResponse.model_validate_json().
    response_format = ResponseFormatJSONObject(type="json_object")

    errors: list[str] = []
    last_raw = ""
    rl_attempt = 0

    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info("LLM naming call — attempt %d/%d", attempt, _MAX_RETRIES)
        messages = _prompt(meat_dishes, veg_dishes, errors)

        try:
            response = client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                temperature=_TEMPERATURE,
                response_format=response_format,
            )
        except RateLimitError:
            wait = (
                _RATE_LIMIT_BACKOFF[rl_attempt]
                if rl_attempt < len(_RATE_LIMIT_BACKOFF)
                else None
            )
            if wait is not None:
                logger.warning("Rate limit hit — waiting %.0fs before retry", wait)
                time.sleep(wait)
                rl_attempt += 1
                continue
            logger.error("Rate limit exhausted after %d backoff attempts", rl_attempt)
            raise PlannerError("Groq rate limit exceeded — try again in a moment") from None
        except APIError as e:
            logger.error("Groq API error on attempt %d: %s", attempt, e)
            raise PlannerError(f"Groq API error: {e}") from e

        if response.usage:
            logger.info(
                "tokens attempt=%d prompt=%d completion=%d total=%d",
                attempt,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
            )
        last_raw = response.choices[0].message.content or ""

        try:
            naming = NamingResponse.model_validate_json(last_raw)
        except ValidationError as e:
            logger.warning("Attempt %d — schema validation failed: %s", attempt, e)
            errors.append(str(e))
            continue

        id_errors = _validate_ids(naming, meat_dishes, veg_dishes, catalogue)
        if id_errors:
            logger.warning("Attempt %d — invalid product IDs: %s", attempt, id_errors)
            errors.extend(id_errors)
            continue

        # Re-compose any dish the LLM flagged as incoherent
        invalid: dict[str, list[int]] = {"meat": [], "vegetarian": []}
        for i, named in enumerate(naming.meat):
            if not named.valid:
                logger.warning("Meat dish %d flagged invalid — %s", i + 1, named.reason)
                invalid["meat"].append(i)
        for i, named in enumerate(naming.vegetarian):
            if not named.valid:
                logger.warning("Vegetarian dish %d flagged invalid — %s", i + 1, named.reason)
                invalid["vegetarian"].append(i)

        if invalid["meat"] or invalid["vegetarian"]:
            if attempt == _MAX_RETRIES:
                # Last attempt — accept whatever we have rather than failing completely.
                # Flag the offending dishes so the chef knows to review them.
                logger.warning(
                    "Accepting plan with %d flagged dish(es) after %d attempts — "
                    "re-composition exhausted",
                    len(invalid["meat"]) + len(invalid["vegetarian"]),
                    attempt,
                )
                return _assemble_plan(week_start, meat_dishes, naming, veg_dishes, flagged=invalid)

            for i in invalid["meat"]:
                seen = [meat_dishes[j].ingredient_set() for j in range(5) if j != i]
                try:
                    meat_dishes[i] = compose_single_dish(
                        "meat", CUISINE_ROTATION[i], catalogue, seen
                    )
                    logger.info("Re-composed meat dish %d", i + 1)
                except ComposerError as e:
                    logger.warning("Re-composition failed for meat dish %d: %s", i + 1, e)

            for i in invalid["vegetarian"]:
                seen = [veg_dishes[j].ingredient_set() for j in range(5) if j != i]
                try:
                    veg_dishes[i] = compose_single_dish(
                        "vegetarian", CUISINE_ROTATION[i], catalogue, seen
                    )
                    logger.info("Re-composed vegetarian dish %d", i + 1)
                except ComposerError as e:
                    logger.warning("Re-composition failed for vegetarian dish %d: %s", i + 1, e)

            errors.append(
                f"LLM flagged {len(invalid['meat'])} meat and "
                f"{len(invalid['vegetarian'])} vegetarian dishes as incoherent — re-composed"
            )
            continue

        logger.info("Valid naming received on attempt %d", attempt)
        return _assemble_plan(week_start, meat_dishes, naming, veg_dishes)

    logger.error("All %d attempts failed. Last response: %.200s", _MAX_RETRIES, last_raw)
    raise PlannerError(
        f"Failed to name dishes after {_MAX_RETRIES} attempts. "
        f"Last error: {errors[-1] if errors else 'unknown'}"
    )
