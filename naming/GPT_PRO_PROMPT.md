# GPT Pro Naming Research Prompt

Use this repository as a private GridModel naming research pack.

Your task is to research human-readable names for electrical substations.
Do not modify source truth directly. Produce candidate names only.

Input files:

- `naming/substation_naming_pack.jsonl.gz`
- `naming/line_context_pack.jsonl.gz`
- `naming/schema_candidate_names.json`

Work priority:

1. rows with `recommended_review_priority=high`
2. substations with `voltage.resolved_kv >= 220`
3. synthetic names like `Unnamed LA Substation 1462903363`
4. substations connected to named high-voltage lines

Research rules:

- Use web research and public sources.
- Prefer utility, ISO, regulatory, planning, permit, and official map sources.
- OpenStreetMap tags/history are acceptable evidence when they contain a real name.
- Map labels and satellite interpretation are weak evidence unless corroborated.
- Never invent a name from coordinates alone.
- Never treat `Unnamed ... Substation ...` as a human-readable name.
- If evidence is weak, set `confidence=low` and `needs_manual_review=true`.
- If no reliable name is found, set `proposed_name=null`, `confidence=none`, and explain why.

Return JSONL rows matching `naming/schema_candidate_names.json`.

For each row, include:

- `substation_id`
- `current_name`
- `proposed_name`
- `confidence`
- `sources`
- `evidence_summary`
- `needs_manual_review`
- optional `operator`, `voltage_kv`, `alternate_names`, `rejected_names`, `notes`

Do not collapse multiple substations into one row unless the source evidence proves they are the same physical facility. If two nearby voltage yards share a common site name, keep separate rows but mention the shared site relationship in `notes`.
