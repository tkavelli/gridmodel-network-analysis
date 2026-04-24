# HV 14i Substation Naming Prompt

You are working on GridModel substation naming truth.

Input file:

- `naming/hv_14i_substation_naming_pack.json`

Task:

For every item in `items`, produce a verified human-readable substation name.
The scope is every unique endpoint substation referenced by the current
high-voltage station-to-station candidate artifact `14i_hv_station_lines.json`.

Rules:

1. Do not invent names from nearby cities/neighborhoods without evidence.
2. Use coordinates, OSM id, voltage, operator, and connected line context as
   search keys.
3. Prefer official or authoritative sources: utility planning docs, CAISO/ISO
   materials, FERC/EIA/CEC/CPUC filings, interconnection studies, city/county
   permit PDFs, utility project pages.
4. OSM can be supporting evidence, not final truth unless it exactly matches
   other evidence.
5. Preserve distinctions between Substation, Switchyard, Switching Station,
   Receiving Station, Distributing Station, and Generating Station Switchyard.
6. If two nearby OSM polygons are probably the same real station/site, do not
   silently merge them. Mark `duplicate_or_split_candidate`.
7. If evidence is weak, set `confidence` to `low` or `proposed_name` to `null`.
8. Output only valid JSON, no Markdown, no code fences.

Output file:

- `naming/hv_14i_substation_names.json`

Output schema:

```json
{
  "version": "hv_14i_names_v1",
  "scope": "substations appearing in 14i_hv_station_lines.json",
  "items": [
    {
      "component_id": "uuid",
      "current_name": "string or null",
      "proposed_name": "string or null",
      "facility_kind": "Substation | Switchyard | Switching Station | Receiving Station | Distributing Station | Generating Station Switchyard | Unknown",
      "operator": "string or null",
      "voltage_kv": 220,
      "osm_id": "string or null",
      "region": "LA | OrangeCounty | other",
      "lat": 0.0,
      "lon": 0.0,
      "confidence": "high | medium | low | none",
      "needs_manual_review": true,
      "duplicate_or_split_candidate": false,
      "same_site_candidate_ids": ["uuid"],
      "alternate_names": ["string"],
      "rejected_names": [
        {
          "name": "string",
          "reason": "string"
        }
      ],
      "sources": [
        {
          "url": "https://...",
          "source_type": "utility | iso | regulatory | planning | osm | map_label | other",
          "claim": "short claim supported by the source"
        }
      ],
      "evidence_summary": "short explanation why this name is or is not supported",
      "notes": "string"
    }
  ]
}
```

Important:

- Return all unique `component_id` values from the input pack in one JSON
  object.
- Do not omit unnamed substations. Include them with `proposed_name: null` if no
  reliable name is found.
- Use plain URL strings only. Do not use Markdown links inside JSON.
