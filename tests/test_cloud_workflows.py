from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cloud_storage import CloudError, ConflictError
import cloud_workspace


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cloud_app(monkeypatch):
    monkeypatch.delenv("JUMBO_CLOUD_DISABLED")
    database = {}
    options = {"offline": False}
    class FakeClient:
        def __init__(self, config, session=None):
            self.session = session if session is not None else {}
        def sign_in(self, email, password):
            self.session.update({"user_id": email, "email": email, "access_token": "test"})
        def load_library(self):
            return deepcopy(database.get(self.session["user_id"], ({}, 0)))
        def save_library(self, projects, revision):
            if options["offline"]:
                raise CloudError("Connection unavailable. Export a backup.")
            key = self.session["user_id"]
            if revision != database.get(key, ({}, 0))[1]:
                raise ConflictError("Changed in another session. Export and reload.")
            database[key] = deepcopy(projects), revision + 1
            return revision + 1
        def sign_out(self):
            self.session.clear()
    monkeypatch.setattr(cloud_workspace, "CloudClient", FakeClient)
    def create():
        at = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=15).run()
        assert not at.exception
        return at
    return create, database, options


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception


def sign_in(at, email="owner@example.test"):
    at.text_input(key="cloud_email").set_value(email)
    at.text_input(key="cloud_password").set_value("test-password")
    click(at, "Sign in")


def create_project(at, name):
    at.text_input(key="project_name_input").set_value(name)
    at.text_input(key="location_query").set_value("Test site")
    click(at, "Create project")


def test_guest_data_is_session_only_and_not_read_from_shared_file(cloud_app):
    create, database, _ = cloud_app
    Path("saved_scenarios.json").write_text('{"private-server-copy":{"location":"Secret"}}')
    at = create()
    assert "private-server-copy" not in at.session_state["project_library"]
    create_project(at, "Guest draft")
    assert "Guest draft" in at.session_state["project_library"]
    assert not database
    assert any("only in this session" in item.value for item in at.warning)
    assert "Guest draft" not in Path("saved_scenarios.json").read_text()


def test_save_survives_fresh_session_and_other_account_has_no_projects(cloud_app):
    create, database, _ = cloud_app
    first = create()
    sign_in(first)
    create_project(first, "Cloud Kyiv")
    second = create()
    sign_in(second)
    assert "Cloud Kyiv" in second.session_state["project_library"]
    second.selectbox(key="project_selector").select("Cloud Kyiv").run()
    assert second.text_input(key="location_query").value == "Test site"
    other = create()
    sign_in(other, "other@example.test")
    assert other.session_state["project_library"] == {}


def test_failed_save_preserves_draft_reports_warning_and_can_retry(cloud_app):
    create, database, options = cloud_app
    at = create()
    sign_in(at)
    options["offline"] = True
    create_project(at, "Offline draft")
    assert not database
    assert "Offline draft" in at.session_state["project_library"]
    assert any("only in this session" in item.value for item in at.warning)
    assert not any("Project created" in item.value for item in at.success)
    options["offline"] = False
    click(at, "Retry cloud save")
    assert "Offline draft" in database["owner@example.test"][0]
    assert "_storage_error" not in at.session_state


def test_stale_tab_preserves_newer_save_and_local_draft(cloud_app):
    create, database, _ = cloud_app
    first, second = create(), create()
    sign_in(first)
    sign_in(second)
    create_project(first, "Newer cloud project")
    create_project(second, "Stale draft")
    assert "Newer cloud project" in database["owner@example.test"][0]
    assert "Stale draft" not in database["owner@example.test"][0]
    assert "Stale draft" in second.session_state["project_library"]
    assert any("another session" in item.value for item in second.warning)


def test_transfer_preserves_name_collisions_and_logout_clears_account(cloud_app):
    create, database, _ = cloud_app
    at = create()
    guest = deepcopy(at.session_state["project_library"])
    name = next(iter(guest))
    database["owner@example.test"] = ({name: {"location": "Different cloud site", "area": 100}}, 1)
    sign_in(at)
    click(at, "Copy guest projects to my account")
    saved = database["owner@example.test"][0]
    assert saved[name]["location"] == "Different cloud site"
    assert saved[name + " (import 1)"]["location"] == guest[name]["location"]
    at.session_state["analysis"] = {"private": True}
    click(at, "Sign out")
    assert "_cloud_session" not in at.session_state
    assert "analysis" not in at.session_state
    assert name + " (import 1)" not in at.session_state["project_library"]
