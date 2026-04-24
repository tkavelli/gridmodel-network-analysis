# GridModel Naming Research Pack

This directory is for assisted research of human-readable substation and line names.
It is not canonical truth by itself.

The intended workflow is:

1. Give the compressed JSONL packs to a research-capable assistant.
2. Ask it to search public sources for substation names, operators, and evidence.
3. Return candidate names in the output schema below.
4. Review the candidates before importing them back into `gridmodel-datasets`.

## Files

- `substation_naming_pack.jsonl.gz`
  - one row per seed `Substation` component
  - includes current synthetic/source name, raw OSM evidence, coordinates, voltage, connected lines, neighbors, and search hints
- `line_context_pack.jsonl.gz`
  - one row per seed `Line` component
  - includes endpoint station IDs/names, voltage, corridor role, wire/member counts, line length, and bbox
- `manifest.json`
  - deterministic counts, hashes, source root, and truth policy
- `schema_candidate_names.json`
  - expected response contract for researched candidate names

## Research Rules

- Do not invent names from coordinates alone.
- Do not treat `Unnamed LA Substation 123...` as a valid human name.
- Prefer primary or operational sources:
  - utility/ISO transmission maps
  - public interconnection documents
  - planning/permit filings
  - OpenStreetMap tags and history when they carry real names
- Map labels and satellite interpretation are supporting evidence only unless corroborated.
- Keep a proposed name separate from the current name until review.
- Include source URLs and confidence for every proposed name.

## Candidate Output Contract

Return JSONL rows matching `schema_candidate_names.json`.

Required fields:

- `substation_id`
- `current_name`
- `proposed_name`
- `confidence`
- `sources`
- `evidence_summary`
- `needs_manual_review`

Recommended fields:

- `operator`
- `voltage_kv`
- `alternate_names`
- `rejected_names`
- `notes`

## Priority

Research order should be:

1. `recommended_review_priority=high`
2. substations with voltage `>=220 kV`
3. named lines whose endpoints are synthetic
4. dense local areas where multiple synthetic substations are connected
