# Reference Materials

Provided by Coincidence Labs alongside the assignment. Not part of the runnable system.

| File | Description |
|------|-------------|
| [`agentic_extraction_example.json`](agentic_extraction_example.json) | Example output from Coincidence Labs' own document parsing pipeline (`dpt-2-20251103`). Shows raw extraction format: 138 chunks, types include `text`, `table`, `figure`, `logo`, `marginalia`, markdown with anchor IDs. This is what real paper ingestion looks like before pre-processing into the simplified `data/paper*.json` schema. |
| [`chemistry_2025_source_paper.pdf`](chemistry_2025_source_paper.pdf) | Source PDF for the above — Juan Li et al., *Results in Chemistry* 18 (2025) 102670. Real BET/BRD4 inhibitor clinical trials paper. Reference material only. |

## Why These Are Included

The extraction example shows how to extend this system to accept raw pipeline output. See the **"Extending to Real Documents"** section in the root `README.md` for the adaptation path.
