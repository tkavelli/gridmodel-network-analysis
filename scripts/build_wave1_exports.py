#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import re
import sys
import io
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

UNNAMED_SUBSTATION_RE = re.compile(r"^Unnamed\s+([A-Z]+)\s+Substation\s+(\d+)$")
GENERIC_PAREN_RE = re.compile(r"\s*\((power|electricity)\)\s*$", re.IGNORECASE)
RECEIVING_PREFIX_RE = re.compile(r"^Receiving Station [A-Z0-9]+ -\s*", re.IGNORECASE)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

STATION_STOPWORDS = {
    "substation",
    "station",
    "receiving",
    "switching",
    "distributing",
    "distribution",
    "transmission",
}

WAVE1_VOLTAGES = {220.0, 230.0, 500.0}
SOURCE_FILES = {
    "component_types": "06_component_types.json",
    "attributes": "05_attributes.json",
    "lib_components": "08_lib_components.json",
    "components": "14a_components.json",
    "attrs": "14b_component_custom_attrs.json",
    "connections": "14f_connections.json",
    "membership": "14g_membership.json",
    "raw_nodes": "00_raw/unified_nodes.json",
    "raw_edges": "00_raw/unified_edges.json",
    "raw_substations": "00_raw/unified_substations.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Wave 1 EHV graph and raw analysis exports.")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Seed output root. Defaults to GRIDMODEL_DATASET_OUTPUT_ROOT or sibling gridmodel-datasets output.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Target analysis repo root.",
    )
    return parser.parse_args()


