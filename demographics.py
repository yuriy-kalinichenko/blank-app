"""Validate WorldPop age bands before labelling a count as an exact age range."""
import math


def exact_age_population(pyramid, age_range=(0, 18)):
    """WorldPop classes are [0,1), [1,5), then five-year bands.

    Never allocate a fraction of an age band without an explicit estimation
    model. In particular, class 15 includes age 19 and cannot give exact 0–18.
    """
    lower, upper = age_range[0], age_range[1] + 1
    total, covered = 0.0, set()
    for row in pyramid:
        try:
            start = int(row['class'])
        except (KeyError, ValueError, TypeError):
            raise ValueError('WorldPop age-band metadata is unavailable; exact age count is unknown.')
        end = 1 if start == 0 else 5 if start == 1 else start + 5
        if start >= upper or end <= lower:
            continue
        if start < lower or end > upper:
            raise ValueError(
                f'Exact ages {lower}–{upper - 1} unavailable: WorldPop band '
                f'{start}–{end - 1} crosses the requested boundary. '
                'No within-band age allocation has been assumed.'
            )
        ages = set(range(start, end))
        if covered & ages:
            raise ValueError('Overlapping WorldPop age bands; exact count is unknown.')
        try:
            value = (float(row['total']) if row.get('total') is not None
                     else float(row['male']) + float(row['female']))
        except (KeyError, TypeError, ValueError):
            raise ValueError('WorldPop age-band count is missing; exact count is unknown.')
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid WorldPop age-band count; exact count is unknown.')
        total += value
        covered |= ages
    if covered != set(range(lower, upper)):
        raise ValueError('Incomplete WorldPop age-band coverage; exact age count is unknown.')
    return total
