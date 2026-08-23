from analysis.evidence import extract_evidence, contradiction_rate
from analysis.market_intelligence import edge_score, parlay_probability
from analysis.prop_model import simulate_prop, no_vig_probability, expected_value


def test_injury_evidence_is_classified_and_weighted():
    result = extract_evidence("Jane Doe ruled out with a knee injury", verified=True, source_type="news")
    assert result.classification == "injury"
    assert result.impact > .2 and result.reliability >= .7


def test_monte_carlo_is_seeded_and_returns_probability():
    result = simulate_prop([10, 12, 11, 14, 8, 13], 10.5, simulations=500, seed=2)
    assert result.simulations == 500
    assert 0 <= result.over_probability <= 1


def test_market_math_and_correlation_bounds():
    over, under = no_vig_probability(-110, -110)
    assert round(over + under, 5) == 1
    assert expected_value(.6, 100) > 0
    assert 0 <= parlay_probability([.6, .6], .25) <= 1
    score = edge_score(.60, .52, .8, 25)
    assert score["recommended"]
