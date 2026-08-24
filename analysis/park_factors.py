"""
analysis/park_factors.py

MLB park factors — how much each stadium inflates or suppresses
offense. Based on established multi-year park factor data
(100 = neutral, >100 = hitter-friendly, <100 = pitcher-friendly).

Used to adjust batter hit props up in hitter parks (Coors) and
down in pitcher parks (Petco, Oracle).
"""

# Park factors: 100 = league average.
# Sources: multi-year aggregate hit/run factors (public data).
# hits_factor affects batter hit props; hr_factor affects HR props.
PARK_FACTORS = {
    "Coors Field":            {"runs": 112, "hits": 109, "hr": 110},  # Denver altitude
    "Fenway Park":            {"runs": 106, "hits": 107, "hr": 97},   # Green Monster
    "Great American Ball Park": {"runs": 104, "hits": 101, "hr": 116}, # HR-friendly
    "Camden Yards":           {"runs": 103, "hits": 101, "hr": 108},
    "Chase Field":            {"runs": 103, "hits": 104, "hr": 102},
    "Globe Life Field":       {"runs": 102, "hits": 102, "hr": 101},
    "Wrigley Field":          {"runs": 102, "hits": 103, "hr": 101},  # wind-dependent
    "Nationals Park":         {"runs": 101, "hits": 100, "hr": 102},
    "Citizens Bank Park":     {"runs": 101, "hits": 99,  "hr": 109},  # HR bandbox
    "Yankee Stadium":         {"runs": 101, "hits": 98,  "hr": 112},  # short porch
    "Truist Park":            {"runs": 100, "hits": 100, "hr": 102},
    "Rogers Centre":          {"runs": 100, "hits": 101, "hr": 103},
    "Target Field":           {"runs": 100, "hits": 100, "hr": 99},
    "Angel Stadium":          {"runs": 99,  "hits": 100, "hr": 101},
    "Minute Maid Park":       {"runs": 99,  "hits": 101, "hr": 102},
    "Kauffman Stadium":       {"runs": 99,  "hits": 102, "hr": 91},   # big outfield
    "Progressive Field":      {"runs": 98,  "hits": 99,  "hr": 98},
    "Busch Stadium":          {"runs": 98,  "hits": 99,  "hr": 94},
    "American Family Field":   {"runs": 98,  "hits": 99,  "hr": 103},
    "Dodger Stadium":         {"runs": 98,  "hits": 97,  "hr": 104},
    "Guaranteed Rate Field":  {"runs": 98,  "hits": 99,  "hr": 104},
    "Rate Field":             {"runs": 98,  "hits": 99,  "hr": 104},
    "loanDepot park":         {"runs": 97,  "hits": 98,  "hr": 95},   # pitcher park
    "Citi Field":             {"runs": 97,  "hits": 98,  "hr": 96},
    "Comerica Park":          {"runs": 97,  "hits": 99,  "hr": 94},   # deep gaps
    "PNC Park":               {"runs": 97,  "hits": 100, "hr": 92},
    "Petco Park":             {"runs": 95,  "hits": 96,  "hr": 97},   # pitcher park
    "Oracle Park":            {"runs": 94,  "hits": 97,  "hr": 89},   # SF, marine air
    "T-Mobile Park":          {"runs": 93,  "hits": 96,  "hr": 95},   # pitcher park
    "Oakland Coliseum":       {"runs": 93,  "hits": 96,  "hr": 92},   # huge foul ground
    "Sutter Health Park":     {"runs": 100, "hits": 100, "hr": 100},  # A's temp park
    "Tropicana Field":        {"runs": 96,  "hits": 98,  "hr": 95},
}


def get_park_factor(venue: str, stat_type: str = "hits") -> float:
    """
    Return the park factor multiplier for a stat (as a decimal, e.g. 1.09).
    stat_type: "hits", "runs", or "hr".
    Returns 1.0 (neutral) if venue unknown.
    """
    if not venue:
        return 1.0
    # Match venue (fuzzy)
    for name, factors in PARK_FACTORS.items():
        if name.lower() in venue.lower() or venue.lower() in name.lower():
            key = stat_type if stat_type in factors else "hits"
            return factors[key] / 100.0
    return 1.0


def park_score_adjustment(venue: str, is_hr_prop: bool = False) -> float:
    """
    Return a score adjustment (-10 to +10 points) based on park.
    Hitter-friendly parks add points to batter props, pitcher parks subtract.
    """
    factor = get_park_factor(venue, "hr" if is_hr_prop else "hits")
    # factor 1.09 -> +9 * scaling; factor 0.94 -> -6
    return round((factor - 1.0) * 100, 1)


def park_note(venue: str) -> str:
    """Human-readable park tendency note."""
    factor = get_park_factor(venue, "hits")
    if factor >= 1.05:
        return f"🟢 Hitter-friendly park ({int(factor*100)})"
    elif factor <= 0.95:
        return f"🔴 Pitcher-friendly park ({int(factor*100)})"
    return f"➖ Neutral park ({int(factor*100)})"
