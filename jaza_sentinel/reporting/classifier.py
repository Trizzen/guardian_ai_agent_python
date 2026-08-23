"""Explainable deterministic classification before any Luna inference."""

from __future__ import annotations

import re

from .models import ActivityFact, Classification


DOMAIN_IDS = (
    "daily-command",
    "coding-command",
    "fitness-program",
    "nutrition-program",
    "gardening-program",
    "financial-program",
    "budget-program",
)

_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gardening-program", "garden_context", ("garden", "gardening", "plant", "seed", "soil", "water garden", "harvest", "fertilize", "fertilizer", "weed", "tomato", "vegetable", "herb")),
    ("nutrition-program", "nutrition_context", ("nutrition", "meal", "breakfast", "lunch", "dinner", "food", "protein", "calorie", "calories", "macro", "macros", "hydrate", "hydration", "drink water", "diet", "supplement")),
    (
        "fitness-program",
        "fitness_context",
        (
            "workout", "exercise", "fitness", "gym", "bench press", "bicep curl", "curls",
            "cardio", "treadmill", "running", "jog", "jogging", "fitness walk",
            "go for a walk", "take a walk", "squat", "squats", "deadlift", "pushup",
            "push-up", "stretch", "bike ride", "cycling", "strength train",
            "strength training", "bodybuilding",
        ),
    ),
    ("coding-command", "coding_context", ("code", "coding", "programming", "developer", "software", "debug", "bug", "deploy", "release", "repository", "github", "angular", "flask", "python", "typescript", "javascript", "api", "database", "sql", "guardthiskingdom", "menusheild", "menushield", "safebite", "jaza", "automatrix")),
    ("budget-program", "budget_context", ("budget", "spending plan", "expense", "expenses", "bill", "bills", "monthly spending", "cut cost", "save money")),
    ("financial-program", "financial_context", ("finance", "financial", "retirement", "invest", "investment", "income", "tax", "debt", "credit", "savings", "mortgage", "insurance", "net worth")),
    ("daily-command", "daily_command_context", ("priority", "priorities", "daily plan", "plan today", "weekly review", "morning review", "check-in", "check in")),
)


def _normalize(value: str) -> str:
    return " " + re.sub(r"[^a-z0-9+.#-]+", " ", value.lower()).strip() + " "


def classify(fact: ActivityFact) -> Classification:
    if fact.source_kind.startswith("garden_") or fact.category.strip().lower() == "garden":
        return Classification(
            domain="gardening-program",
            confidence=1.0,
            reason="GTK Garden taxonomy or Garden Pro structure.",
            rule="garden_source",
        )
    haystack = " ".join((fact.title, fact.note, fact.category))
    normalized = _normalize(haystack)
    for domain, rule, keywords in _RULES:
        # Whole-token / whole-phrase matching avoids substring accidents such as
        # "api" in an unrelated word or "run" inside a product name.
        matches = [keyword for keyword in keywords if _normalize(keyword) in normalized]
        if matches:
            return Classification(
                domain=domain,
                confidence=0.95 if len(matches) > 1 else 0.88,
                reason=f"Matched contextual signal: {matches[0]}.",
                rule=rule,
            )
    return Classification(
        domain="unclassified",
        confidence=0.0,
        reason=(
            "GTK taxonomy alone was insufficient; the title and note did not match a safe domain rule."
        ),
        rule="requires_luna_or_human_review",
    )


def classify_all(facts: list[ActivityFact]) -> list[ActivityFact]:
    for fact in facts:
        fact.classification = classify(fact)
    return facts
