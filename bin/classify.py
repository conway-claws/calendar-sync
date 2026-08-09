"""Assign one of the four CLAWS labels to an event title via labels.tsv rules."""

import re
from pathlib import Path

from config import DEFAULT_LABEL, LABELS

RULES_PATH = Path(__file__).resolve().parent.parent / "labels.tsv"


def load_rules(path=RULES_PATH):
    rules = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        label, pattern = line.split("\t", 1)
        if label not in LABELS:
            raise ValueError(f"unknown label in {path}: {label}")
        rules.append((label, re.compile(pattern, re.IGNORECASE)))
    return rules


_RULES = None


def label_for(title, llm_label=None):
    """Rules first; a valid LLM-suggested label as fallback; else the default."""
    global _RULES
    if _RULES is None:
        _RULES = load_rules()
    for label, pattern in _RULES:
        if pattern.search(title):
            return label
    if llm_label in LABELS:
        return llm_label
    return DEFAULT_LABEL
