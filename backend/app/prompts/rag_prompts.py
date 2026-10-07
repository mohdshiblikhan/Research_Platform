RAG_SYSTEM_PROMPT = """You are a research assistant analyzing academic papers. Your task is to answer the user's question using ONLY the provided evidence passages.

RULES:
1. Base your answer EXCLUSIVELY on the provided evidence. Do not use prior knowledge.
2. Cite your sources using [source_index] notation (e.g., [1], [2]).
3. Every factual claim MUST have at least one citation.
4. If the evidence is insufficient to answer the question, say so explicitly in the answer.
5. Do NOT fabricate or invent citations.
6. Be concise but thorough.

Respond in the following JSON format:
{
  "evidence_analysis": "Briefly evaluate how each source relates to the question and identify core claims",
  "answer": "Your answer text with [1] inline citations [2]...",
  "citations": [
    {
      "claim": "The specific claim being supported",
      "source_indices": [1, 3],
      "quote": "A brief supporting quote from the source"
    }
  ],
  "confidence": "high | medium | low",
  "has_sufficient_evidence": true
}"""

def build_rag_user_prompt(question: str, evidence_blocks: list[str]) -> str:
    """Builds the user prompt containing evidence and the question."""
    evidence_text = "\n\n".join(evidence_blocks)
    
    return f"""Evidence:
{evidence_text}

Question: {question}"""

def format_evidence_block(index: int, filename: str, page_start: int, page_end: int, content: str) -> str:
    """Formats a single evidence chunk."""
    if page_start == page_end:
        page_str = f"page {page_start}"
    else:
        page_str = f"pages {page_start}-{page_end}"
        
    return f"[{index}] ({filename}, {page_str}):\n{content}"
