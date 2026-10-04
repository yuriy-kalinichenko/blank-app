from streamlit.testing.v1 import AppTest


def test_app_starts_and_project_workspace_is_present():
    at = AppTest.from_file("streamlit_app.py").run(timeout=15)

    assert len(at.exception) == 0
    assert at.title[0].value == "Jumbo Location Analyzer"

    markdown_values = [item.value for item in at.markdown]
    assert "### Project workspace" in markdown_values

    button_labels = [button.label for button in at.button]
    assert "＋ New" in button_labels
    assert "↧ Load" in button_labels
    assert "Save" in button_labels
    assert "Analyze location" in button_labels
