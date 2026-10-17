"""Portfolio money comparisons must not assume an implicit exchange rate."""

import ast
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest


def functions():
    source = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    tree = ast.parse(source.read_text())
    names = {"build_project_comparison", "build_ebitda_comparison_charts"}
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"pd": pd}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def project(currency="EUR", scale=1):
    # Identical profitability and payback, expressed in different nominal units.
    return {"currency": currency, "area": 10, "rent": scale,
            "annual_sales": 1000 * scale, "gross_margin": 50,
            "capex": 100 * scale}


def test_mixed_currency_priority_ignores_nominal_sales_density():
    projects = {"EUR first": project(), "UAH nominally larger": project("UAH", 100)}
    before = deepcopy(projects)
    result = functions()["build_project_comparison"](projects)
    assert result["Project"].tolist() == list(projects)
    assert result["EBITDA margin, %"].tolist() == [38.0, 38.0]
    assert result["Payback, years"].tolist() == [0.3, 0.3]
    assert result["EBITDA"].tolist() == [380, 38000]  # Keep original units.
    assert projects == before


def test_same_currency_priority_retains_sales_density_tiebreak():
    result = functions()["build_project_comparison"]({"First": project(), "Denser": project(scale=2)})
    assert result["Project"].tolist() == ["Denser", "First"]


def test_mixed_currency_priority_still_uses_dimensionless_returns():
    better = {**project("UAH", 100), "capex": 1000}
    result = functions()["build_project_comparison"]({"EUR": project(), "UAH": better})
    assert result.iloc[0]["Project"] == "UAH"


def test_ebitda_charts_contain_one_currency_each_and_preserve_values():
    f = functions()
    comparison = f["build_project_comparison"]({"EUR": project(), "UAH": project("UAH", 100), "EUR second": project(scale=2)})
    charts = f["build_ebitda_comparison_charts"](comparison)
    assert set(charts) == {"EUR", "UAH"}
    assert charts["EUR"]["EBITDA"].to_dict() == {"EUR second": 760, "EUR": 380}
    assert charts["UAH"]["EBITDA"].to_dict() == {"UAH": 38000}


def test_ebitda_charts_handle_empty_missing_and_legacy_currency():
    f = functions()
    assert f["build_ebitda_comparison_charts"](f["build_project_comparison"]({})) == {}
    legacy = project(); del legacy["currency"]
    comparison = f["build_project_comparison"]({"Legacy": legacy, "Missing sales": {"currency": "USD"}})
    charts = f["build_ebitda_comparison_charts"](comparison)
    assert set(charts) == {"EUR"}
    assert charts["EUR"].loc["Legacy", "EBITDA"] == 380


@pytest.mark.parametrize("second_currency, chart_count", [("UAH", 2), ("EUR", 1)])
def test_portfolio_ui_labels_currency_scales_without_changing_projects(monkeypatch, second_currency, chart_count):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    charts = []
    original = st.bar_chart

    def capture(data, **kwargs):
        charts.append(data.copy())
        return original(data, **kwargs)

    monkeypatch.setattr(st, "bar_chart", capture)
    projects = {"QA EUR": project(), "QA second": project(second_currency, 100)}
    before = deepcopy(projects)
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py")
    at.session_state["project_library"] = projects
    at.run(timeout=15)
    assert not at.exception
    assert len(charts) == chart_count
    captions = [item.value for item in at.caption]
    assert any("EBITDA · EUR · saved currency, no conversion" in value for value in captions)
    if second_currency != "EUR":
        assert any("Projects use different currencies" in item.value for item in at.info)
        assert any("EBITDA · UAH · saved currency, no conversion" in value for value in captions)
        assert all(len(chart) == 1 for chart in charts)
    else:
        assert not any("Projects use different currencies" in item.value for item in at.info)
    assert at.session_state["project_library"] == before
