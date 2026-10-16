from analysis_evidence import attach_analysis
from project_library import export_project_library, validate_project_library
import json


def test_site_evidence_roundtrip_preserves_other_projects_and_unknown_economics():
    projects = {'Tirana': {'location': 'TEG, Tirana', 'annual_sales': 123}}
    record = {'location': 'East Point, Tbilisi', 'annual_sales': None}
    analysis = {'query': record['location'], 'population': {'15 min': {'total_population': 100}}}
    projects['Tbilisi'] = attach_analysis(record, analysis)
    analysis['population'].clear()
    restored = validate_project_library(json.loads(export_project_library(projects, 'qa')))
    assert restored['Tirana']['annual_sales'] == 123
    assert restored['Tbilisi']['annual_sales'] is None
    assert restored['Tbilisi']['analysis_snapshot']['population']['15 min']['total_population'] == 100
    changed = attach_analysis({**restored['Tbilisi'], 'location': 'Other site'}, analysis)
    assert 'analysis_snapshot' not in changed
