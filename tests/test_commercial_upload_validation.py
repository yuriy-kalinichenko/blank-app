"""Commercial file imports must not inject invalid financial assumptions."""

import ast
import math
import re
from pathlib import Path

import pytest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def commercial_parser(rows):
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    aliases = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "COMMERCIAL_FIELD_ALIASES"
            for target in node.targets
        )
    )
    names = {
        "_normalize_commercial_label",
        "_match_commercial_field",
        "_parse_commercial_number",
        "parse_commercial_upload",
    }
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "COMMERCIAL_FIELD_ALIASES": aliases,
        "math": math,
        "re": re,
    }
    exec(
        compile(ast.Module(body=definitions, type_ignores=[]), str(APP_PATH), "exec"),
        namespace,
    )
    namespace["_commercial_rows_from_upload"] = lambda _uploaded: rows
    return namespace["parse_commercial_upload"]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([['Store area', 'NaN']], "Store area must be a finite number"),
        ([['CAPEX', '-250000']], "CAPEX cannot be negative"),
        ([['Gross margin', '125']], "Gross margin must be between 0 and 100"),
        ([['Annual sales', 'not-a-number']], "Annual sales must be a finite number"),
    ],
)
def test_commercial_import_rejects_invalid_financial_values(rows, message):
    with pytest.raises(ValueError, match=message):
        commercial_parser(rows)(object())


def test_commercial_import_keeps_valid_localized_financial_values():
    rows = [
        ["Store area", "4 500"],
        ["CAPEX", "2.500.000,50"],
        ["Gross margin", "50%"],
        ["Logistics", "20,000"],
    ]

    assert commercial_parser(rows)(object()) == {
        "area": 4500.0,
        "capex": 2500000.5,
        "gross_margin": 50.0,
        "logistics": 20000.0,
    }
