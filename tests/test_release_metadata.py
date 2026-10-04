import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_synchronized():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    app_source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert pyproject["project"]["name"] == "jumbo-location-analyzer"
    assert pyproject["project"]["version"] == "1.0.0rc1"

    match = re.search(r'BUILD_VERSION = "([^"]+)"', app_source)
    assert match is not None
    assert match.group(1) == "2026-10-04-v1.0-rc1"

    assert "**2026-10-04-v1.0-rc1**" in readme
