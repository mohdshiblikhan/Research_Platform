from typing import Any, Optional


RESEARCH_PLANNING_SYSTEM_PROMPT = """You are a principal research scientist and AI research strategist.
Your task is to convert a user research question into a rigorous, evidence-driven, structured research plan by analyzing the provided academic literature.

You will be provided with:
1. Structured extractions from research papers in the project.
2. A comparative analysis and synthesis highlighting differences, common themes, and literature gaps.
3. Question-specific evidence passages retrieved directly from the papers, with exact source provenance.

CORE PRINCIPLES & CONSTRAINTS:
1. BOUNDED CONTEXT & VERIFIABLE CLAIMS:
   - Base all claims strictly on the provided extractions and evidence passages.
   - Do NOT mistake an unobserved topic for a proven universal research gap. If a concept is simply not mentioned in the provided papers, acknowledge that it is unobserved in this specific corpus rather than asserting it is globally missing in all science.
   - Ground each identified gap in verifiable observations from the analyzed documents.

2. TRACEABLE CHAIN OF INQUIRY:
   - Gaps (G1, G2, ...) -> Hypotheses (H1, H2, ...) -> Experiments (E1, E2, ...).
   - Every hypothesis MUST explicitly reference at least one valid Gap ID in `addresses_gaps`.
   - Every experiment MUST explicitly reference exactly one valid Hypothesis ID in `hypothesis`.
   - The sequence of experiments MUST specify the logical dependency order for execution.

3. CONCRETE EXPERIMENTAL DESIGN:
   - Experiments must propose clear methods, suitable datasets/benchmarks, and measurable evaluation metrics (e.g., Recall@K, Faithfulness, F1, latency).

Respond ONLY with a valid JSON object matching the following structure:
{
  "reasoning": "Detailed chain-of-thought analysis linking literature findings to gaps, hypotheses, and experimental steps.",
  "literature_summary": "Comprehensive summary of what the analyzed papers establish regarding the research question.",
  "gaps": [
    {
      "id": "G1",
      "description": "Clear description of the gap or limitation demonstrated in the literature.",
      "evidence": ["Verifiable observation citing document findings or retrieved evidence."],
      "source_documents": [1, 2]
    }
  ],
  "hypotheses": [
    {
      "id": "H1",
      "statement": "Testable, falsifiable hypothesis statement.",
      "addresses_gaps": ["G1"],
      "rationale": "Why this hypothesis is plausible and worth investigating based on literature evidence."
    }
  ],
  "experiments": [
    {
      "id": "E1",
      "title": "Concise experiment title.",
      "hypothesis": "H1",
      "method": "Experimental procedure, baseline comparisons, and setup.",
      "datasets": "Benchmark or dataset names to evaluate on.",
      "metrics": ["Metric1", "Metric2"],
      "priority": "high | medium | low"
    }
  ],
  "recommended_sequence": ["E1", "E2"],
  "confidence": "high | medium | low",
  "limitations": "Explicit caveats regarding the plan's scope, including the bounded nature of the analyzed document corpus."
}

Do NOT output markdown fences, code blocks, or preamble. Return ONLY the JSON object."""


def format_evidence_passage(
    index: int,
    doc_id: int,
    filename: str,
    page_start: int,
    page_end: int,
    chunk_id: int,
    content: str,
) -> str:
    """Format a single retrieved chunk with full source provenance."""
    if page_start == page_end:
        pages = f"p. {page_start}"
    else:
        pages = f"pp. {page_start}-{page_end}"
    return (
        f"[Evidence {index}] (Document ID: {doc_id}, File: \"{filename}\", {pages}, Chunk: {chunk_id}):\n"
        f"{content.strip()}"
    )


def format_extraction_for_planning(
    doc_id: int,
    filename: str,
    extraction: Any,
) -> str:
    """Format structured extraction fields for a single document."""
    lines = [f'=== Document {doc_id}: "{filename}" ===']
    fields = [
        ("Research Problem", getattr(extraction, "research_problem", None)),
        ("Methodology", getattr(extraction, "methodology", None)),
        ("Models Used", getattr(extraction, "models_used", None)),
        ("Datasets", getattr(extraction, "datasets", None)),
        ("Evaluation Metrics", getattr(extraction, "evaluation_metrics", None)),
        ("Results", getattr(extraction, "results", None)),
        ("Limitations", getattr(extraction, "limitations", None)),
        ("Baselines", getattr(extraction, "baselines", None)),
    ]
    for label, val in fields:
        lines.append(f"{label}: {val or 'Not specified'}")
    return "\n".join(lines)


def build_research_planning_prompt(
    research_question: str,
    extractions_context: str,
    comparison_context: str,
    evidence_context: str,
) -> str:
    """Assemble the complete research planning user prompt."""
    sections = [
        f"USER RESEARCH QUESTION:\n{research_question}\n",
        "=== ANALYZED LITERATURE (STRUCTURED EXTRACTIONS) ===",
        extractions_context.strip(),
        "\n=== CROSS-DOCUMENT COMPARATIVE SYNTHESIS ===",
        comparison_context.strip(),
    ]

    if evidence_context and evidence_context.strip():
        sections.extend([
            "\n=== QUESTION-SPECIFIC RETRIEVED EVIDENCE PASSAGES ===",
            evidence_context.strip(),
        ])
    else:
        sections.append("\n=== QUESTION-SPECIFIC RETRIEVED EVIDENCE PASSAGES ===\n(No specific passages retrieved)")

    sections.append(
        "\nBased on the literature extractions, comparative analysis, and specific evidence passages above, "
        "produce a complete structured research plan addressing the user's research question according to all guidelines."
    )

    return "\n\n".join(sections)
