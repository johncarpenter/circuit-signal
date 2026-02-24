"""
Tools: register_source, list_sources

Manage the registry of data sources that feed signals into the correlation engine.
"""

import json
import logging

from signal_correlation.store import SignalStore

logger = logging.getLogger("signal-correlation.sources")


def run_register_source(
    store: SignalStore,
    source_id: str,
    name: str,
    description: str | None = None,
    domain: str = "other",
    geography: dict | None = None,
    entity_keys: list[str] | None = None,
    baseline_path: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Register or update a data source."""
    source = {
        "source_id": source_id,
        "name": name,
        "description": description,
        "domain": domain,
        "geography": geography or {},
        "entity_keys": entity_keys,
        "baseline_path": baseline_path,
        "tags": tags or [],
    }

    status = store.upsert_source(source)
    total = store.count_sources()

    return {
        "source_id": source_id,
        "status": status,
        "total_sources": total,
    }


def run_list_sources(store: SignalStore) -> dict:
    """List all registered sources with signal counts."""
    sources = store.list_sources()

    result = []
    for s in sources:
        tags = s.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []

        result.append({
            "source_id": s["source_id"],
            "name": s["name"],
            "domain": s.get("domain"),
            "geography": {"region": s.get("region")},
            "signal_count": s.get("signal_count", 0),
            "latest_signal": str(s["latest_signal"]) if s.get("latest_signal") else None,
            "tags": tags or [],
        })

    return {"sources": result}
