import pytest
from app.services.evaluation_engine import EvaluationEngine

def test_k_validation_rejects_invalid():
    """Verify strict K validation rejects booleans, floats, non-integers, and <= 0."""
    with pytest.raises(ValueError):
        EvaluationEngine.compute_recall_at_k([1, 2], {1}, 0)

    with pytest.raises(ValueError):
        EvaluationEngine.compute_recall_at_k([1, 2], {1}, -1)

    with pytest.raises(ValueError):
        EvaluationEngine.compute_recall_at_k([1, 2], {1}, True)  # Boolean rejected!

    with pytest.raises(ValueError):
        EvaluationEngine.compute_recall_at_k([1, 2], {1}, False)  # Boolean rejected!

    with pytest.raises(ValueError):
        EvaluationEngine.compute_precision_at_k([1, 2], {1}, 1.5)  # Float rejected!


def test_ir_deduplication():
    """Verify duplicate retrieved chunk IDs do not inflate hits or DCG."""
    # Raw retrieved list with duplicates of chunk 10
    retrieved_with_duplicates = [10, 10, 10, 20]
    relevant = {10}

    # If deduplication did not occur, top_k 3 would see three hits!
    # With deduplication, unique list is [10, 20], so top_k 3 has 1 hit.
    precision = EvaluationEngine.compute_precision_at_k(retrieved_with_duplicates, relevant, k=3)
    assert precision == 1.0 / 3.0

    recall = EvaluationEngine.compute_recall_at_k(retrieved_with_duplicates, relevant, k=3)
    assert recall == 1.0

    # For nDCG, chunk 10 should only be counted at rank 1, not rank 2 or 3
    ndcg = EvaluationEngine.compute_ndcg_at_k(retrieved_with_duplicates, relevant, k=3)
    assert ndcg == 1.0  # DCG = 1 / log2(2) = 1.0, IDCG = 1.0


def test_unannotated_queries_excluded():
    """Verify queries with empty relevant_ids return None, and mean excludes them."""
    retrieved = [1, 2, 3]
    empty_rel = set()

    assert EvaluationEngine.compute_recall_at_k(retrieved, empty_rel, k=5) is None
    assert EvaluationEngine.compute_precision_at_k(retrieved, empty_rel, k=5) is None
    assert EvaluationEngine.compute_mrr_at_k(retrieved, empty_rel, k=5) is None
    assert EvaluationEngine.compute_ndcg_at_k(retrieved, empty_rel, k=5) is None
    assert EvaluationEngine.compute_hit_rate_at_k(retrieved, empty_rel, k=5) is None


def test_safe_empty_aggregation():
    """Verify mean computation over only None scores returns None rather than crashing."""
    scores = [None, None, None]
    assert EvaluationEngine.compute_mean_metric(scores) is None
    assert EvaluationEngine.compute_mean_metric([]) is None

    # Mixed evaluable and unannotated
    mixed = [0.8, None, 0.4]
    assert pytest.approx(EvaluationEngine.compute_mean_metric(mixed)) == 0.6


def test_mrr_at_k_cutoff():
    """Verify MRR@K returns 1/rank if <= K, and 0.0 if first hit is > K."""
    retrieved = [10, 20, 30, 40, 50]
    relevant = {30}  # rank 3

    assert EvaluationEngine.compute_mrr_at_k(retrieved, relevant, k=5) == 1.0 / 3.0
    assert EvaluationEngine.compute_mrr_at_k(retrieved, relevant, k=2) == 0.0  # Cutoff at 2 excludes rank 3


def test_ndcg_ranking_discount():
    """Verify nDCG rewards placing relevant documents higher."""
    relevant = {100, 200}
    # Ideal: relevant chunks at ranks 1 and 2
    ideal = [100, 200, 300]
    # Sub-optimal: relevant chunks at ranks 2 and 3
    suboptimal = [300, 100, 200]

    ndcg_ideal = EvaluationEngine.compute_ndcg_at_k(ideal, relevant, k=3)
    ndcg_suboptimal = EvaluationEngine.compute_ndcg_at_k(suboptimal, relevant, k=3)

    assert ndcg_ideal == 1.0
    assert 0.0 < ndcg_suboptimal < 1.0


