"""
scoring.py — The "Who's Winning the Bet?" formula

MVP voting is notoriously hard to quantify, but here's the formula:

Weight reasoning:
  fWAR    (25%) — The most complete single-number value measure. MVP voters use it
                   even if they won't admit it. Captures offense, defense, baserunning.

  wRC+    (20%) — Park/league-adjusted offensive production. A 170 wRC+ means 70%
                   better than league average. Best offensive rate stat we have.

  HR      (18%) — Voters LOVE home runs. Always have. Judge won his 62-HR MVP.
                   Unfair? Yes. Reality? Also yes.

  OPS     (15%) — Classic power+patience combo. Easy for casual fans/voters to grok.

  RBI     (10%) — Voters care about counting stats even if saberheads don't.
                   Context-dependent but it's in there.

  Runs    (6%)  — Offensive contribution beyond your own plate appearances.

  SB      (6%)  — Baserunning value. Roman is likely faster, Judge is not.

The score is the fraction of total "value" each player has. If they're equal in
everything, they each get 50. If Judge leads every category, he gets closer to 100.
Final scores always sum to 100.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Stat weights — must sum to 1.0
WEIGHTS = {
    "fwar":     0.25,
    "wrc_plus": 0.20,
    "hr":       0.18,
    "ops":      0.15,
    "rbi":      0.10,
    "runs":     0.06,
    "sb":       0.06,
}

# Fallback weights if WAR/wRC+ are unavailable (FanGraphs down)
WEIGHTS_NO_ADVANCED = {
    "hr":  0.28,
    "ops": 0.28,
    "rbi": 0.18,
    "runs": 0.14,
    "sb":  0.12,
}


def calculate_bet_score(judge_stats: dict, roman_stats: dict) -> dict:
    """
    Calculate the "Who's Winning?" bet score.

    Returns:
        {
            "judge": 62,
            "roman": 38,
            "leader": "judge",
            "categories": {
                "hr": {"judge": 28, "roman": 18, "leader": "judge"},
                ...
            }
        }
    """
    # Decide which weights to use based on data availability
    has_advanced = (
        _get_float(judge_stats, "fwar") is not None or
        _get_float(roman_stats, "fwar") is not None
    )
    weights = WEIGHTS if has_advanced else WEIGHTS_NO_ADVANCED

    judge_total = 0.0
    roman_total = 0.0
    categories = {}

    for stat, weight in weights.items():
        j_val = _get_float(judge_stats, stat) or 0.0
        r_val = _get_float(roman_stats, stat) or 0.0
        combined = j_val + r_val

        if combined == 0:
            j_frac = r_frac = 0.5
        else:
            j_frac = j_val / combined
            r_frac = r_val / combined

        j_points = j_frac * weight
        r_points = r_frac * weight

        judge_total += j_points
        roman_total += r_points

        # Normalize category scores to sum to 100 for display
        total_weight = j_points + r_points
        if total_weight > 0:
            j_cat_score = round((j_points / total_weight) * 100)
        else:
            j_cat_score = 50

        categories[stat] = {
            "judge_val": j_val,
            "roman_val": r_val,
            "judge_score": j_cat_score,
            "roman_score": 100 - j_cat_score,
            "leader": "judge" if j_val > r_val else "roman" if r_val > j_val else "tied",
            "weight": weight,
        }

    # Convert to 0-100 scores that sum to 100
    grand_total = judge_total + roman_total
    if grand_total > 0:
        judge_score = round((judge_total / grand_total) * 100)
    else:
        judge_score = 50
    roman_score = 100 - judge_score

    leader = "tied"
    if abs(judge_score - roman_score) > 2:
        leader = "judge" if judge_score > roman_score else "roman"

    return {
        "judge": judge_score,
        "roman": roman_score,
        "leader": leader,
        "categories": categories,
        "weights_used": "advanced" if has_advanced else "basic",
    }


def _get_float(stats: dict, key: str) -> Optional[float]:
    """
    Safely extract a numeric value from a stats dict.
    Handles string AVG/OBP/SLG like ".285" and None gracefully.
    """
    val = stats.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return None
    return None
