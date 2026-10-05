from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def test_app_starts_and_project_workspace_is_present():
    at = AppTest.from_file(APP_PATH).run(timeout=15)

    assert len(at.exception) == 0
    assert at.title[0].value == "Jumbo Location Analyzer"

    markdown_values = [item.value for item in at.markdown]
    assert "### Project workspace" in markdown_values

    button_labels = [button.label for button in at.button]
    assert "＋ New project" in button_labels
    assert "Create project" in button_labels
    assert "Rename" in button_labels
    assert "Delete" in button_labels
    assert "↧ Load" not in button_labels
    assert "Analyze location" in button_labels

    expander_labels = [item.label for item in at.expander]
    assert "Advanced · import / export" in expander_labels

    download_labels = [item.label for item in at.download_button]
    assert "Export library" in download_labels

    uploader_keys = [item.key for item in at.file_uploader]
    assert "project_import_library_file" in uploader_keys


def test_commercial_workflow_is_simple_and_upload_is_advanced():
    source = APP_PATH.read_text(encoding="utf-8")
    assert '"Save to project"' in source
    assert 'key="commercial_save_to_project"' in source
    assert 'with st.expander("Advanced · upload commercial file"' in source
    assert 'key="commercial_data_upload"' in source
    assert '"Apply commercial data"' in source
    assert 'key="commercial_data_apply"' in source


def test_commercial_save_rejects_incomplete_required_fields():
    source = APP_PATH.read_text(encoding="utf-8")
    assert '"Commercial data was not saved. Fill the required fields first: "' in source
    for label in ["Store area", "Rent", "CAPEX", "Annual sales", "Gross margin"]:
        assert f'"{label}"' in source


def test_portfolio_comparison_is_available_for_multiple_projects():
    source = APP_PATH.read_text(encoding="utf-8")
    assert '"### Portfolio comparison"' in source
    assert '"Commercial priority"' in source
    assert '"Sales density / m²"' in source
    assert '"EBITDA"' in source
    assert '"Occupancy cost, %"' in source
    assert '"Payback, years"' in source
    assert '"#### EBITDA comparison"' in source
    assert "positive EBITDA first" in source
    assert "faster payback" in source


def test_workspace_save_preserves_existing_commercial_values():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "Workspace Save changes updates project metadata only." in source
    assert 'existing_project = dict(saved_projects.get(target_name, {}))' in source
    assert 'saved_projects[target_name] = existing_project' in source
    assert '"Save to project" action' in source


def test_karavan_zeroed_commercial_data_has_recovery_baseline():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "One-time recovery for the Karavan baseline" in source
    for snippet in [
        '"area": 4500.0',
        '"rent": 5.0',
        '"capex": 2500000.0',
        '"annual_sales": 5000000.0',
        '"gross_margin": 50.0',
        '"payroll": 250000.0',
        '"utilities": 120000.0',
        '"logistics": 20000.0',
        '"other_opex": 100000.0',
    ]:
        assert snippet in source
