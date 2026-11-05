import json
from typing import Any, Dict, List, Optional


# =============================================================================
# Claim Extraction Prompt
# =============================================================================

CLAIM_EXTRACTION_SYSTEM_PROMPT = """You are an expert AI evaluation auditor specializing in factual claim decomposition.

Your task is to decompose a given generated response into a list of standalone, atomic, testable factual claims.
For each claim, you must extract any citation markers or chunk IDs referenced directly in that sentence/claim (e.g. "[1]", "[chunk_12]", "chunk_12", "[doc_1:3]").

CRITICAL INSTRUCTIONS:
1. Decompose compound statements into separate single atomic claims.
2. Each claim must be self-contained and independently verifiable.
3. If the answer contains NO factual claims (e.g., it is empty, an apology, a generic disclaimer like "I don't know", or conversational fluff), return an empty list: {"claims": []}.
4. Do NOT hallucinate claims or citations not present in the answer.

Return ONLY a valid JSON object matching this schema:
{
  "claims": [
    {
      "claim_text": "Exact or normalized standalone claim statement",
      "cited_chunk_references": ["1", "chunk_12"]
    }
  ]
}
"""

def build_claim_extraction_prompt(answer_text: str) -> str:
    """Build prompt to decompose an answer into atomic factual claims with cited chunk references."""
    return (
        "Extract all atomic factual claims and their cited references from the following response text:\n\n"
        f"--- RESPONSE START ---\n{answer_text.strip()}\n--- RESPONSE END ---\n\n"
        "Return strictly valid JSON adhering to the specified schema."
    )


# =============================================================================
# Claim Verification Prompt (Entailment)
# =============================================================================

CLAIM_VERIFICATION_SYSTEM_PROMPT = """You are an expert AI fact-checking and natural language inference judge.

Your task is to verify whether an atomic claim is supported by the provided retrieved context.

You must assign one of three verdicts:
- "SUPPORTED": The context directly and unambiguously states or mathematically entails the claim.
- "CONTRADICTED": The context directly contradicts or refutes the claim.
- "UNSUPPORTED": The context does not mention the necessary facts or cannot verify the claim (neutral/insufficient evidence).

CRITICAL INSTRUCTIONS:
1. Base your decision ONLY on the provided context passages. Do not use outside knowledge or extrapolate beyond the text.
2. Provide a concise explanation justifying the verdict.

Return ONLY a valid JSON object matching this schema:
{
  "verdict": "SUPPORTED" | "CONTRADICTED" | "UNSUPPORTED",
  "reasoning": "Brief explanation of how the context supports, contradicts, or fails to mention the claim."
}
"""

def build_claim_verification_prompt(claim_text: str, context_text: str) -> str:
    """Build prompt to verify an atomic claim against retrieved context."""
    return (
        f"Claim to verify:\n\"{claim_text}\"\n\n"
        f"Retrieved Context:\n---\n{context_text.strip()}\n---\n\n"
        "Evaluate the entailment relation. Return strictly valid JSON."
    )


# =============================================================================
# Answer Relevance Prompt
# =============================================================================

ANSWER_RELEVANCE_SYSTEM_PROMPT = """You are an expert AI evaluation auditor assessing question-answering relevance.

Your task is to evaluate how directly, concisely, and completely a generated answer addresses the user's research query.
Note: You are NOT evaluating whether the answer is factually true, but whether it directly answers the specific question asked without unnecessary evasion, irrelevance, or tangential tangents.

Scoring Rubric (0.0 to 1.0):
- 1.0: Directly and fully answers the question with zero extraneous or evasive content.
- 0.7 - 0.9: Mostly answers the question; minor digression or slight omission.
- 0.4 - 0.6: Partially answers the question or contains substantial irrelevant text.
- 0.1 - 0.3: Barely addresses the question or largely evades it.
- 0.0: Completely irrelevant or refuses to answer without justification.

Return ONLY a valid JSON object matching this schema:
{
  "score": 0.85,
  "reasoning": "Concise justification of the assigned relevance score."
}
"""

def build_answer_relevance_prompt(query: str, answer_text: str) -> str:
    """Build prompt to evaluate answer relevance to a query."""
    return (
        f"Query:\n\"{query}\"\n\n"
        f"Generated Answer:\n---\n{answer_text.strip()}\n---\n\n"
        "Evaluate the relevance of the answer to the query. Return strictly valid JSON."
    )


# =============================================================================
# Answer Correctness Prompt (Agent Final Answer vs Ground Truth)
# =============================================================================

ANSWER_CORRECTNESS_SYSTEM_PROMPT = """You are an expert AI research evaluation judge assessing semantic answer correctness.

Your task is to evaluate the semantic and factual alignment between an Agent's generated answer and a Reference Ground Truth answer.
This is a model-based estimate of factual correctness against a reference answer.

Scoring Rubric (0.0 to 1.0):
- 1.0: Factually completely aligned with the reference answer; covers all key points accurately.
- 0.7 - 0.9: Majority of key claims match the reference answer; minor omissions that do not compromise core findings.
- 0.4 - 0.6: Partial alignment; misses important conclusions or includes partially inaccurate assertions.
- 0.1 - 0.3: Major discrepancies, contradicted conclusions, or predominantly inaccurate claims.
- 0.0: Entirely incorrect or completely contradicts the reference answer.

Return ONLY a valid JSON object matching this schema:
{
  "score": 0.9,
  "reasoning": "Concise breakdown comparing the candidate answer to the reference answer."
}
"""

