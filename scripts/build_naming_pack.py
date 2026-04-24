#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = (
    ROOT.parent
    / "gridmodel-datasets"
    / "08_Data"
    / "08.01_Seed"
    / "scripts"
    / "output"
)

SOURCE_FILES = {
    "component_types": "06_component_types.json",
    "attributes": "05_attributes.json",
    "lib_components": "08_lib_components.json",
    "components": "14a_components.json",
    "attrs": "14b_component_custom_attrs.json",
    "connections": "14f_connections.json",
    "raw_substations": "00_raw/unified_substations.json",
}

UNNAMED_SUBSTATION_RE = re.compile(r"^Unnamed\s+([A-Z]+)\s+Substation\s+(\d+)$")
GENERIC_NAME_RE = re.compile(r"^(\d+\s*)?(substation|switching station|receiving station|distributing station)(\s+\d+)?$", re.I)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
STOPWORDS = {
    "substation",
    "station",
    "receiving",
    "switching",
    "distributing",
    "distribution",
    "transmission",
    "power",
    "electricity",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build substation and line naming research pack.")
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    return parser.parse_args()


def resolve_source_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    if os.environ.get("GRIDMODEL_DATASET_OUTPUT_ROOT"):
        return Path(os.environ["GRIDMODEL_DATASET_OUTPUT_ROOT"]).expanduser().resolve()
    if os.environ.get("GRIDMODEL_DATASETS_ROOT"):
        return (
            Path(os.environ["GRIDMODEL_DATASETS_ROOT"]).expanduser().resolve()
            / "08_Data"
            / "08.01_Seed"
            / "scripts"
            / "output"
        )
    return DEFAULT_OUTPUT_ROOT.resolve()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as gz_handle:
            with io.TextIOWrapper(gz_handle, encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("kV", "").replace("KV", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_name(name: str) -> str:
    tokens = NON_ALNUM_RE.sub(" ", (name or "").lower().replace("&", " and ")).split()
    return " ".join(token for token in tokens if token not in STOPWORDS)


def is_synthetic_substation_name(name: str) -> bool:
    clean = " ".join((name or "").split())
    return bool(UNNAMED_SUBSTATION_RE.match(clean) or GENERIC_NAME_RE.match(clean))


def component_osm_hint(name: str) -> tuple[str | None, str | None]:
    match = UNNAMED_SUBSTATION_RE.match(" ".join((name or "").split()))
    if not match:
        return None, None
    return match.group(1), match.group(2)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geometry_length_m(geometry: dict[str, Any] | None) -> float:
    if not geometry or geometry.get("type") != "LineString":
        return 0.0
    coords = geometry.get("coordinates") or []
    total = 0.0
    for start, end in zip(coords, coords[1:]):
        lon1, lat1 = start
        lon2, lat2 = end
        total += haversine_m(lat1, lon1, lat2, lon2)
    return total


def bbox_for_geometries(geometries: list[dict[str, Any]]) -> list[float] | None:
    points: list[list[float]] = []
    for geometry in geometries:
        if geometry and geometry.get("type") == "LineString":
            points.extend(geometry.get("coordinates") or [])
    if not points:
        return None
    return [
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    ]


def compact_line_for_station(line: dict[str, Any], station_id: str, substations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    other_id = line.get("to_substation_id") if line.get("from_substation_id") == station_id else line.get("from_substation_id")
    other = substations.get(other_id or "")
    return {
        "line_id": line["line_id"],
        "line_name": line["line_name"],
        "nominal_voltage_kv": line["nominal_voltage_kv"],
        "corridor_role": line["corridor_role"],
        "endpoint_confidence": line["endpoint_confidence"],
        "wire_count": line["wire_count"],
        "line_length_m": line["line_length_m"],
        "other_substation_id": other_id,
        "other_substation_name": other.get("current_name") if other else None,
    }


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    source_root = resolve_source_root(args.source_root)
    missing = [name for name, rel in SOURCE_FILES.items() if not (source_root / rel).exists()]
    if missing:
        raise FileNotFoundError(f"Missing source files in {source_root}: {missing}")

    component_types = load_json(source_root / SOURCE_FILES["component_types"])
    attributes = load_json(source_root / SOURCE_FILES["attributes"])
    lib_components = load_json(source_root / SOURCE_FILES["lib_components"])
    components = load_json(source_root / SOURCE_FILES["components"])
    attrs = load_json(source_root / SOURCE_FILES["attrs"])
    connections = load_json(source_root / SOURCE_FILES["connections"])
    raw_substations = load_json(source_root / SOURCE_FILES["raw_substations"])

    component_type_names = {row["Id"]: row["Name"] for row in component_types}
    attr_names = {row["Id"]: row["Name"] for row in attributes}
    lib_type_by_component = {
        row["Id"]: component_type_names[row["TypeId"]]
        for row in lib_components
        if row.get("TypeId") in component_type_names
    }
    component_type_by_id = {
        row["Id"]: lib_type_by_component.get(row["LibComponentId"])
        for row in components
    }
    attrs_by_component: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for row in attrs:
        attrs_by_component[row["ComponentId"]][attr_names[row["AttributeId"]]] = row["Value"]

    components_by_id = {row["Id"]: row for row in components}
    line_connections: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in connections:
        line_connections[row["ByComponentId"]].append(row)
    line_wire_counts: collections.Counter[str] = collections.Counter(
        row.get("ParentId")
        for row in components
        if component_type_by_id.get(row["Id"]) == "Wire" and row.get("ParentId")
    )

    raw_by_region_osm: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    raw_by_exact_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    raw_by_normalized_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in raw_substations:
        osm_id = str(row.get("osm_id") or "")
        for region_key in filter(None, {row.get("region"), row.get("region_code")}):
            raw_by_region_osm[(str(region_key), osm_id)].append(row)
        if row.get("name"):
            cleaned = " ".join(row["name"].split())
            raw_by_exact_name[cleaned].append(row)
            raw_by_normalized_name[normalize_name(cleaned)].append(row)

    def choose_raw(candidates: list[dict[str, Any]], voltage_kv: float | None) -> dict[str, Any] | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if voltage_kv is not None:
            matching_voltage = []
            for row in candidates:
                raw_voltage = parse_float(row.get("max_voltage_kv")) or parse_float(row.get("voltage_kv"))
                if raw_voltage is not None and math.isclose(raw_voltage, voltage_kv):
                    matching_voltage.append(row)
            if matching_voltage:
                candidates = matching_voltage
        shared = {(row.get("osm_id"), row.get("lat"), row.get("lon"), row.get("max_voltage_kv")) for row in candidates}
        if len(shared) == 1:
            return sorted(candidates, key=lambda row: (row.get("region_code") or "", row.get("id") or ""))[0]
        return sorted(candidates, key=lambda row: (row.get("name") or "", row.get("id") or ""))[0]

    substations: dict[str, dict[str, Any]] = {}
    for component in sorted(components, key=lambda row: row["Id"]):
        if component_type_by_id.get(component["Id"]) != "Substation":
            continue
        component_attrs = attrs_by_component.get(component["Id"], {})
        nominal_kv = parse_float(component_attrs.get("Nominal Voltage"))
        high_side_kv = parse_float(component_attrs.get("High Side Voltage"))
        resolved_kv = high_side_kv or nominal_kv
        current_name = component["Name"]
        region_hint, osm_hint = component_osm_hint(current_name)
        raw_match = None
        match_method = "unresolved"
        if region_hint and osm_hint:
            raw_match = choose_raw(raw_by_region_osm.get((region_hint, osm_hint), []), resolved_kv)
            if raw_match:
                match_method = "synthetic_name_region_osm"
        if raw_match is None:
            raw_match = choose_raw(raw_by_exact_name.get(" ".join(current_name.split()), []), resolved_kv)
            if raw_match:
                match_method = "exact_name"
        if raw_match is None:
            raw_match = choose_raw(raw_by_normalized_name.get(normalize_name(current_name), []), resolved_kv)
            if raw_match:
                match_method = "normalized_name"
        raw_voltage = parse_float(raw_match.get("max_voltage_kv")) if raw_match else None
        resolved_kv = resolved_kv or raw_voltage
        needs_name = is_synthetic_substation_name(current_name) or not (raw_match and raw_match.get("name"))
        lat = raw_match.get("lat") if raw_match else None
        lon = raw_match.get("lon") if raw_match else None
        raw_name = raw_match.get("name") if raw_match else None
        region = (raw_match or {}).get("region_code") or region_hint
        queries = []
        if lat is not None and lon is not None:
            queries.append(f"{lat}, {lon} electrical substation")
        if osm_hint:
            queries.append(f"OpenStreetMap power=substation {osm_hint}")
        if region and resolved_kv:
            queries.append(f"{region} {resolved_kv:g} kV substation {raw_name or current_name}")
        substations[component["Id"]] = {
            "substation_id": component["Id"],
            "current_name": current_name,
            "needs_name_research": needs_name,
            "name_status": "synthetic_or_missing" if needs_name else "has_source_name",
            "region_hint": region,
            "voltage": {
                "nominal_kv": nominal_kv,
                "high_side_kv": high_side_kv,
                "resolved_kv": resolved_kv,
                "raw_max_voltage_kv": raw_voltage,
            },
            "raw_evidence": {
                "match_method": match_method,
                "raw_substation_id": raw_match.get("id") if raw_match else None,
                "osm_id": raw_match.get("osm_id") if raw_match else osm_hint,
                "osm_url": f"https://www.openstreetmap.org/node/{raw_match.get('osm_id')}" if raw_match and raw_match.get("osm_id") else None,
                "raw_name": raw_name,
                "lat": lat,
                "lon": lon,
                "operator": raw_match.get("operator") if raw_match else None,
                "operator_source": raw_match.get("operator_source") if raw_match else None,
                "substation_type": raw_match.get("substation_type") if raw_match else None,
                "raw_voltage_kv": raw_match.get("voltage_kv") if raw_match else None,
                "raw_min_voltage_kv": raw_match.get("min_voltage_kv") if raw_match else None,
            },
            "research_hints": {
                "search_queries": queries,
                "expected_sources": [
                    "utility transmission/substation maps",
                    "ISO/utility interconnection documents",
                    "OpenStreetMap object history/tags",
                    "public planning/permit documents",
                    "satellite/map labels when corroborated by another source",
                ],
            },
        }

    line_rows: list[dict[str, Any]] = []
    station_line_index: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for component in sorted(components, key=lambda row: row["Id"]):
        if component_type_by_id.get(component["Id"]) != "Line":
            continue
        component_attrs = attrs_by_component.get(component["Id"], {})
        geometries = [row.get("Geometry") for row in line_connections.get(component["Id"], []) if row.get("Geometry")]
        from_station = component_attrs.get("From Substation Id")
        to_station = component_attrs.get("To Substation Id")
        line = {
            "line_id": component["Id"],
            "line_name": component["Name"],
            "nominal_voltage_kv": parse_float(component_attrs.get("Nominal Voltage")),
            "line_type": component_attrs.get("Line Type"),
            "corridor_role": component_attrs.get("Corridor Role"),
            "endpoint_confidence": component_attrs.get("Endpoint Confidence"),
            "from_substation_id": from_station,
            "from_substation_name": substations.get(from_station or "", {}).get("current_name"),
            "to_substation_id": to_station,
            "to_substation_name": substations.get(to_station or "", {}).get("current_name"),
            "wire_count": line_wire_counts[component["Id"]],
            "member_count": len(line_connections.get(component["Id"], [])),
            "line_length_m": round(sum(geometry_length_m(geometry) for geometry in geometries), 3) if geometries else None,
            "bbox": bbox_for_geometries(geometries),
        }
        line_rows.append(line)
        if from_station in substations:
            station_line_index[from_station].append(line)
        if to_station in substations and to_station != from_station:
            station_line_index[to_station].append(line)

    substation_rows: list[dict[str, Any]] = []
    for station_id, station in substations.items():
        connected = sorted(
            station_line_index.get(station_id, []),
            key=lambda row: (
                -(row["nominal_voltage_kv"] or -1),
                row["corridor_role"] or "",
                row["line_name"],
                row["line_id"],
            ),
        )
        station = dict(station)
        station["connected_line_count"] = len(connected)
        station["connected_lines"] = [compact_line_for_station(line, station_id, substations) for line in connected[:30]]
        station["connected_lines_truncated"] = max(0, len(connected) - 30)
        station["neighbor_substation_ids"] = sorted(
            {
                item["other_substation_id"]
                for item in station["connected_lines"]
                if item.get("other_substation_id") in substations
            }
        )
        station["recommended_review_priority"] = (
            "high"
            if station["needs_name_research"] and (station["voltage"]["resolved_kv"] or 0) >= 220
            else "medium"
            if station["needs_name_research"] and station["connected_line_count"]
            else "low"
        )
        substation_rows.append(station)

    substation_rows.sort(
        key=lambda row: (
            {"high": 0, "medium": 1, "low": 2}[row["recommended_review_priority"]],
            -(row["voltage"]["resolved_kv"] or -1),
            row["current_name"],
            row["substation_id"],
        )
    )
    line_rows.sort(key=lambda row: (-(row["nominal_voltage_kv"] or -1), row["line_name"], row["line_id"]))

    naming_dir = repo_root / "naming"
    substation_path = naming_dir / "substation_naming_pack.jsonl.gz"
    line_path = naming_dir / "line_context_pack.jsonl.gz"
    substation_json_path = naming_dir / "substation_naming_pack.json"
    line_json_path = naming_dir / "line_context_pack.json"
    write_jsonl_gz(substation_path, substation_rows)
    write_jsonl_gz(line_path, line_rows)
    write_json(substation_json_path, substation_rows)
    write_json(line_json_path, line_rows)

    summary = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_root": str(source_root),
        "files": [
            {
                "path": "naming/substation_naming_pack.jsonl.gz",
                "row_count": len(substation_rows),
                "size_bytes": substation_path.stat().st_size,
                "sha256": sha256_file(substation_path),
                "lfs_expected": True,
            },
            {
                "path": "naming/substation_naming_pack.json",
                "row_count": len(substation_rows),
                "size_bytes": substation_json_path.stat().st_size,
                "sha256": sha256_file(substation_json_path),
                "lfs_expected": False,
            },
            {
                "path": "naming/line_context_pack.jsonl.gz",
                "row_count": len(line_rows),
                "size_bytes": line_path.stat().st_size,
                "sha256": sha256_file(line_path),
                "lfs_expected": True,
            },
            {
                "path": "naming/line_context_pack.json",
                "row_count": len(line_rows),
                "size_bytes": line_json_path.stat().st_size,
                "sha256": sha256_file(line_json_path),
                "lfs_expected": False,
            },
        ],
        "counts": {
            "substations_total": len(substation_rows),
            "substations_needing_name_research": sum(1 for row in substation_rows if row["needs_name_research"]),
            "high_priority_substations": sum(1 for row in substation_rows if row["recommended_review_priority"] == "high"),
            "lines_total": len(line_rows),
            "lines_by_role": dict(sorted(collections.Counter(row["corridor_role"] or "UNKNOWN" for row in line_rows).items())),
            "lines_by_voltage": dict(
                sorted(
                    collections.Counter(
                        f"{row['nominal_voltage_kv']:g}" if row["nominal_voltage_kv"] is not None else "UNKNOWN"
                        for row in line_rows
                    ).items(),
                    key=lambda item: parse_float(item[0]) or -1,
                    reverse=True,
                )
            ),
        },
        "truth_policy": [
            "This pack is evidence for human/LLM research, not canonical naming truth.",
            "Do not overwrite source names without cited evidence and confidence.",
            "Prefer utility/ISO/planning documents over map label guesses.",
            "Keep proposed names separate from current_name until reviewed.",
        ],
    }
    write_json(naming_dir / "manifest.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
