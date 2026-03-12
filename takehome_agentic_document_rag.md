# Take-Home Assignment: Multi-Document Conflict Resolution System

## The Problem

You are given **5 research papers** about NVX-0228, a fictional BRD4 inhibitor. These papers were published by different groups at different times, and they **disagree** on key findings — IC50 values, toxicity rates, mechanism of action, and more.

Build a system that can answer questions about NVX-0228 by coordinating across all 5 documents. When papers disagree, the system should surface the conflicts and reason about them — not silently pick a winner.

How you architect this is up to you. A multi-agent system with distinct roles (retrieval, conflict analysis, synthesis) is one strong approach. A well-designed pipeline with clear separation of concerns is another. We care about **why you chose your architecture** and how it handles the core challenge: managing context from multiple conflicting sources.

**Time: ~4 hours**

---

## Input Data

Five pre-parsed paper JSONs are in `data/`. Each follows this schema:

```json
{
  "metadata": {
    "filename": "paper.pdf",
    "title": "Full paper title",
    "authors": ["Author A", "Author B"],
    "publication_date": "YYYY-MM-DD",
    "journal": "Journal Name",
    "sample_size": 48,
    "page_count": 12
  },
  "chunks": [
    {
      "id": "chunk-uuid",
      "type": "text | table",
      "content": "Clean text content...",
      "section": "Results",
      "page": 3,
      "grounding": {
        "box": { "left": 0.06, "top": 0.12, "right": 0.94, "bottom": 0.35 },
        "page": 3
      }
    }
  ]
}
```

The chunks are pre-cleaned — no HTML, no noise to filter. Each paper has metadata (publication date, sample size, journal) that may help when reasoning about conflicting claims.

---

## What We're Looking For

### System Design

Some questions to consider as you design your system:

- How do you manage context? (The papers total ~40 chunks — too much to pass everything into a single LLM call.)
- How do you ensure evidence is pulled from **multiple papers**, not just the most similar one?
- When the system discovers a conflict, how does it respond? (Ignore it? Fetch more context? Flag it?)
- How is the work decomposed? What are the boundaries between components?

If you use a multi-agent approach, show how agents communicate and when one agent's output changes another's behavior. If you use a pipeline, explain why that was the right call. Use any framework or build from scratch — if you use a framework, explain what value it adds.

### Output

For each query, the system should produce:


- Evidence from **multiple papers**
- **Conflicts detected** between papers, with reasoning about the type of disagreement
- A **synthesis** that cites sources and acknowledges disagreements
- A **trace or log** showing how your system arrived at the answer (agent messages, pipeline steps, or similar)

### Test Queries

Run your system on these 5 queries and include the output for each:

```
1. "What is the IC50 of NVX-0228?"
2. "What toxicity was observed with NVX-0228?"
3. "What is the mechanism of action of NVX-0228?"
4. "What clinical trials have been conducted with NVX-0228?"
5. "What resistance mechanisms have been identified?"
```

---

## Evaluation Criteria

- **Architecture & context management**: Clear separation of concerns, sensible decisions about what context goes where, well-defined interfaces between components
- **Conflict handling**: The system surfaces real disagreements between papers and reasons about them
- **System behavior**: Show at least one case where discovering a conflict changes what the system does next (e.g., fetches more context, re-ranks results, flags for review)
- **Code quality & write-up**: Clean code, README explaining your architecture decisions and trade-offs

---

## Constraints

- **Language**: Python 3.10+
- **LLM / Embeddings / Vector store**: Your choice. Document what you used and why.
- **Submission**: GitHub repo or zip with README, runnable code, and example outputs.

---

## Bonus

A `generation_template.json` is included in `data/`. It defines an IND Module 2.6.2 pharmacology summary structure. Extend your agent system to fill each template section with synthesized, conflict-aware content from the papers.