def test_citation_metrics_empty():
    """Verify empty citations return None for all citation metrics."""
    res = EvaluationEngine.compute_citation_metrics([], {1, 2, 3})
    assert res["citation_validity_ratio"] is None
    assert res["citation_link_precision"] is None
    assert res["claim_citation_support_rate"] is None


def test_citation_link_precision_zero_valid_links():
    """
    When citations are emitted, but none reference valid chunks:
    validity_ratio = 0.0, claim_support = 0.0, but link_precision = None.
    """
    claim_evals = [
        {
            "claim": "Claim A",
            "cited_chunk_ids": [999],  # Hallucinated ID (not in retrieved set)
            "supporting_chunk_ids": [],
        }
    ]
    retrieved = {1, 2, 3}
    res = EvaluationEngine.compute_citation_metrics(claim_evals, retrieved)

    assert res["citation_validity_ratio"] == 0.0
    assert res["claim_citation_support_rate"] == 0.0
    assert res["citation_link_precision"] is None  # No valid edges exist to test!


def test_multi_citation_support_rules():
    """
    Verify claim-level OR support and link-level precision:
    Claim 1 cites [10, 20]. Chunk 10 entails it, chunk 20 does not.
    Claim 2 cites [30]. Chunk 30 does not entail it.
    All chunks [10, 20, 30] exist in retrieved set.
    """
    claim_evals = [
        {
            "claim": "Claim 1",
            "cited_chunk_ids": [10, 20],
            "supporting_chunk_ids": [10],  # 10 entails, 20 does not
        },
        {
            "claim": "Claim 2",
            "cited_chunk_ids": [30],
            "supporting_chunk_ids": [],  # neither entails
        },
    ]
    retrieved = {10, 20, 30}
    res = EvaluationEngine.compute_citation_metrics(claim_evals, retrieved)

    assert res["citation_validity_ratio"] == 1.0  # 3 of 3 citations valid
    # Claim 1 is supported (since 10 entails it). Claim 2 is not. 1 of 2 claims supported.
    assert res["claim_citation_support_rate"] == 0.5
    # Links: (Claim1, 10) supported, (Claim1, 20) unsupported, (Claim2, 30) unsupported.
    # 1 of 3 links supported:
    assert pytest.approx(res["citation_link_precision"]) == 1.0 / 3.0


def test_agent_outcome_separation_and_efficiency():
    """Verify tool deviation does not reduce task_completion, and efficiency handles None."""
    # Agent used [tool_b, tool_c] instead of expected [tool_a].
    # But completed the session successfully.
    res = EvaluationEngine.compute_agent_trajectory_metrics(
        session_status="completed",
        has_final_answer=True,
        used_tools=["tool_b", "tool_c"],
        expected_tools=["tool_a"],
        duplicate_tool_count=0,
        total_tool_calls=2,
        total_steps=3,
        failed_tool_calls_count=0,
        min_expected_steps=2,
    )
    assert res["task_completion"] == 1.0  # Primary metric unpenalized!
    assert res["tool_precision"] == 0.0   # Diagnostic deviation recorded
    assert res["tool_recall"] == 0.0
    assert res["trajectory_efficiency"] == 2.0 / 3.0
    assert res["error_recovery_success"] is None  # No tool errors occurred


def test_agent_error_recovery_success():
    """Verify error_recovery_success calculation."""
    # Case 1: Had tool error, but successfully completed session
    res_recovered = EvaluationEngine.compute_agent_trajectory_metrics(
        session_status="completed",
        has_final_answer=True,
        used_tools=["tool_a"],
        expected_tools=[],
        duplicate_tool_count=0,
        total_tool_calls=2,
        total_steps=3,
        failed_tool_calls_count=1,
    )
    assert res_recovered["error_recovery_success"] == 1.0
    assert res_recovered["tool_precision"] is None  # empty expected_tools yields None

    # Case 2: Had tool error, and failed
    res_failed = EvaluationEngine.compute_agent_trajectory_metrics(
        session_status="failed",
        has_final_answer=False,
        used_tools=["tool_a"],
        expected_tools=[],
        duplicate_tool_count=0,
        total_tool_calls=2,
        total_steps=3,
        failed_tool_calls_count=1,
    )
    assert res_failed["error_recovery_success"] == 0.0
    assert res_failed["task_completion"] == 0.0
