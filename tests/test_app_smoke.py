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
    assert 'key=f"commercial_save_to_project__{project_key}"' in source
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


def test_karavan_recovery_handles_partial_zero_state():
    source = APP_PATH.read_text(encoding="utf-8")
    assert "not all(value > 0 for value in _core_values)" in source
    assert 'st.session_state["_recovered_project_name"] = _name' in source
    assert "apply_project_to_state(" in source


def test_commercial_tab_reads_directly_from_saved_project():
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'active_saved = saved_projects.get(active_project, {}) if active_project else {}' in source
    assert 'value=float(active_saved.get("area") or 0)' in source
    assert 'value=float(active_saved.get("annual_sales") or 0)' in source
    assert 'saved_projects[active_project] = project_record' in source

def test_commercial_form_state_is_scoped_per_project():
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'project_key = re.sub(' in source
    for fragment in [
        'key=f"commercial_area__{project_key}"',
        'key=f"commercial_rent__{project_key}"',
        'key=f"commercial_capex__{project_key}"',
        'key=f"commercial_sales__{project_key}"',
        'key=f"commercial_margin__{project_key}"',
        'key=f"commercial_save_to_project__{project_key}"',
    ]:
        assert fragment in source
    assert 'saved_projects[active_project] = project_record' in source
    assert 'saved_projects[active_project] = capture_project_from_state(active_project)' not in source
