import pytest


@pytest.fixture(scope="session", autouse=True)
def cloud_disabled_by_default():
    # Runs before module-scoped fixtures that import the entire Streamlit script.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("JUMBO_CLOUD_DISABLED", "1")
        yield


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    """Tests do not modify the developer's local library."""
    monkeypatch.chdir(tmp_path)
