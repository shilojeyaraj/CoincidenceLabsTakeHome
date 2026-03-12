# Example Outputs

Pre-run results for all 5 assignment test queries plus one bonus arbitrary question.
Each file is a `QueryResult` JSON saved automatically by the system after every query.

---

## The 5 Required Test Queries

| File | Query | Conflicts | Expansion |
|------|-------|-----------|-----------|
| [`20260312_145936_What_is_the_IC50_of_NVX-0228_.json`](20260312_145936_What_is_the_IC50_of_NVX-0228_.json) | What is the IC50 of NVX-0228? | 1 (ASSAY_VARIABILITY) | No |
| [`20260312_150039_What_toxicity_was_observed_with_NVX-0228.json`](20260312_150039_What_toxicity_was_observed_with_NVX-0228.json) | What toxicity was observed with NVX-0228? | 5 (METHODOLOGY × 4, ASSAY_VARIABILITY × 1) | No |
| [`20260312_150137_What_is_the_mechanism_of_action_of_NVX-0.json`](20260312_150137_What_is_the_mechanism_of_action_of_NVX-0.json) | What is the mechanism of action of NVX-0228? | 3 (CONCEPTUAL, ASSAY_VARIABILITY, METHODOLOGY) | **Yes** |
| [`20260312_150241_What_clinical_trials_have_been_conducted.json`](20260312_150241_What_clinical_trials_have_been_conducted.json) | What clinical trials have been conducted with NVX-0228? | 5 (CONCEPTUAL, METHODOLOGY × 3, NON_CONFLICT) | **Yes** |
| [`20260312_150340_What_resistance_mechanisms_have_been_ide.json`](20260312_150340_What_resistance_mechanisms_have_been_ide.json) | What resistance mechanisms have been identified? | 2 (CONCEPTUAL, ASSAY_VARIABILITY) | **Yes** |

## Bonus: Arbitrary Question (not in the test set)

| File | Query | Conflicts | Expansion |
|------|-------|-----------|-----------|
| [`20260312_151144_What_is_the_oral_bioavailability_and_hal.json`](20260312_151144_What_is_the_oral_bioavailability_and_hal.json) | What is the oral bioavailability and half-life of NVX-0228? | 4 (METHODOLOGY × 3, ASSAY_VARIABILITY) | No |

This file demonstrates that the system handles arbitrary questions outside the 5 test queries — vector search retrieves the relevant chunks from all 5 papers regardless of what you ask.

---

## Output Schema

Every file follows the `QueryResult` schema:

```json
{
  "query": "The original question",
  "answer": "SUMMARY\n\n...\n\nKEY FINDINGS\n\n1. ...\n\nCONFLICT ANALYSIS\n\n...\n\nCONCLUSIONS\n\n...\n\nREFERENCES\n\n...",
  "conflicts": [
    {
      "property": "ic50_bd1_nm",
      "conflict_type": "ASSAY_VARIABILITY",
      "papers_involved": ["paper1_nvx0228_novel_inhibitor", "paper2_nvx0228_pharmacokinetics", ...],
      "claims": [...],
      "reasoning": "IC50 values range from 8.5–15.3 nM across studies. Paper 1 used AlphaScreen...",
      "resolution": "Assay standardization recommended"
    }
  ],
  "papers_cited": ["paper1_nvx0228_novel_inhibitor", ...],
  "context_expansion_triggered": true,
  "trace": [
    {"agent": "PaperAgent", "step": "paper_agent_paper1_nvx0228_novel_inhibitor", "latency_ms": 11397, "tokens_used": 247, ...},
    {"agent": "ConflictAgent", "step": "conflict_agent", ...},
    {"agent": "ConflictAgent.ContextExpansion", "step": "context_expansion_paper1_nvx0228_novel_inhibitor", ...},
    {"agent": "SynthesisAgent", "step": "synthesis_agent", ...}
  ],
  "ind_results": [],
  "timestamp": "2026-03-12T15:01:37"
}
```

### What to look at in each file

- **`answer`** — The final synthesised response. Plain text with ALL CAPS section headers (SUMMARY, KEY FINDINGS, CONFLICT ANALYSIS, CONCLUSIONS, REFERENCES). Author-year citations inline e.g. `(Chen et al., 2023)`.
- **`conflicts`** — Every detected disagreement between papers, classified by type. `reasoning` explains *why* this is a conflict and how the papers differ.
- **`context_expansion_triggered`** — `true` on the mechanism, clinical trials, and resistance queries. This means the system detected a CONCEPTUAL conflict and automatically fetched additional chunks before synthesising.
- **`trace`** — Full agent execution log: which agent ran, what it produced, how long it took, how many tokens it used. Mechanism query trace has 12 steps (5 paper + conflict + 5 expansion fetches + synthesis) instead of the normal 7.
