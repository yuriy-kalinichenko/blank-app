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
    assert "＋ New" in button_labels
    assert "↧ Load" in button_labels
    assert "Save" in button_labels
    assert "Analyze location" in button_labels

    expander_labels = [item.label for item in at.expander]
    assert "Project library · backup & transfer" in expander_labels

    download_labels = [item.label for item in at.download_button]
    assert "Export library" in download_labels

    uploader_keys = [item.key for item in at.file_uploader]
    assert "project_import_library_file" in uploader_keys
