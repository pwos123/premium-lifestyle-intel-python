"""Article lifecycle helpers shared by routes and background jobs."""


def recompute_gate2_tier(d1: int | None, d2: int | None, d3: int | None) -> str:
    d1 = d1 or 0
    d2 = d2 or 0
    d3 = d3 or 0
    total = d1 + d2 + d3
    if d1 >= 2 and total >= 7:
        return "A"
    if d1 >= 1 and total >= 5:
        return "B"
    if total <= 2:
        return "D"
    return "C"
