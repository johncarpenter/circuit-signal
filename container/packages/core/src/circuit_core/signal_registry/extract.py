"""Extract seasonal arrays from baseline results for signal registration."""


def extract_seasonal_arrays(baseline_result: dict) -> dict:
    """Read seasonality list from baseline result JSON, return typed arrays.

    Returns dict with keys: weekly (float[7]|None), hourly (float[24]|None),
    monthly (float[12]|None).
    """
    arrays: dict = {"weekly": None, "hourly": None, "monthly": None}

    seasonality = baseline_result.get("seasonality", [])
    for s in seasonality:
        label = s.get("period_label", "")
        values = s.get("values")
        if values is None:
            continue

        if label == "weekly" and len(values) == 7:
            arrays["weekly"] = [float(v) for v in values]
        elif label == "annual" and len(values) == 12:
            arrays["monthly"] = [float(v) for v in values]
        elif label == "daily" and len(values) == 24:
            arrays["hourly"] = [float(v) for v in values]

    return arrays
