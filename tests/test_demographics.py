import pytest
from demographics import exact_age_population


def test_live_worldpop_bands_do_not_overstate_children_0_to_18():
    rows = [{'class': str(age), 'male': 10, 'female': 10}
            for age in (0, 1, 5, 10, 15)]
    with pytest.raises(ValueError, match='15–19 crosses'):
        exact_age_population(rows)
    assert exact_age_population(rows, (0, 14)) == 80


def test_missing_or_overlapping_band_is_not_zero_population():
    with pytest.raises(ValueError, match='Incomplete'):
        exact_age_population([{'class': '00', 'total': 10}], (0, 14))
    with pytest.raises(ValueError, match='Overlapping'):
        exact_age_population([{'class': '00', 'total': 10}] * 2, (0, 0))
