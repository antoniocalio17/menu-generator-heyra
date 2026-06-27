# Heyra Menu Generator

Automated weekly canteen menu planner for two dietary tracks (meat / vegetarian), Monday to Friday.

The composer algorithm builds dishes from a real product catalogue using cuisine-weighted sampling. The LLM (Groq `llama-3.3-70b-versatile`) only names each dish, writes a short recipe overview, and flags genuinely incoherent combinations. Ingredient selection is fully deterministic.

---

## Setup

**Prerequisites:** Python 3.10+, a [Groq API key](https://console.groq.com).

```bash
# 1. Create and activate the environment
conda create -n heyra_menu python=3.10
conda activate heyra_menu

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your Groq API key
echo "GROQ_API_KEY=your_key_here" > engine/.env
```

---

## Run

### Web API + UI

```bash
uvicorn api.main:app --reload
```

Open `http://localhost:8000` — the chef UI loads automatically.

| Endpoint | Description |
|---|---|
| `POST /api/generate/{year}/{week}` | Run the full pipeline for an ISO year + week |
| `GET  /api/menu/{year}/{week}` | Retrieve a saved menu |
| `PUT  /api/menu/{year}/{week}/{track}/{day}` | Chef edits one dish |
| `POST /api/suggest` | AI-ranked ingredient substitutes |
| `POST /api/rename-dish` | Re-generate dish name after a swap |
| `GET  /api/catalogue` | Full product list (used by the UI) |

### CLI (dev / quick test)

```bash
python local_main.py <week_number>
# e.g. python local_main.py 27
```

Prints the week's menu as Markdown to stdout.

### Tests

```bash
pytest tests/
```

42 tests covering catalogue, composer, exporter, and validator.

---

## Project Structure

```
menu-generator/
│
├── engine/                     core business logic, no HTTP
│   ├── constants.py            all shared values and LLM prompt strings
│   ├── output_format.py        Pydantic models (Dish, TrackPlan, WeeklyPlan)
│   ├── catalogue.py            loads products.csv, typed product queries
│   ├── composer.py             builds dish skeletons by weighted sampling
│   ├── groq_llama.py           calls the LLM to name dishes, handles retries
│   ├── fallback.py             builds a plan from past saved menus if LLM fails
│   ├── validator.py            checks dietary rules and product existence
│   ├── exporter.py             enriches a plan with costs, kcal, allergens
│   └── suggester.py            AI ingredient substitution and dish renaming
│
├── api/
│   ├── main.py                 FastAPI app — routes, orchestration, error handling
│   └── logging_config.py       rotating file logger (1 MB × 5), silences third-party noise
│
├── web_app/                    plain HTML/CSS/JS chef UI, no framework, no build step
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── tests/
│   ├── test_catalogue.py       product filtering, dietary constraints, exclusions
│   ├── test_composer.py        dish uniqueness, cuisine rotation, budget fit
│   ├── test_exporter.py        cost/kcal totals, allergens, JSON and Markdown output
│   └── test_validator.py       dietary violations, unknown product IDs
│
├── data/
│   ├── products.csv            3137 products, 2959 available, 29 ingredient groups
│   └── menus/                  generated weekly plans saved as YYYY_wWW.json
│
├── local_main.py               CLI entry point (dev use)
├── requirements.txt
└── pyproject.toml              ruff + mypy + pytest config
```

---

## How the pipeline works

```
products.csv
     │
     ▼
 catalogue        loads and indexes all available products
     │
     ▼
 composer         picks one product per role (protein / carb / veg / sauce)
                  per day using cuisine-weighted sampling
                  scales protein quantity if daily budget is exceeded
     │
     ▼
 groq_llama       sends 10 composed dishes to the LLM
                  LLM returns names, descriptions, validity flags
                  re-composes and retries on bad output (up to 3 attempts)
                  falls back to fallback.py if LLM is unavailable
     │
     ▼
 validator        checks product IDs, meat/veg dietary rules
     │
     ▼
 exporter         computes per-dish cost, kcal, allergens → JSON or Markdown
     │
     ▼
 data/menus/      saved as YYYY_wWW.json for retrieval and fallback
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key — place in `engine/.env` |
