# Heyra Menu Generator

Automated weekly canteen menu planner for two dietary tracks (meat / vegetarian), Monday to Friday.

The composer algorithm builds dishes from a real product catalogue using cuisine-weighted sampling. The LLM (Groq `llama-3.3-70b-versatile`) only names each dish, writes a short recipe overview, and flags genuinely incoherent combinations. Ingredient selection is fully deterministic.

---

## Setup

**Prerequisites:** Python 3.10+, a [Groq API key](https://console.groq.com).

Inside `engine/.env`, set:
```
GROQ_API_KEY=your_groq_api_key_here
```

---

### Windows

**Option A — with Conda** *(Conda must already be installed)*

```powershell
conda create -n heyra_menu python=3.10
conda activate heyra_menu
pip install -r requirements.txt
Copy-Item engine\.env.example engine\.env
notepad engine\.env
```

**Option B — without Conda**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item engine\.env.example engine\.env
notepad engine\.env
```

---

### macOS / Linux

**Option A — with Conda** *(Conda must already be installed)*

```bash
conda create -n heyra_menu python=3.10
conda activate heyra_menu
pip install -r requirements.txt
cp engine/.env.example engine/.env
nano engine/.env
```

**Option B — without Conda**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp engine/.env.example engine/.env
nano engine/.env
```

---

## Run

### Web API + UI

```bash
python -m uvicorn api.main:app --reload
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
├── engine/                         core business logic, no HTTP
│   ├── constants.py                all shared values, LLM config, and prompt strings
│   ├── output_format.py            Pydantic models shared across the engine (Dish, WeeklyPlan)
│   ├── catalogue.py                loads products.csv, typed product queries
│   ├── composer.py                 builds dish skeletons by cuisine-weighted sampling
│   ├── fallback.py                 builds a plan from past saved menus if LLM fails
│   ├── validator.py                checks dietary rules and product existence
│   ├── exporter.py                 enriches a plan with costs, kcal, allergens
│   └── llm/                        everything that talks to the Groq API
│       ├── schemas.py              Pydantic models for LLM request/response parsing
│       ├── groq_llama.py           dish naming, coherence validation, retry logic
│       └── suggester.py            ingredient substitution suggestions and dish renaming
│
├── api/
│   ├── schemas.py                  Pydantic request/response models for the HTTP layer
│   ├── deps.py                     shared state: catalogue instance, paths, helpers
│   ├── main.py                     FastAPI route handlers (no class definitions)
│   └── logging_config.py           rotating file logger (1 MB × 5), silences third-party noise
│
├── web_app/                        plain HTML/CSS/JS chef UI, no framework, no build step
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── tests/
│   ├── test_catalogue.py           product filtering, dietary constraints, exclusions
│   ├── test_composer.py            dish uniqueness, cuisine rotation, budget fit
│   ├── test_exporter.py            cost/kcal totals, allergens, JSON and Markdown output
│   └── test_validator.py           dietary violations, unknown product IDs
│
├── data/
│   ├── products.csv                3137 products, 2959 available, 29 ingredient groups
│   └── menus/                      generated weekly plans saved as YYYY_wWW.json
│
├── local_main.py                   CLI entry point (dev use)
├── requirements.txt
└── pyproject.toml                  ruff + mypy + pytest config
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
 llm/groq_llama   sends 10 composed dishes to the LLM
                  LLM returns names, descriptions, validity flags
                  re-composes and retries on bad output (up to 3 attempts)
                  falls back to fallback.py if LLM is unavailable
     │
     ▼
 validator        checks product IDs and meat/veg dietary rules
     │
     ▼
 exporter         computes per-dish cost, kcal, allergens → JSON or Markdown
     │
     ▼
 data/menus/      saved as YYYY_wWW.json for retrieval and fallback
```

---

## Future improvements

**Composer algorithm**

The current composer samples ingredients using cuisine-weighted randomness at the ingredient-group level. Several improvements are possible:

- **Flavour-profile labels per ingredient** — adding a `flavour_profile` attribute (e.g. savoury / sweet / sour / bitter) at the individual product level rather than the group level would let the composer enforce basic culinary coherence before the LLM step. Any labelled dataset found online would be sufficient; however this was not the main focus of the project.
- **Cuisine tags per product** — currently every product inherits the tag of its group. A per-product tag would give the composer finer-grained control over dish coherence.

**Inventory and demand forecasting**

- Once a weekly menu is fixed, the exact quantities of each ingredient needed are known. These could be accumulated over time to build a real consumption history.
- With a few months of data, forecasting models (e.g. Prophet, ARIMA) could predict how demand varies across the year — higher protein consumption in winter, lighter dishes in summer — and adjust the composer's sampling weights accordingly.
- Inventory tracking could be added: adjust the purchasing plan based on what is actually left in stock from the previous week rather than starting from zero each time.

**Cost model**

The current budget assumes a fixed cost of ~35 DKK per meal per employee (after tax), keeping raw material cost at roughly 20 EUR per week. This is a simplification — a more rigorous model could account for:

- Labour, energy, and overhead costs on top of raw materials.
- A **monthly budget constraint** instead of a hard weekly cap, allowing the system to spend more in one week and compensate the following week rather than applying the same ceiling uniformly.
- Dynamic pricing from actual supplier invoices rather than catalogue estimates.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key — place in `engine/.env` (see `engine/.env.example`) |
