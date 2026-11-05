import json
import math
from typing import Sequence, Optional, Any, Set, Dict, List

class EvaluationEngine:
    """
    Pure deterministic scoring engine for IR, Citation, and Agent Trajectory evaluation.
    Contains zero external dependencies and zero side-effects.
    """

    @staticmethod
    def _validate_k(k: Any) -> None:
        """
        Validates that K is a positive integer >= 1.
        Explicitly rejects booleans (subclass of int in Python) and non-integers.
        """
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError(f"k must be a positive integer >= 1, got {k} of type {type(k).__name__}")

    @staticmethod
    def _deduplicate(retrieved_ids: Sequence[int]) -> List[int]:
        """
        Preserves the rank order of first occurrence for retrieved chunk IDs.
        Guarantees that duplicate results cannot inflate Precision@K, Recall@K, or DCG.
        """
        seen: Set[int] = set()
        deduped: List[int] = []
        for cid in retrieved_ids:
            if cid not in seen:
                seen.add(cid)
                deduped.append(cid)
        return deduped

    @classmethod
    def compute_recall_at_k(
        cls, retrieved_ids: Sequence[int], relevant_ids: Set[int], k: int
    ) -> Optional[float]:
        """
        Recall@K = (Unique relevant chunks retrieved in top K) / (Total relevant chunks).
        Returns None if query is unannotated (relevant_ids is empty).
        """
        cls._validate_k(k)
        if not relevant_ids:
            return None
        deduped = cls._deduplicate(retrieved_ids)
        top_k = deduped[:k]
        hits = sum(1 for cid in top_k if cid in relevant_ids)
        return hits / len(relevant_ids)

    @classmethod
    def compute_precision_at_k(
        cls, retrieved_ids: Sequence[int], relevant_ids: Set[int], k: int
    ) -> Optional[float]:
        """
        Precision@K = (Unique relevant chunks retrieved in top K) / K.
        Returns None if query is unannotated.
        """
        cls._validate_k(k)
        if not relevant_ids:
            return None
        deduped = cls._deduplicate(retrieved_ids)
        top_k = deduped[:k]
        hits = sum(1 for cid in top_k if cid in relevant_ids)
        return hits / k

    @classmethod
    def compute_mrr_at_k(
        cls, retrieved_ids: Sequence[int], relevant_ids: Set[int], k: int
    ) -> Optional[float]:
        """
        MRR@K = 1.0 / rank of first relevant chunk strictly within top K (1-indexed).
        Returns 0.0 if no relevant chunk is retrieved within top K.
        Returns None if query is unannotated.
        """
        cls._validate_k(k)
        if not relevant_ids:
            return None
        deduped = cls._deduplicate(retrieved_ids)
        for rank, cid in enumerate(deduped[:k], start=1):
            if cid in relevant_ids:
                return 1.0 / rank
        return 0.0

    @classmethod
    def compute_ndcg_at_k(
        cls, retrieved_ids: Sequence[int], relevant_ids: Set[int], k: int
    ) -> Optional[float]:
        """
        nDCG@K with binary relevance and logarithmic position discounting.
        Returns None if query is unannotated.
        """
        cls._validate_k(k)
        if not relevant_ids:
            return None
        deduped = cls._deduplicate(retrieved_ids)
        top_k = deduped[:k]

        # DCG@K
        dcg = 0.0
        for i, cid in enumerate(top_k, start=1):
            if cid in relevant_ids:
                dcg += 1.0 / math.log2(i + 1)

        # IDCG@K (Ideal DCG placing min(K, |REL|) relevant hits at ranks 1..ideal_hits)
        ideal_hits = min(k, len(relevant_ids))
        if ideal_hits == 0:
            return 0.0
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))

        return dcg / idcg

    @classmethod
    def compute_hit_rate_at_k(
        cls, retrieved_ids: Sequence[int], relevant_ids: Set[int], k: int
    ) -> Optional[float]:
        """
        HitRate@K = 1.0 if at least one relevant chunk is retrieved in top K, else 0.0.
        Returns None if query is unannotated.
        """
        cls._validate_k(k)
        if not relevant_ids:
            return None
        deduped = cls._deduplicate(retrieved_ids)
        return 1.0 if any(cid in relevant_ids for cid in deduped[:k]) else 0.0

    @staticmethod
    def compute_mean_metric(scores: Sequence[Optional[float]]) -> Optional[float]:
        """
        Computes the arithmetic mean over non-None evaluable scores.
        Safe Empty Aggregation: Returns None if scores is empty or all elements are None.
        """
        evaluable = [s for s in scores if s is not None]
        return (sum(evaluable) / len(evaluable)) if evaluable else None

    @staticmethod
    def compute_citation_metrics(
        claim_evaluations: Sequence[Dict[str, Any]],
        retrieved_chunk_ids: Set[int],
    ) -> Dict[str, Optional[float]]:
        """
        Computes citation validity and semantic support across claims.
        Handles multiple citations attached to a single claim:
        - claim_citation_support_rate (OR semantics): claim is supported if >= 1 cited chunk entails it.
        - citation_link_precision: fraction of valid citation edges where chunk entails claim.
          Returns None if no valid citation edges exist.
        - citation_validity_ratio: fraction of emitted citation links pointing to retrieved chunks.
        """
        all_citation_links: List[Dict[str, bool]] = []
        claims_with_citations = 0
        claims_supported_by_citations = 0

        for record in claim_evaluations:
            cited_ids = record.get("cited_chunk_ids", [])
            if not cited_ids:
                continue
            claims_with_citations += 1
            supporting_ids = set(record.get("supporting_chunk_ids", []))

            # OR semantics across citations for a single claim
            if any(cid in supporting_ids for cid in cited_ids if cid in retrieved_chunk_ids):
                claims_supported_by_citations += 1

            for cid in cited_ids:
                is_valid = cid in retrieved_chunk_ids
                is_supported = is_valid and (cid in supporting_ids)
                all_citation_links.append({"valid": is_valid, "supported": is_supported})

        if not all_citation_links:
            # Case 1: No citations were emitted at all
            return {
                "citation_validity_ratio": None,
                "citation_link_precision": None,
                "claim_citation_support_rate": None,
            }

        valid_links = [l for l in all_citation_links if l["valid"]]
        valid_ratio = len(valid_links) / len(all_citation_links)
        claim_support_rate = (
            (claims_supported_by_citations / claims_with_citations) if claims_with_citations else 0.0
        )

        if not valid_links:
            # Case 2: Citations emitted, but NONE reference valid retrieved chunks
            return {
                "citation_validity_ratio": 0.0,
                "citation_link_precision": None,  # No valid edges exist to evaluate semantic entailment
                "claim_citation_support_rate": 0.0,
            }

        # Case 3: At least one valid citation edge exists
        link_precision = sum(1 for l in valid_links if l["supported"]) / len(valid_links)

        return {
            "citation_validity_ratio": valid_ratio,
            "citation_link_precision": link_precision,
            "claim_citation_support_rate": claim_support_rate,
        }

    @staticmethod
    def compute_agent_trajectory_metrics(
        session_status: str,
        has_final_answer: bool,
        used_tools: Sequence[str],
        expected_tools: Sequence[str],
        duplicate_tool_count: int,
        total_tool_calls: int,
        total_steps: int,
        failed_tool_calls_count: int = 0,
        min_expected_steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Computes outcome-focused agent trajectory metrics and diagnostics.
        - Primary: task_completion (1.0 vs 0.0).
        - Diagnostics: tool precision/recall/Jaccard (None if expected_tools empty),
          redundancy_ratio, trajectory_efficiency (None if min_expected_steps unavailable),
          and error_recovery_success (None if 0 errors; 1.0 if completed despite errors).
        """
        task_completion = 1.0 if (session_status == "completed" and has_final_answer) else 0.0
        redundancy_ratio = (
            (duplicate_tool_count / total_tool_calls) if total_tool_calls > 0 else 0.0
        )

        # Trajectory efficiency: None when reliable minimal expected steps is unavailable
        efficiency = None
        if min_expected_steps is not None and min_expected_steps > 0 and total_steps > 0:
            efficiency = min(1.0, min_expected_steps / total_steps)

        # Error recovery success: None if no errors occurred; 1.0 if completed despite errors, else 0.0
        error_recovery_success = None
        if failed_tool_calls_count > 0:
            error_recovery_success = 1.0 if (session_status == "completed" and has_final_answer) else 0.0

        # Tool metrics: None if expected_tools is empty. Purely diagnostic; does not penalize task completion!
        tool_metrics: Dict[str, Optional[float]] = {
            "tool_precision": None,
            "tool_recall": None,
            "tool_jaccard": None,
        }
        if expected_tools:
            u_set = set(used_tools)
            e_set = set(expected_tools)
            inter = len(u_set & e_set)
            tool_metrics["tool_precision"] = (inter / len(u_set)) if u_set else 0.0
            tool_metrics["tool_recall"] = inter / len(e_set)
            tool_metrics["tool_jaccard"] = inter / len(u_set | e_set)

        return {
            "task_completion": task_completion,
            "redundancy_ratio": redundancy_ratio,
            "trajectory_efficiency": efficiency,
            "error_recovery_success": error_recovery_success,
            "total_steps": total_steps,
            "total_tool_calls": total_tool_calls,
            **tool_metrics,
        }

    @classmethod
    def validate_k_values(cls, k_values: Sequence[int]) -> None:
        """Validate a list of K values."""
        if not k_values:
            raise ValueError("k_values cannot be empty")
        for k in k_values:
            cls._validate_k(k)

    @classmethod
    def evaluate_retrieval_for_query(
        cls,
        retrieved_chunk_ids: Sequence[int],
        expected_chunk_ids: Sequence[int],
        k_values: Sequence[int],
    ) -> Dict[str, Any]:
        """Compute all IR metrics for a single query across specified K values."""
        rel_set = set(expected_chunk_ids)
        metrics: Dict[str, Any] = {}
        for k in k_values:
            metrics[f"recall@{k}"] = cls.compute_recall_at_k(retrieved_chunk_ids, rel_set, k)
            metrics[f"precision@{k}"] = cls.compute_precision_at_k(retrieved_chunk_ids, rel_set, k)
            metrics[f"mrr@{k}"] = cls.compute_mrr_at_k(retrieved_chunk_ids, rel_set, k)
            metrics[f"ndcg@{k}"] = cls.compute_ndcg_at_k(retrieved_chunk_ids, rel_set, k)
            metrics[f"hit_rate@{k}"] = cls.compute_hit_rate_at_k(retrieved_chunk_ids, rel_set, k)
        return metrics

    @classmethod
    def aggregate_retrieval_metrics(
        cls,
        query_evaluations: Sequence[Dict[str, Any]],
        k_values: Sequence[int],
    ) -> Dict[str, Any]:
        """Aggregate IR metrics across multiple queries."""
        aggregated: Dict[str, Any] = {}
        for k in k_values:
            for metric_prefix in ["recall", "precision", "mrr", "ndcg", "hit_rate"]:
                metric_key = f"{metric_prefix}@{k}"
                scores = [q.get(metric_key) for q in query_evaluations if metric_key in q]
                aggregated[metric_key] = cls.compute_mean_metric(scores)
        aggregated["total_queries_evaluated"] = len(query_evaluations)
        return aggregated

    @classmethod
    def evaluate_citations(
        cls,
        claims_data: Sequence[Dict[str, Any]],
        retrieved_chunk_ids: Sequence[int],
    ) -> Dict[str, Optional[float]]:
        """Convenience wrapper for citation evaluation."""
        return cls.compute_citation_metrics(
            claim_evaluations=claims_data,
            retrieved_chunk_ids=set(retrieved_chunk_ids),
        )

    @classmethod
    def evaluate_agent_trajectory(
        cls,
        trajectory: Sequence[Dict[str, Any]],
        expected_tools: Sequence[str],
        session_status: str,
        has_final_answer: bool,
        min_expected_steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Parse agent trajectory records and compute trajectory metrics."""
        total_steps = len(trajectory)
        total_tool_calls = 0
        used_tools: List[str] = []
        failed_tool_calls_count = 0
        duplicate_tool_count = 0
        seen_calls: Set[str] = set()

        for step in trajectory:
            t_calls = step.get("tool_calls", [])
            action_type = step.get("action_type")
            if action_type == "duplicate_skipped":
                duplicate_tool_count += 1
            for tc in t_calls:
                total_tool_calls += 1
                tname = tc.get("tool_name", "")
                used_tools.append(tname)
                if not tc.get("success", True):
                    failed_tool_calls_count += 1
                call_sig = f"{tname}:{json.dumps(tc.get('arguments', {}), sort_keys=True)}"
                if call_sig in seen_calls:
                    duplicate_tool_count += 1
                else:
                    seen_calls.add(call_sig)

        return cls.compute_agent_trajectory_metrics(
            session_status=session_status,
            has_final_answer=has_final_answer,
            used_tools=used_tools,
            expected_tools=expected_tools,
            duplicate_tool_count=duplicate_tool_count,
            total_tool_calls=total_tool_calls,
            total_steps=total_steps,
            failed_tool_calls_count=failed_tool_calls_count,
            min_expected_steps=min_expected_steps,
        )

    @classmethod
    def aggregate_agent_metrics(
        cls, agent_evaluations: Sequence[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate agent trajectory and correctness metrics."""
        keys = [
            "task_completion",
            "redundancy_ratio",
            "trajectory_efficiency",
            "error_recovery_success",
            "tool_precision",
            "tool_recall",
            "tool_jaccard",
            "answer_correctness",
        ]
        summary: Dict[str, Any] = {}
        for k in keys:
            scores = [e.get(k) for e in agent_evaluations if k in e]
            summary[f"mean_{k}"] = cls.compute_mean_metric(scores)
        summary["total_sessions_evaluated"] = len(agent_evaluations)
        return summary

