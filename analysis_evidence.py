"""Portable evidence snapshots; never attach another location's analysis."""
from copy import deepcopy


def attach_analysis(project, analysis):
    result = dict(project)
    location = (result.get('location') or '').strip()
    if analysis and analysis.get('query') == location:
        result['analysis_snapshot'] = deepcopy(analysis)
    elif (result.get('analysis_snapshot') or {}).get('query') != location:
        result.pop('analysis_snapshot', None)
    return result
