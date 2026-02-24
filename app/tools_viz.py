"""Chart generation from tool results — returns Chainlit Plotly elements."""

import json
import logging

import plotly.graph_objects as go
import chainlit as cl

logger = logging.getLogger("signal-app.viz")


def maybe_create_charts(tool_name: str, result_json: str) -> list:
    """Generate Plotly charts from tool results. Returns list of cl.Plotly elements."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if isinstance(data, dict) and "error" in data:
        return []

    charts = []

    if tool_name == "discover_baseline":
        charts.extend(_baseline_charts(data))
    elif tool_name == "detect_deviations":
        charts.extend(_deviation_charts(data))
    elif tool_name == "project_forecast":
        charts.extend(_forecast_charts(data))
    elif tool_name == "suggest_segments":
        charts.extend(_segment_score_charts(data))

    return charts


def _baseline_charts(data: dict) -> list:
    """Trend decomposition line chart from baseline results."""
    elements = []
    columns = data.get("columns", data.get("results", {}))

    if isinstance(columns, dict):
        items = columns.items()
    elif isinstance(columns, list):
        items = [(c.get("column", f"col_{i}"), c) for i, c in enumerate(columns)]
    else:
        return elements

    for col_name, col_data in items:
        if not isinstance(col_data, dict):
            continue

        fig = go.Figure()

        # Trend component
        trend = col_data.get("trend", {})
        if isinstance(trend, dict):
            values = trend.get("values", trend.get("data", []))
            timestamps = trend.get("timestamps", trend.get("index", []))
            if values and timestamps:
                fig.add_trace(go.Scatter(
                    x=timestamps, y=values,
                    mode="lines", name="Trend",
                    line=dict(color="#2196F3", width=2),
                ))

        # Seasonal component
        seasonal = col_data.get("seasonal", col_data.get("seasonality", {}))
        if isinstance(seasonal, dict):
            values = seasonal.get("values", seasonal.get("data", []))
            timestamps = seasonal.get("timestamps", seasonal.get("index", []))
            if values and timestamps:
                fig.add_trace(go.Scatter(
                    x=timestamps, y=values,
                    mode="lines", name="Seasonal",
                    line=dict(color="#FF9800", width=1),
                ))

        # Residual component
        residual = col_data.get("residual", col_data.get("residuals", {}))
        if isinstance(residual, dict):
            values = residual.get("values", residual.get("data", []))
            timestamps = residual.get("timestamps", residual.get("index", []))
            if values and timestamps:
                fig.add_trace(go.Scatter(
                    x=timestamps, y=values,
                    mode="lines", name="Residual",
                    line=dict(color="#9E9E9E", width=1),
                    opacity=0.5,
                ))

        if fig.data:
            fig.update_layout(
                title=f"Baseline Decomposition — {col_name}",
                xaxis_title="Date",
                yaxis_title="Value",
                template="plotly_white",
                height=400,
            )
            elements.append(cl.Plotly(
                name=f"baseline_{col_name}",
                figure=fig,
                display="inline",
            ))

    return elements


def _deviation_charts(data: dict) -> list:
    """Anomaly timeline from deviation results."""
    elements = []

    deviations = data.get("deviations", data.get("anomalies", data.get("results", [])))
    if not isinstance(deviations, list) or not deviations:
        return elements

    fig = go.Figure()

    # Group by severity for color coding
    severity_colors = {
        "critical": "#F44336",
        "high": "#FF5722",
        "medium": "#FF9800",
        "low": "#FFC107",
    }

    timestamps = []
    magnitudes = []
    colors = []
    hover_texts = []

    for dev in deviations:
        ts = dev.get("ts_start", dev.get("timestamp", dev.get("date")))
        mag = dev.get("magnitude", dev.get("z_score", dev.get("value", 0)))
        sev = dev.get("severity", "medium")
        col = dev.get("column_name", dev.get("column", ""))
        sig_type = dev.get("signal_type", dev.get("type", ""))

        if ts is not None:
            timestamps.append(ts)
            magnitudes.append(abs(mag) if mag else 0)
            colors.append(severity_colors.get(sev, "#FF9800"))
            hover_texts.append(f"{col}: {sig_type}<br>Severity: {sev}<br>Magnitude: {mag:.2f}" if mag else f"{col}: {sig_type}")

    if timestamps:
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=magnitudes,
            mode="markers",
            marker=dict(
                size=10,
                color=colors,
                line=dict(width=1, color="white"),
            ),
            text=hover_texts,
            hoverinfo="text+x",
            name="Deviations",
        ))

        fig.update_layout(
            title=f"Detected Deviations ({len(deviations)} found)",
            xaxis_title="Date",
            yaxis_title="Magnitude",
            template="plotly_white",
            height=400,
        )

        elements.append(cl.Plotly(
            name="deviations_timeline",
            figure=fig,
            display="inline",
        ))

    return elements


def _forecast_charts(data: dict) -> list:
    """Forecast with confidence interval bands."""
    elements = []

    forecasts = data.get("forecasts", data.get("results", {}))

    if isinstance(forecasts, dict):
        items = forecasts.items()
    elif isinstance(forecasts, list):
        items = [(f.get("column", f"col_{i}"), f) for i, f in enumerate(forecasts)]
    else:
        return elements

    for col_name, fc_data in items:
        if not isinstance(fc_data, dict):
            continue

        fig = go.Figure()

        # Historical data
        hist = fc_data.get("historical", {})
        if isinstance(hist, dict):
            h_vals = hist.get("values", hist.get("data", []))
            h_ts = hist.get("timestamps", hist.get("index", []))
            if h_vals and h_ts:
                fig.add_trace(go.Scatter(
                    x=h_ts, y=h_vals,
                    mode="lines", name="Historical",
                    line=dict(color="#2196F3", width=2),
                ))

        # Forecast line
        forecast = fc_data.get("forecast", fc_data.get("predicted", {}))
        if isinstance(forecast, dict):
            f_vals = forecast.get("values", forecast.get("data", []))
            f_ts = forecast.get("timestamps", forecast.get("index", []))
            if f_vals and f_ts:
                fig.add_trace(go.Scatter(
                    x=f_ts, y=f_vals,
                    mode="lines", name="Forecast",
                    line=dict(color="#4CAF50", width=2, dash="dash"),
                ))

                # Confidence intervals
                ci = fc_data.get("confidence_intervals", fc_data.get("ci", {}))
                if isinstance(ci, dict):
                    for level, bounds in ci.items():
                        if isinstance(bounds, dict):
                            upper = bounds.get("upper", [])
                            lower = bounds.get("lower", [])
                            if upper and lower and len(upper) == len(f_ts):
                                fig.add_trace(go.Scatter(
                                    x=list(f_ts) + list(reversed(f_ts)),
                                    y=list(upper) + list(reversed(lower)),
                                    fill="toself",
                                    fillcolor="rgba(76,175,80,0.1)",
                                    line=dict(width=0),
                                    name=f"CI {level}",
                                    showlegend=True,
                                ))

        if fig.data:
            fig.update_layout(
                title=f"Forecast — {col_name}",
                xaxis_title="Date",
                yaxis_title="Value",
                template="plotly_white",
                height=400,
            )
            elements.append(cl.Plotly(
                name=f"forecast_{col_name}",
                figure=fig,
                display="inline",
            ))

    return elements


def _segment_score_charts(data: dict) -> list:
    """Segment quality score bar chart."""
    elements = []

    rankings = data.get("rankings", data.get("recommendations", data.get("segments", [])))

    if not isinstance(rankings, list) or not rankings:
        return elements

    names = []
    scores = []
    for r in rankings:
        name = r.get("column", r.get("segment_by", r.get("name", "")))
        score = r.get("overall_score", r.get("score", 0))
        if name and score:
            names.append(str(name))
            scores.append(float(score))

    if names:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=scores,
            y=names,
            orientation="h",
            marker_color="#2196F3",
        ))
        fig.update_layout(
            title="Segment Quality Scores",
            xaxis_title="Score",
            yaxis_title="Segmentation",
            template="plotly_white",
            height=max(300, len(names) * 40 + 100),
            yaxis=dict(autorange="reversed"),
        )
        elements.append(cl.Plotly(
            name="segment_scores",
            figure=fig,
            display="inline",
        ))

    return elements
