# gridmodel-network-analysis

Station-to-station EHV analysis exports plus full raw graph dumps derived from the local `gridmodel-datasets` seed outputs.

## Layout

- `wave1/`
  - curated `500 kV` + unified `220/230 kV` station graph
  - plain JSON for direct inspection in GitHub
- `full_raw/`
  - compressed JSONL dumps for raw nodes, raw edges, seed components, attrs, connections, and membership
  - `full_raw/*.gz` tracked with Git LFS
- `scripts/build_wave1_exports.py`
  - generator and validator

## Source Data

By default the generator reads from the sibling repository:

- `/Users/nikolaybubnov/Downloads/gridmodel-dev/gridmodel-datasets/08_Data/08.01_Seed/scripts/output`

You can override that with either:

- `GRIDMODEL_DATASET_OUTPUT_ROOT=/abs/path/to/output`
- `GRIDMODEL_DATASETS_ROOT=/abs/path/to/gridmodel-datasets`

## Generate

```bash
python3 scripts/build_wave1_exports.py
```

The script:

1. builds the curated Wave 1 station graph
2. emits the full raw dumps
3. writes a deterministic manifest
4. validates the exported contracts before exiting

See [wave1/README.md](/Users/nikolaybubnov/Downloads/gridmodel-dev/gridmodel-network-analysis/wave1/README.md) for the curated graph contract.
