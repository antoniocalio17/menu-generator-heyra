"""
Per-ingredient AI substitution suggestions.
Given the full dish context and a target slot, returns ranked substitute
candidates from the live catalogue.
"""

import logging
import os
from pathlib import Path
from typing import Annotated, cast

from dotenv import load_dotenv
from openai import APIError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, Field, ValidationError

from engine.catalogue import Catalogue, Product

load_dotenv(Path(__file__).parent / ".env")

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL = "llama-3.3-70b-versatile"
_TEMPERATURE = 0.3
_MAX_CANDIDATES = 3
_POOL_SIZE = 20

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rename / re-describe a dish after an ingredient swap
# ---------------------------------------------------------------------------


class _RenameResponse(BaseModel):
    dish_name: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]


def rename_dish(
    ingredients: list[dict],
    track: str,
    catalogue: Catalogue,
) -> dict:
    """
    Return {dish_name, description} for the current ingredient set.
    Called after the chef swaps an ingredient so the name stays coherent.
    """
    dish: list[tuple[Product, float]] = []
    for ing in ingredients:
        p = catalogue.get_product_by_id(ing["product_id"])
        if p:
            dish.append((p, float(ing["quantity_g"])))

    if not dish:
        raise ValueError("No valid ingredients to rename")

    lines = [f"Track: {track}\n\nIngredients:"]
    for p, qty in dish:
        lines.append(
            f"  {p['ingredient_group']}: {p['product_name']} "
            f"({qty:.0f}g, cuisine={p['cuisine_tag']})"
        )

    schema = (
        '\n\nGive this dish:\n'
        '1. A creative name (3-6 words)\n'
        '2. A 1-2 sentence description — mention the key cooking technique and how '
        'the components come together. Be concise. No generic closing sentences.\n\n'
        'Return JSON only:\n'
        '{ "dish_name": "...", "description": "..." }'
    )

    system = (
        "You are a professional canteen chef. "
        "Name and briefly describe a dish based on its ingredients. "
        "Respond with JSON only."
    )

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=_GROQ_BASE_URL)
    messages: list[ChatCompletionMessageParam] = [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": "\n".join(lines) + schema}),
    ]

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=_TEMPERATURE,
            response_format=ResponseFormatJSONObject(type="json_object"),
        )
    except APIError as e:
        logger.error("Groq API error in rename_dish: %s", e)
        raise

    if response.usage:
        logger.info(
            "rename_dish tokens — prompt=%d completion=%d total=%d",
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        )
    raw = response.choices[0].message.content or ""
    try:
        parsed = _RenameResponse.model_validate_json(raw)
    except ValidationError as e:
        logger.warning("rename_dish schema validation failed: %s | raw: %.200s", e, raw)
        raise

    return {"dish_name": parsed.dish_name, "description": parsed.description}


# ---------------------------------------------------------------------------
# Substitute suggestions for one ingredient slot
# ---------------------------------------------------------------------------


class _Candidate(BaseModel):
    product_id: int
    reason: Annotated[str, Field(min_length=1)]


class _SuggestionResponse(BaseModel):
    candidates: Annotated[
        list[_Candidate],
        Field(min_length=1, max_length=_MAX_CANDIDATES),
    ]


def _build_prompt(
    dish: list[tuple[Product, float]],
    target: Product,
    pool: list[Product],
    track: str,
) -> list[ChatCompletionMessageParam]:
    system = (
        f"You are a culinary advisor for a canteen kitchen (track: {track}).\n"
        "A chef wants to swap one ingredient. Given the full dish and a pool of "
        f"available substitutes, pick the best {_MAX_CANDIDATES} replacements.\n"
        "Rank by how well each fits the dish's cuisine, coherence, and balance. "
        "Only use product_ids from the provided pool. "
        "One concise reason per candidate (max 12 words). Respond with JSON only."
    )

    dish_lines = ["Current dish:"]
    for product, qty in dish:
        marker = "  <-- REPLACE THIS" if product["product_id"] == target["product_id"] else ""
        dish_lines.append(
            f"  {product['ingredient_group']}: {product['product_name']} "
            f"({qty:.0f}g, cuisine={product['cuisine_tag']}){marker}"
        )

    pool_lines = [
        f"\nAvailable substitutes for '{target['product_name']}' "
        f"({target['ingredient_group']}):"
    ]
    for p in pool:
        pool_lines.append(
            f"  id={p['product_id']}  {p['product_name']}  "
            f"cuisine={p['cuisine_tag']}  {p['cost_per_100g_eur']:.2f} EUR/100g"
        )

    schema = (
        '\nReturn JSON:\n'
        '{\n'
        '  "candidates": [\n'
        '    { "product_id": <int from pool>, "reason": "..." },\n'
        '    ...\n'
        '  ]\n'
        '}'
    )

    user = "\n".join(dish_lines) + "\n".join(pool_lines) + schema

    return [
        cast(ChatCompletionMessageParam, {"role": "system", "content": system}),
        cast(ChatCompletionMessageParam, {"role": "user", "content": user}),
    ]


def suggest_substitutes(
    ingredients: list[dict],
    target_product_id: int,
    track: str,
    catalogue: Catalogue,
) -> list[dict]:
    """
    Return up to _MAX_CANDIDATES substitute products for target_product_id,
    ranked by fit within the full dish context.

    Each item in the returned list:
        {product_id, product_name, ingredient_group, cost_per_100g_eur, reason}
    """
    dish: list[tuple[Product, float]] = []
    target: Product | None = None

    for ing in ingredients:
        p = catalogue.get_product_by_id(ing["product_id"])
        if p is None:
            continue
        dish.append((p, float(ing["quantity_g"])))
        if ing["product_id"] == target_product_id:
            target = p

    if target is None:
        raise ValueError(f"product_id {target_product_id} not in catalogue")

    pool = catalogue.get_products_by_group(
        target["ingredient_group"],
        track,
        exclude_ids={target_product_id},
        limit=_POOL_SIZE,
    )
    if not pool:
        return []

    valid_ids = {p["product_id"] for p in pool}

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=_GROQ_BASE_URL)
    messages = _build_prompt(dish, target, pool, track)

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=_TEMPERATURE,
            response_format=ResponseFormatJSONObject(type="json_object"),
        )
    except APIError as e:
        logger.error("Groq API error in suggester: %s", e)
        raise

    if response.usage:
        logger.info(
            "suggest_substitutes tokens — prompt=%d completion=%d total=%d",
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            response.usage.total_tokens,
        )
    raw = response.choices[0].message.content or ""
    try:
        parsed = _SuggestionResponse.model_validate_json(raw)
    except ValidationError as e:
        logger.warning("Suggester schema validation failed: %s | raw: %.200s", e, raw)
        raise

    results: list[dict] = []
    for c in parsed.candidates:
        if c.product_id not in valid_ids:
            logger.debug("Suggester returned unknown id %d — skipped", c.product_id)
            continue
        p = catalogue.get_product_by_id(c.product_id)
        if p is None:
            continue
        results.append({
            "product_id": c.product_id,
            "product_name": p["product_name"],
            "ingredient_group": p["ingredient_group"],
            "cost_per_100g_eur": p["cost_per_100g_eur"],
            "reason": c.reason,
        })

    return results
