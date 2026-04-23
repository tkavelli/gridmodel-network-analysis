# Wave 1 EHV Graph

Curated station-to-station EHV topology for:

- `500 kV`
- unified `220/230 kV`

## Files

- `substations.json`
  - Wave 1 substations with resolved coordinates and voltage tier
- `lines.json`
  - clean station-to-station EHV corridors only
- `transformers.json`
  - transformer hierarchy context
- `graph_edges.json`
  - two edge kinds only: `line`, `transformer_stepdown`
- `summary.json`
  - counts, connected components, and anomaly totals
- `anomalies.json`
  - excluded lines and unmapped/outlier records

## Rules

- `Connection Point` is used only internally for endpoint resolution.
- Curated line edges must resolve to exactly two distinct substation roots.
- `VirtualEndpoint`-ended or ambiguous lines stay out of the main graph.
- This export is topology and hierarchy only. It does not claim operational power-flow direction.
