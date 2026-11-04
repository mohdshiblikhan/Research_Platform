import json
from typing import Any, Dict, List, Optional

EXPERIMENT_COMPARISON_SYSTEM_PROMPT = """You are an expert AI research scientist and empirical evaluation analyst.
You are provided with a pre-computed empirical comparison matrix comparing multiple experiments within a research project.

Your task is to interpret the deterministic numbers, configuration differences, Pareto non-domination findings, and hypothesis verdicts to produce an analytical synthesis.

CRITICAL INSTRUCTIONS:
1. Ground every statement strictly in the numbers and notes provided in the comparison context.
2. Do NOT invent or hallucinate metrics, models, or results that are not in the context.
3. Analyze genuine trade-offs (e.g. accuracy vs. latency or cost) based on the computed Pareto points.
4. Evaluate whether related experiments consistently support, refute, or qualify their motivating hypotheses based on the recorded consensus.
5. Provide concrete, actionable next steps for future experiments based on the observed trade-offs and gaps.

Return ONLY a valid JSON object matching this structure:
{
  "key_performance_tradeoffs": "Detailed explanation of quantitative performance trade-offs...",
  "pareto_insights": "Analysis of Pareto-optimal configurations and dominated runs...",
  "hypothesis_consistency": "Synthesis of empirical consistency across hypothesis verdicts...",
  "anomalies_or_contradictions": "Any surprising regressions or contradictions (or null if none)...",
  "recommended_next_steps": ["Actionable next experiment 1", "Actionable next experiment 2"],
  "executive_summary": "A 2-3 sentence overall synthesis of the empirical comparison."
}
"""


def build_experiment_comparison_prompt(
    experiments_data: List[Dict[str, Any]],
    varying_configurations: List[Dict[str, Any]],
    metrics_summary: List[Dict[str, Any]],
    pareto_data: Optional[Dict[str, Any]],
    hypothesis_consensus: List[Dict[str, Any]],
) -> str:
    """Build a comprehensive, structured user prompt context for LLM comparison synthesis."""
    context_obj = {
        "experiments": experiments_data,
        "varying_configurations": varying_configurations,
        "metrics_matrix": metrics_summary,
        "pareto_analysis": pareto_data,
        "hypothesis_consensus": hypothesis_consensus,
    }

    context_json = json.dumps(context_obj, indent=2)

    return (
        "Analyze the following pre-computed empirical comparison of AI experiments:\n\n"
        f"```json\n{context_json}\n```\n\n"
        "Synthesize the empirical findings, trade-offs, Pareto frontier, and hypothesis verdicts. "
        "Return strictly valid JSON adhering to the specified schema."
    )
