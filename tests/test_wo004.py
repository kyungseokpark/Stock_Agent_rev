import pandas as pd


def test_select_top_candidates_prefers_composite_score_when_enabled():
    from src.recommendation_quality import select_top_candidates

    df = pd.DataFrame(
        [
            {"ticker": "CHART", "adjusted_score": 95, "composite_score": 60, "final_score": 90, "risk_reward": 2.0, "is_sample_data": False},
            {"ticker": "FORCE", "adjusted_score": 70, "composite_score": 88, "final_score": 70, "risk_reward": 1.5, "is_sample_data": False},
        ]
    )
    config = {
        "composite": {"enabled": True},
        "screening": {"min_score_for_candidate": 0},
        "scoring_adjustment": {"use_adjusted_score": True, "exclude_sample_data": True},
    }

    selected = select_top_candidates(df, config, top_n=1)

    assert selected["ticker"].tolist() == ["FORCE"]
