import json

import pytest

from local_storage import write_json_atomically


def test_atomic_write_replaces_complete_project_library(tmp_path):
    target = tmp_path / "saved_scenarios.json"
    target.write_text('{"Old": {"location": "Kyiv"}}', encoding="utf-8")

    write_json_atomically(target, {"New": {"location": "Lviv"}})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "New": {"location": "Lviv"}
    }
    assert not list(tmp_path.glob(".saved_scenarios.json.*.tmp"))


def test_failed_serialization_keeps_previous_library(tmp_path):
    target = tmp_path / "saved_scenarios.json"
    original = '{"Existing": {"location": "Odesa"}}'
    target.write_text(original, encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomically(target, {"Broken": {"value": object()}})

    assert target.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".saved_scenarios.json.*.tmp"))