def resolve_source_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    env_output = os.environ.get("GRIDMODEL_DATASET_OUTPUT_ROOT")
    if env_output:
        return Path(env_output).expanduser().resolve()
    env_repo = os.environ.get("GRIDMODEL_DATASETS_ROOT")
    if env_repo:
        return (
            Path(env_repo).expanduser().resolve()
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


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("kV", "").replace("KV", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def normalize_tier(voltage_kv: float | None) -> str | None:
    if voltage_kv is None:
        return None
    if math.isclose(voltage_kv, 500.0):
        return "EHV_500"
    if math.isclose(voltage_kv, 220.0) or math.isclose(voltage_kv, 230.0):
        return "EHV_220_230"
    return None


def clean_station_name(name: str) -> str:
    text = " ".join((name or "").strip().split())
    text = GENERIC_PAREN_RE.sub("", text).strip().strip('"').strip("'").strip()
    return text.rstrip(" ,;:.")


def normalized_station_name(name: str) -> str:
    text = clean_station_name(name)
    text = RECEIVING_PREFIX_RE.sub("", text)
    text = text.lower().replace("&", " and ")
    tokens = NON_ALNUM_RE.sub(" ", text).split()
    filtered = [token for token in tokens if token not in STATION_STOPWORDS]
    if len(filtered) > 1:
        filtered = [token for token in filtered if len(token) > 1 or token.isdigit()]
    return " ".join(filtered)


def stable_sort_key(record: dict[str, Any], *keys: str) -> tuple[Any, ...]:
    return tuple(record.get(key) for key in keys)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_mtime(source_paths: list[Path]) -> str:
    latest = max(path.stat().st_mtime for path in source_paths)
    return dt.datetime.fromtimestamp(latest, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    source_root = resolve_source_root(args.source_root)

    missing = [name for name, rel in SOURCE_FILES.items() if not (source_root / rel).exists()]
    if missing:
        raise FileNotFoundError(f"Missing source files in {source_root}: {missing}")

    source_paths = [source_root / rel for rel in SOURCE_FILES.values()]

    component_types = load_json(source_root / SOURCE_FILES["component_types"])
    attributes = load_json(source_root / SOURCE_FILES["attributes"])
    lib_components = load_json(source_root / SOURCE_FILES["lib_components"])
    components = load_json(source_root / SOURCE_FILES["components"])
    attrs = load_json(source_root / SOURCE_FILES["attrs"])
    connections = load_json(source_root / SOURCE_FILES["connections"])
    membership = load_json(source_root / SOURCE_FILES["membership"])
    raw_substations = load_json(source_root / SOURCE_FILES["raw_substations"])

    component_type_names = {row["Id"]: row["Name"] for row in component_types}
    attr_names = {row["Id"]: row["Name"] for row in attributes}
    lib_type_by_component = {
        row["Id"]: component_type_names[row["TypeId"]]
        for row in lib_components
        if row.get("TypeId") in component_type_names
    }

    components_by_id = {row["Id"]: row for row in components}
    component_type_by_id = {
        component["Id"]: lib_type_by_component[component["LibComponentId"]]
        for component in components
    }

    attrs_by_component: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for row in attrs:
        attrs_by_component[row["ComponentId"]][attr_names[row["AttributeId"]]] = row["Value"]

    line_connections: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in connections:
        line_connections[row["ByComponentId"]].append(row)

    line_wire_counts: collections.Counter[str] = collections.Counter(
        component["ParentId"]
        for component in components
        if component_type_by_id[component["Id"]] == "Wire" and component.get("ParentId")
    )

    substation_member_map: dict[str, str] = {}
    for row in membership:
        if row["Type"] != "SUBSTATION_MEMBER":
            continue
        parent_type = component_type_by_id.get(row["ParentCId"])
        member_type = component_type_by_id.get(row["MemberCId"])
        if parent_type == "Substation":
            substation_member_map[row["MemberCId"]] = row["ParentCId"]

    parent_by_id = {row["Id"]: row.get("ParentId") for row in components}
    owning_substation_cache: dict[str, str | None] = {}

    def resolve_owning_substation(component_id: str | None) -> str | None:
        if component_id is None:
            return None
        if component_id in owning_substation_cache:
            return owning_substation_cache[component_id]
        direct = substation_member_map.get(component_id)
        if direct:
            owning_substation_cache[component_id] = direct
            return direct
        current = parent_by_id.get(component_id)
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            current_type = component_type_by_id.get(current)
            if current_type == "Substation":
                owning_substation_cache[component_id] = current
                return current
            direct = substation_member_map.get(current)
            if direct:
                owning_substation_cache[component_id] = direct
                return direct
            current = parent_by_id.get(current)
        owning_substation_cache[component_id] = None
        return None

    raw_by_region_osm: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    raw_by_exact_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    raw_by_normalized_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in raw_substations:
        osm_id = str(row["osm_id"])
        for region_key in filter(None, {row.get("region"), row.get("region_code")}):
            raw_by_region_osm[(str(region_key), osm_id)].append(row)
        if row.get("name"):
            cleaned = clean_station_name(row["name"])
            raw_by_exact_name[cleaned].append(row)
            raw_by_normalized_name[normalized_station_name(cleaned)].append(row)

    def choose_raw_candidate(
        candidates: list[dict[str, Any]],
        resolved_voltage_kv: float | None,
    ) -> dict[str, Any] | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if resolved_voltage_kv is not None:
            filtered = []
            for row in candidates:
                raw_voltage = parse_float(row.get("max_voltage_kv")) or parse_float(row.get("voltage_kv"))
                if raw_voltage is not None and math.isclose(raw_voltage, resolved_voltage_kv):
                    filtered.append(row)
            if len(filtered) == 1:
                return filtered[0]
            if filtered:
                candidates = filtered
        shared_signature = {
            (row.get("osm_id"), row.get("lat"), row.get("lon"), row.get("max_voltage_kv"))
            for row in candidates
        }
        if len(shared_signature) == 1:
            return sorted(candidates, key=lambda row: (row.get("region_code"), row.get("id")))[0]
        return None

    substation_components = [
        row
        for row in components
        if component_type_by_id[row["Id"]] == "Substation"
    ]
    substation_components.sort(key=lambda row: row["Id"])

    curated_substations: list[dict[str, Any]] = []
    wave1_station_ids: set[str] = set()
    unresolved_wave1_substations: list[dict[str, Any]] = []
    outlier_substation_voltage_counts: collections.Counter[str] = collections.Counter()

    for component in substation_components:
        component_attrs = attrs_by_component.get(component["Id"], {})
        high_side_kv = parse_float(component_attrs.get("High Side Voltage"))
        nominal_kv = parse_float(component_attrs.get("Nominal Voltage"))

        raw_match = None
        name_source = "unresolved"
        cleaned_name = clean_station_name(component["Name"])
        normalized_name = normalized_station_name(component["Name"])

        unnamed_match = UNNAMED_SUBSTATION_RE.match(cleaned_name)
        if unnamed_match:
            region_code, osm_id = unnamed_match.groups()
            raw_match = choose_raw_candidate(raw_by_region_osm.get((region_code, osm_id), []), nominal_kv or high_side_kv)
            if raw_match:
                name_source = "component_fallback_osm"

        if raw_match is None:
            raw_match = choose_raw_candidate(raw_by_exact_name.get(cleaned_name, []), high_side_kv or nominal_kv)
            if raw_match:
                name_source = "raw_name_exact"

        if raw_match is None:
            raw_match = choose_raw_candidate(raw_by_normalized_name.get(normalized_name, []), high_side_kv or nominal_kv)
            if raw_match:
                name_source = "raw_name_normalized"

        raw_max_voltage_kv = parse_float(raw_match.get("max_voltage_kv")) if raw_match else None
        resolved_voltage_kv = high_side_kv or nominal_kv or raw_max_voltage_kv
        normalized_tier = normalize_tier(resolved_voltage_kv)
        if resolved_voltage_kv is not None and normalized_tier is None:
            outlier_substation_voltage_counts[f"{resolved_voltage_kv:g}"] += 1

        record = {
            "substation_id": component["Id"],
            "display_name": component["Name"],
            "raw_substation_id": raw_match.get("id") if raw_match else None,
            "raw_osm_id": raw_match.get("osm_id") if raw_match else None,
            "region": raw_match.get("region_code") if raw_match else None,
            "lat": raw_match.get("lat") if raw_match else None,
            "lon": raw_match.get("lon") if raw_match else None,
            "raw_max_voltage_kv": raw_max_voltage_kv,
            "resolved_voltage_kv": resolved_voltage_kv,
            "normalized_tier": normalized_tier,
            "name_source": name_source,
        }

        if normalized_tier in {"EHV_500", "EHV_220_230"} and raw_match and raw_match.get("lat") is not None and raw_match.get("lon") is not None:
            curated_substations.append(record)
            wave1_station_ids.add(component["Id"])
        elif normalized_tier in {"EHV_500", "EHV_220_230"}:
            unresolved_wave1_substations.append(record)

    curated_substations.sort(key=lambda row: (row["normalized_tier"], row["display_name"], row["substation_id"]))
    curated_substation_by_id = {row["substation_id"]: row for row in curated_substations}

    wave1_lines: list[dict[str, Any]] = []
    excluded_lines: list[dict[str, Any]] = []
    outlier_line_voltage_counts: collections.Counter[str] = collections.Counter()

    line_components = [
        row
        for row in components
        if component_type_by_id[row["Id"]] == "Line"
    ]
    line_components.sort(key=lambda row: row["Id"])

    for component in line_components:
        component_attrs = attrs_by_component.get(component["Id"], {})
        nominal_voltage_kv = parse_float(component_attrs.get("Nominal Voltage"))
        if nominal_voltage_kv is None:
            continue
        if nominal_voltage_kv not in WAVE1_VOLTAGES:
            outlier_line_voltage_counts[f"{nominal_voltage_kv:g}"] += 1
            continue

        normalized_tier = normalize_tier(nominal_voltage_kv)
        rows = sorted(line_connections.get(component["Id"], []), key=lambda row: row["Id"])
        endpoint_ids = sorted({cid for row in rows for cid in (row["FromComponentId"], row["ToComponentId"])})
        cp_ids = sorted(cid for cid in endpoint_ids if component_type_by_id.get(cid) == "Connection Point")
        vep_ids = sorted(cid for cid in endpoint_ids if component_type_by_id.get(cid) == "VirtualEndpoint")
        cp_to_substation = {cp_id: resolve_owning_substation(cp_id) for cp_id in cp_ids}
        substation_ids = sorted({sub_id for sub_id in cp_to_substation.values() if sub_id})
        reasons: list[str] = []

        if not cp_ids:
            reasons.append("no_station_boundary_cp")
        elif len(cp_ids) == 1:
            reasons.append("single_station_endpoint")
        elif len(cp_ids) > 2:
            reasons.append("more_than_two_station_cps")

        if vep_ids:
            reasons.append("virtual_endpoint_present")

        if any(sub_id is None for sub_id in cp_to_substation.values()):
            reasons.append("unmapped_connection_point_substation")

        if len(substation_ids) == 1 and cp_ids:
            reasons.append("same_substation_both_ends")
        elif len(substation_ids) > 2:
            reasons.append("more_than_two_station_roots")
        elif len(substation_ids) == 0 and cp_ids:
            reasons.append("no_substation_roots")

        non_wave1_station_ids = sorted(sub_id for sub_id in substation_ids if sub_id not in wave1_station_ids)
        if non_wave1_station_ids:
            reasons.append("non_wave1_station_tier")

        line_length_m = round(sum(geometry_length_m(row.get("Geometry")) for row in rows), 3)
        wire_count = line_wire_counts[component["Id"]]

        record = {
            "line_id": component["Id"],
            "line_name": component["Name"],
            "nominal_voltage_kv": nominal_voltage_kv,
            "normalized_tier": normalized_tier,
            "corridor_role": component_attrs.get("Corridor Role"),
            "wire_count": wire_count,
            "line_length_m": line_length_m if rows else None,
            "connection_point_ids": cp_ids,
            "substation_ids": substation_ids,
            "virtual_endpoint_ids": vep_ids,
            "endpoint_resolution_confidence": "CANONICAL_CP_EXACT" if not reasons and len(substation_ids) == 2 else "ANOMALOUS",
            "supporting_line_attrs": {
                "From Substation Id": component_attrs.get("From Substation Id"),
                "To Substation Id": component_attrs.get("To Substation Id"),
                "Endpoint Confidence": component_attrs.get("Endpoint Confidence"),
            },
        }

        if not reasons and len(substation_ids) == 2:
            endpoints = [curated_substation_by_id[sub_id] for sub_id in substation_ids]
            endpoints.sort(key=lambda row: (row["display_name"], row["substation_id"]))
            record.update(
                {
                    "from_substation_id": endpoints[0]["substation_id"],
                    "to_substation_id": endpoints[1]["substation_id"],
                }
            )
            wave1_lines.append(record)
        else:
            record["reasons"] = sorted(set(reasons))
            excluded_lines.append(record)

    wave1_lines.sort(key=lambda row: (row["normalized_tier"], row["line_name"], row["line_id"]))
    excluded_lines.sort(key=lambda row: row["line_id"])

    transformers: list[dict[str, Any]] = []
    transformer_pair_counts: collections.Counter[str] = collections.Counter()
    transformer_components = [
        row
        for row in components
        if component_type_by_id[row["Id"]] == "Transformer 2-Winding"
    ]
    transformer_components.sort(key=lambda row: row["Id"])

    for component in transformer_components:
        component_attrs = attrs_by_component.get(component["Id"], {})
        high_side_kv = parse_float(component_attrs.get("High Side Voltage"))
        low_side_kv = parse_float(component_attrs.get("Low Side Voltage"))
        if high_side_kv is None or low_side_kv is None:
            continue
        station_id = resolve_owning_substation(component["Id"])
        normalized_high_tier = normalize_tier(high_side_kv)
        normalized_low_tier = normalize_tier(low_side_kv)
        transformer_pair_counts[f"{high_side_kv:g}->{low_side_kv:g}"] += 1
        transformers.append(
            {
                "transformer_id": component["Id"],
                "station_id": station_id,
                "display_name": component["Name"],
                "high_side_kv": high_side_kv,
                "low_side_kv": low_side_kv,
                "normalized_high_tier": normalized_high_tier,
                "normalized_low_tier": normalized_low_tier,
                "envelope_source": component_attrs.get("Transformer Envelope Source"),
                "library_match_confidence": component_attrs.get("Library Match Confidence"),
                "wave1_relevant": normalized_high_tier in {"EHV_500", "EHV_220_230"},
            }
        )

    transformers.sort(key=lambda row: (row["high_side_kv"], row["low_side_kv"], row["transformer_id"]))

    graph_edges: list[dict[str, Any]] = []
    for line in wave1_lines:
        graph_edges.append(
            {
                "edge_kind": "line",
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "from_substation_id": line["from_substation_id"],
                "to_substation_id": line["to_substation_id"],
                "nominal_voltage_kv": line["nominal_voltage_kv"],
                "normalized_tier": line["normalized_tier"],
            }
        )

    for transformer in transformers:
        if not transformer["wave1_relevant"]:
            continue
        if transformer["normalized_high_tier"] == "EHV_500" and transformer["normalized_low_tier"] == "EHV_220_230":
            graph_edges.append(
                {
                    "edge_kind": "transformer_stepdown",
                    "transformer_id": transformer["transformer_id"],
                    "station_id": transformer["station_id"],
                    "from_tier": transformer["normalized_high_tier"],
                    "to_tier": transformer["normalized_low_tier"],
                    "high_side_kv": transformer["high_side_kv"],
                    "low_side_kv": transformer["low_side_kv"],
                }
            )

    graph_edges.sort(
        key=lambda row: (
            row["edge_kind"],
            row.get("line_id", row.get("transformer_id")),
        )
    )

    station_adjacency: dict[str, set[str]] = {row["substation_id"]: set() for row in curated_substations}
    component_line_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    for line in wave1_lines:
        lhs = line["from_substation_id"]
        rhs = line["to_substation_id"]
        station_adjacency[lhs].add(rhs)
        station_adjacency[rhs].add(lhs)
        component_line_counts[tuple(sorted((lhs, rhs)))] += 1

    connected_components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for station_id in sorted(station_adjacency):
        if station_id in seen:
            continue
        queue = collections.deque([station_id])
        seen.add(station_id)
        nodes: list[str] = []
        while queue:
            current = queue.popleft()
            nodes.append(current)
            for neighbor in sorted(station_adjacency[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        node_set = set(nodes)
        line_count = sum(count for pair, count in component_line_counts.items() if pair[0] in node_set and pair[1] in node_set)
        root_nodes = sorted(
            station_id
            for station_id in nodes
            if curated_substation_by_id[station_id]["normalized_tier"] == "EHV_500"
        )
        distance_from_nearest_500: dict[str, int | None] = {station_id: None for station_id in nodes}
        if root_nodes:
            bfs = collections.deque(root_nodes)
            for root in root_nodes:
                distance_from_nearest_500[root] = 0
            while bfs:
                current = bfs.popleft()
                current_distance = distance_from_nearest_500[current]
                assert current_distance is not None
                for neighbor in sorted(station_adjacency[current]):
                    if distance_from_nearest_500[neighbor] is None:
                        distance_from_nearest_500[neighbor] = current_distance + 1
                        bfs.append(neighbor)
        connected_components.append(
            {
                "component_id": f"component_{len(connected_components) + 1}",
                "station_ids": sorted(nodes),
                "station_count": len(nodes),
                "line_count": line_count,
                "root_station_ids": root_nodes,
                "classification": "ehv_island_without_500_root" if not root_nodes else "ehv_component",
                "distance_from_nearest_500": distance_from_nearest_500,
            }
        )

    connected_components.sort(key=lambda row: row["component_id"])

    wave1_dir = repo_root / "wave1"
    full_raw_dir = repo_root / "full_raw"
    wave1_dir.mkdir(parents=True, exist_ok=True)
    full_raw_dir.mkdir(parents=True, exist_ok=True)

    anomalies = {
        "excluded_lines": excluded_lines,
        "unmapped_wave1_substations": unresolved_wave1_substations,
    }
    summary = {
        "source_root": str(source_root),
        "source_data_mtime_utc": build_source_mtime(source_paths),
        "wave1_voltage_tiers": ["EHV_500", "EHV_220_230"],
        "station_counts_by_tier": collections.Counter(row["normalized_tier"] for row in curated_substations),
        "line_counts_by_tier": collections.Counter(row["normalized_tier"] for row in wave1_lines),
        "transformer_counts_by_pair": dict(sorted(transformer_pair_counts.items())),
        "connected_component_count": len(connected_components),
        "connected_components": connected_components,
        "clean_station_to_station_ehv_edge_count": len(wave1_lines),
        "excluded_line_counts_by_reason": dict(
            sorted(collections.Counter(reason for row in excluded_lines for reason in row["reasons"]).items())
        ),
        "outlier_voltages_excluded_from_wave1": {
            "substations": dict(sorted(outlier_substation_voltage_counts.items())),
            "lines": dict(sorted(outlier_line_voltage_counts.items())),
        },
        "wave1_relevant_transformer_count": sum(1 for row in transformers if row["wave1_relevant"]),
    }

    write_json(wave1_dir / "substations.json", curated_substations)
    write_json(wave1_dir / "lines.json", wave1_lines)
    write_json(wave1_dir / "transformers.json", transformers)
    write_json(wave1_dir / "graph_edges.json", graph_edges)
    write_json(wave1_dir / "summary.json", summary)
    write_json(wave1_dir / "anomalies.json", anomalies)

    raw_nodes = load_json(source_root / SOURCE_FILES["raw_nodes"])
    raw_edges = load_json(source_root / SOURCE_FILES["raw_edges"])
    write_jsonl_gz(full_raw_dir / "raw_nodes.jsonl.gz", raw_nodes)
    write_jsonl_gz(full_raw_dir / "raw_edges.jsonl.gz", raw_edges)
    write_json(full_raw_dir / "raw_substations.json", raw_substations)
    write_jsonl_gz(full_raw_dir / "seed_components.jsonl.gz", components)
    write_jsonl_gz(full_raw_dir / "seed_attrs.jsonl.gz", attrs)
    write_jsonl_gz(full_raw_dir / "seed_connections.jsonl.gz", connections)
    write_jsonl_gz(full_raw_dir / "seed_membership.jsonl.gz", membership)

    manifest_files = [
        wave1_dir / "substations.json",
        wave1_dir / "lines.json",
        wave1_dir / "transformers.json",
        wave1_dir / "graph_edges.json",
        wave1_dir / "summary.json",
        wave1_dir / "anomalies.json",
        full_raw_dir / "raw_nodes.jsonl.gz",
        full_raw_dir / "raw_edges.jsonl.gz",
        full_raw_dir / "raw_substations.json",
        full_raw_dir / "seed_components.jsonl.gz",
        full_raw_dir / "seed_attrs.jsonl.gz",
        full_raw_dir / "seed_connections.jsonl.gz",
        full_raw_dir / "seed_membership.jsonl.gz",
    ]

    row_counts = {
        "wave1/substations.json": len(curated_substations),
        "wave1/lines.json": len(wave1_lines),
        "wave1/transformers.json": len(transformers),
        "wave1/graph_edges.json": len(graph_edges),
        "wave1/summary.json": 1,
        "wave1/anomalies.json": 1,
        "full_raw/raw_nodes.jsonl.gz": len(raw_nodes),
        "full_raw/raw_edges.jsonl.gz": len(raw_edges),
        "full_raw/raw_substations.json": len(raw_substations),
        "full_raw/seed_components.jsonl.gz": len(components),
        "full_raw/seed_attrs.jsonl.gz": len(attrs),
        "full_raw/seed_connections.jsonl.gz": len(connections),
        "full_raw/seed_membership.jsonl.gz": len(membership),
    }

    manifest = {
        "source_root": str(source_root),
        "source_data_mtime_utc": build_source_mtime(source_paths),
        "generation_command": "python3 scripts/build_wave1_exports.py",
        "notes": [
            "full_raw/*.gz is intended for Git LFS",
            "Connection Point is internal to endpoint resolution and is not exposed as a Wave 1 graph node",
        ],
        "files": [],
    }

    for path in sorted(manifest_files):
        relative = path.relative_to(repo_root).as_posix()
        manifest["files"].append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "row_count": row_counts[relative],
                "sha256": sha256_file(path),
                "lfs_expected": relative.startswith("full_raw/") and relative.endswith(".gz"),
            }
        )

    write_json(full_raw_dir / "manifest.json", manifest)

    # Validation
    for station in curated_substations:
        assert station["lat"] is not None and station["lon"] is not None, station["substation_id"]
        assert station["normalized_tier"] in {"EHV_500", "EHV_220_230"}

    for line in wave1_lines:
        assert line["normalized_tier"] in {"EHV_500", "EHV_220_230"}
        assert len({line["from_substation_id"], line["to_substation_id"]}) == 2
        assert not line["virtual_endpoint_ids"]
        assert len(line["connection_point_ids"]) == 2
        assert line["from_substation_id"] in curated_substation_by_id
        assert line["to_substation_id"] in curated_substation_by_id

    for transformer in transformers:
        assert transformer["high_side_kv"] is not None
        assert transformer["low_side_kv"] is not None

    for transformer in graph_edges:
        if transformer["edge_kind"] == "transformer_stepdown":
            assert transformer["from_tier"] == "EHV_500"
            assert transformer["to_tier"] == "EHV_220_230"

    for path in [
        full_raw_dir / "raw_nodes.jsonl.gz",
        full_raw_dir / "raw_edges.jsonl.gz",
        full_raw_dir / "seed_components.jsonl.gz",
        full_raw_dir / "seed_attrs.jsonl.gz",
        full_raw_dir / "seed_connections.jsonl.gz",
        full_raw_dir / "seed_membership.jsonl.gz",
    ]:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            first_line = handle.readline()
            assert first_line, f"gzip export is empty: {path}"

    print(
        json.dumps(
            {
                "wave1_substations": len(curated_substations),
                "wave1_lines": len(wave1_lines),
                "wave1_relevant_transformers": sum(1 for row in transformers if row["wave1_relevant"]),
                "excluded_lines": len(excluded_lines),
                "unmapped_wave1_substations": len(unresolved_wave1_substations),
                "repo_root": str(repo_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
