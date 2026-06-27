"""
End-to-end pipeline: catalogue → planner → fix_budget → validator → markdown output.
Usage: python main.py <week_number>   (e.g. python main.py 25)
"""

import sys
from datetime import date

from engine.catalogue import Catalogue
from engine.exporter import build_summary, to_markdown
from engine.groq_llama import PlannerError, generate
from engine.validator import PlanValidationError, validate


def main(week_number: int) -> None:
    try:
        week_start = date.fromisocalendar(date.today().year, week_number, 1)
    except ValueError:
        print(f"Invalid week number: {week_number}. Must be 1–52 (or 53 for long years).")
        sys.exit(1)

    catalogue = Catalogue()

    print(f"Generating menu for ISO week {week_number} ({week_start})...")
    try:
        plan = generate(week_start.isoformat(), catalogue=catalogue)
    except PlannerError as e:
        print(f"Planner failed: {e}")
        sys.exit(1)

    try:
        validate(plan, catalogue)
    except PlanValidationError as e:
        print("Validation errors:")
        for error in e.errors:
            print(f"  - {error}")
        sys.exit(1)

    summary = build_summary(plan, catalogue)
    print(to_markdown(summary))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <week_number>  (e.g. python main.py 25)")
        sys.exit(1)
    try:
        week = int(sys.argv[1])
    except ValueError:
        print(f"Week number must be an integer, got: '{sys.argv[1]}'")
        sys.exit(1)
    main(week)
