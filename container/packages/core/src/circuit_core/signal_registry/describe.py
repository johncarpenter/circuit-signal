"""Generate text descriptions for signals — template-based, no LLM required."""


def generate_description(signal_data: dict) -> str:
    """Generate a deterministic text description from signal metrics.

    Uses templates to describe trend direction, seasonality strength,
    deviation patterns, and peak timing.
    """
    parts = []

    segment = signal_data.get("segment", "unknown")
    dataset = signal_data.get("dataset_name", "")
    parts.append(f"Signal for '{segment}' in {dataset}." if dataset else f"Signal for '{segment}'.")

    # Trend
    slope = signal_data.get("trend_slope")
    if slope is not None:
        if abs(slope) < 0.001:
            parts.append("Trend is flat with no significant growth or decline.")
        elif slope > 0:
            parts.append(f"Shows an increasing trend (slope={slope:.4f}).")
        else:
            parts.append(f"Shows a decreasing trend (slope={slope:.4f}).")

    # Seasonality
    strength = signal_data.get("seasonality_strength")
    if strength is not None:
        if strength > 0.7:
            parts.append(f"Strong seasonality (strength={strength:.2f}).")
        elif strength > 0.3:
            parts.append(f"Moderate seasonality (strength={strength:.2f}).")
        elif strength > 0.05:
            parts.append(f"Weak seasonality (strength={strength:.2f}).")
        else:
            parts.append("No significant seasonal pattern.")

    # Peak timing from seasonal arrays
    weekly = signal_data.get("seasonal_weekly")
    if weekly and len(weekly) == 7:
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        peak_day = days[weekly.index(max(weekly))]
        parts.append(f"Weekly peak on {peak_day}.")

    monthly = signal_data.get("seasonal_monthly")
    if monthly and len(monthly) == 12:
        months = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
        peak_month = months[monthly.index(max(monthly))]
        parts.append(f"Annual peak in {peak_month}.")

    # Deviations
    dev_count = signal_data.get("deviation_count_90d")
    if dev_count is not None:
        if dev_count == 0:
            parts.append("No deviations detected in the last 90 days.")
        elif dev_count <= 3:
            parts.append(f"{dev_count} deviation(s) in the last 90 days.")
        else:
            parts.append(f"Elevated anomaly activity with {dev_count} deviations in 90 days.")

    critical_pct = signal_data.get("critical_pct")
    if critical_pct is not None and critical_pct > 0.1:
        parts.append(f"{critical_pct:.0%} of deviations are critical severity.")

    # Change points
    change_points = signal_data.get("change_points")
    if change_points and len(change_points) > 0:
        parts.append(f"{len(change_points)} structural change point(s) detected.")

    return " ".join(parts)


def generate_descriptions(signals_data: list[dict]) -> list[str]:
    """Generate descriptions for a batch of signals."""
    return [generate_description(s) for s in signals_data]