def build_answer_correctness_prompt(
    query: str, reference_answer: str, candidate_answer: str
) -> str:
    """Build prompt to evaluate candidate answer against reference answer."""
    return (
        f"Research Question:\n\"{query}\"\n\n"
        f"Reference Ground Truth Answer:\n---\n{reference_answer.strip()}\n---\n\n"
        f"Agent Candidate Answer:\n---\n{candidate_answer.strip()}\n---\n\n"
        "Evaluate the semantic correctness of the candidate answer relative to the reference. Return strictly valid JSON."
    )


# =============================================================================
# Synthetic Dataset Generation Prompts
# =============================================================================

SYNTHETIC_SINGLE_CHUNK_QA_SYSTEM_PROMPT = """You are an expert AI research dataset curator.

Your task is to generate a high-quality, realistic research query and its corresponding grounded answer based STRICTLY and SOLELY on the provided text chunk from a scientific paper.

CRITICAL INSTRUCTIONS:
1. The question must sound like an authentic question a researcher would ask (e.g., about methodology, architecture, datasets, metrics, findings).
2. The question must be directly answerable from the provided chunk.
3. The reference answer must be completely faithful to the chunk and contain all relevant details needed to answer the question.
4. Do NOT use outside knowledge or make claims unsupported by the chunk.

Return ONLY a valid JSON object matching this schema:
{
  "query": "Realistic research question",
  "reference_answer": "Complete, grounded answer",
  "reasoning": "Why this question tests understanding of the chunk"
}
"""

def build_synthetic_single_chunk_prompt(chunk_text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Build prompt to generate a single-chunk Q&A pair."""
    meta_str = f"Context Metadata: {json.dumps(metadata)}\n" if metadata else ""
    return (
        f"{meta_str}"
        f"Source Text Chunk:\n---\n{chunk_text.strip()}\n---\n\n"
        "Generate a grounded question and reference answer. Return strictly valid JSON."
    )


SYNTHETIC_MULTI_CHUNK_QA_SYSTEM_PROMPT = """You are an expert AI research dataset curator.

Your task is to generate a multi-hop, multi-chunk research query and its corresponding synthesized answer that REQUIRES information from BOTH provided text chunks (which come from the same research paper).

CRITICAL INSTRUCTIONS:
1. The question must require synthesizing or connecting information present across BOTH chunks (e.g. connecting an experimental setup in Chunk 1 with an empirical result in Chunk 2). It should NOT be answerable using only one chunk.
2. The reference answer must synthesize the information from both chunks accurately.
3. Do NOT extrapolate or introduce external facts.

Return ONLY a valid JSON object matching this schema:
{
  "query": "Synthesized multi-hop research question",
  "reference_answer": "Synthesized grounded answer requiring both chunks",
  "reasoning": "Why both chunks are strictly necessary to answer this question"
}
"""

def build_synthetic_multi_chunk_prompt(
    chunk_1_text: str, chunk_2_text: str, metadata: Optional[Dict[str, Any]] = None
) -> str:
    """Build prompt to generate a multi-chunk Q&A pair from two chunks."""
    meta_str = f"Context Metadata: {json.dumps(metadata)}\n" if metadata else ""
    return (
        f"{meta_str}"
        f"Source Chunk 1:\n---\n{chunk_1_text.strip()}\n---\n\n"
        f"Source Chunk 2:\n---\n{chunk_2_text.strip()}\n---\n\n"
        "Generate a multi-hop research question requiring both chunks and a synthesized reference answer. Return strictly valid JSON."
    )


SYNTHETIC_SELF_VERIFICATION_SYSTEM_PROMPT = """You are a rigorous quality control auditor for synthetic AI benchmark datasets.

Your task is to verify whether a candidate (query, reference_answer) pair is genuinely and accurately grounded in the provided source chunk(s).

CRITICAL INSTRUCTIONS:
1. Check: Is the query answerable using ONLY the provided chunk(s)?
2. Check: Is the reference answer strictly faithful to the chunk(s) without hallucinations or unsubstantiated leaps?
3. If valid, set is_supported to true and assign a confidence score (0.0 - 1.0).
4. If invalid, flawed, ambiguous, or relying on external information, set is_supported to false.

Return ONLY a valid JSON object matching this schema:
{
  "is_supported": true | false,
  "confidence": 0.95,
  "reasoning": "Clear explanation of why this item passes or fails grounding verification."
}
"""

def build_synthetic_self_verification_prompt(
    query: str, reference_answer: str, combined_chunks_text: str
) -> str:
    """Build prompt to audit and self-verify a synthetic Q&A candidate."""
    return (
        f"Candidate Query:\n\"{query}\"\n\n"
        f"Candidate Reference Answer:\n---\n{reference_answer.strip()}\n---\n\n"
        f"Source Context Chunk(s):\n---\n{combined_chunks_text.strip()}\n---\n\n"
        "Audit this candidate pair. Return strictly valid JSON."
    )
