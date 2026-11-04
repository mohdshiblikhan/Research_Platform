import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.schemas.experiment_comparison import (
    ComparisonConfigRow,
    ComparisonConfigValue,
    ComparisonMetricRow,
    ComparisonMetricValue,
    ConfigValuePresence,
    HypothesisConsensusRow,
    HypothesisConsensusState,
    MetricDirection,
    ParetoAnalysis,
    ParetoExcludedExperiment,
    ParetoObjectiveConfig,
    ParetoObjectiveDirection,
    ParetoPoint,
)


def is_valid_numeric(val: Any) -> bool:
    """Return True only if val is a finite int or float (excluding bool)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


# --- Metric Definition & Canonical Registry ---

@dataclass(frozen=True)
class MetricDefinition:
    canonical_name: str
    display_name: str
    direction: MetricDirection
    canonical_unit: Optional[str] = None
    requires_unit: bool = False


# Canonical metric identities
METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    # Accuracy / Quality metrics (Unitless)
    "recall@1": MetricDefinition("recall@1", "Recall@1", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "recall@5": MetricDefinition("recall@5", "Recall@5", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "recall@10": MetricDefinition("recall@10", "Recall@10", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "recall@20": MetricDefinition("recall@20", "Recall@20", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "precision@1": MetricDefinition("precision@1", "Precision@1", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "precision@5": MetricDefinition("precision@5", "Precision@5", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "precision@10": MetricDefinition("precision@10", "Precision@10", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "mrr": MetricDefinition("mrr", "MRR", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "ndcg@10": MetricDefinition("ndcg@10", "nDCG@10", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "accuracy": MetricDefinition("accuracy", "Accuracy", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "f1": MetricDefinition("f1", "F1 Score", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "bleu": MetricDefinition("bleu", "BLEU", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "rouge": MetricDefinition("rouge", "ROUGE", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "hit_rate": MetricDefinition("hit_rate", "Hit Rate", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "faithfulness": MetricDefinition("faithfulness", "Faithfulness", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    "relevance": MetricDefinition("relevance", "Relevance", MetricDirection.HIGHER_IS_BETTER, canonical_unit=None),
    # Efficiency / Cost metrics (Unit-bearing)
    "latency": MetricDefinition("latency", "Latency", MetricDirection.LOWER_IS_BETTER, canonical_unit="ms", requires_unit=True),
    "cost": MetricDefinition("cost", "Cost", MetricDirection.LOWER_IS_BETTER, canonical_unit="usd", requires_unit=True),
    "vram_decimal": MetricDefinition("vram_decimal", "VRAM (Decimal)", MetricDirection.LOWER_IS_BETTER, canonical_unit="MB", requires_unit=True),
    "vram_binary": MetricDefinition("vram_binary", "VRAM (Binary)", MetricDirection.LOWER_IS_BETTER, canonical_unit="MiB", requires_unit=True),
    "error_rate": MetricDefinition("error_rate", "Error Rate", MetricDirection.LOWER_IS_BETTER, canonical_unit=None),
    "perplexity": MetricDefinition("perplexity", "Perplexity", MetricDirection.LOWER_IS_BETTER, canonical_unit=None),
    "loss": MetricDefinition("loss", "Loss", MetricDirection.LOWER_IS_BETTER, canonical_unit=None),
}

# Explicit mapping of raw alias strings to (canonical_metric_name, parsed_unit)
ALIAS_MAP: Dict[str, Tuple[str, Optional[str]]] = {
    # Recall aliases
    "recall@1": ("recall@1", None), "recall_1": ("recall@1", None), "recall 1": ("recall@1", None), "r@1": ("recall@1", None),
    "recall@5": ("recall@5", None), "recall_5": ("recall@5", None), "recall 5": ("recall@5", None), "r@5": ("recall@5", None),
    "recall@10": ("recall@10", None), "recall_10": ("recall@10", None), "recall 10": ("recall@10", None), "r@10": ("recall@10", None),
    "recall@20": ("recall@20", None), "recall_20": ("recall@20", None), "recall 20": ("recall@20", None), "r@20": ("recall@20", None),
    # Precision aliases
    "precision@1": ("precision@1", None), "precision_1": ("precision@1", None), "p@1": ("precision@1", None),
    "precision@5": ("precision@5", None), "precision_5": ("precision@5", None), "p@5": ("precision@5", None),
    "precision@10": ("precision@10", None), "precision_10": ("precision@10", None), "p@10": ("precision@10", None),
    # Ranking & Quality
    "mrr": ("mrr", None), "mrr@10": ("mrr", None), "mean_reciprocal_rank": ("mrr", None),
    "ndcg": ("ndcg@10", None), "ndcg@10": ("ndcg@10", None), "ndcg_10": ("ndcg@10", None),
    "accuracy": ("accuracy", None), "acc": ("accuracy", None),
    "f1": ("f1", None), "f1_score": ("f1", None),
    "bleu": ("bleu", None), "rouge": ("rouge", None),
    "hit_rate": ("hit_rate", None), "faithfulness": ("faithfulness", None), "relevance": ("relevance", None),
    "error_rate": ("error_rate", None), "perplexity": ("perplexity", None), "loss": ("loss", None),
    # Latency / Time (Canonical unit: ms)
    "latency": ("latency", None),
    "latency_ms": ("latency", "ms"),
    "latency_s": ("latency", "s"),
    "latency_sec": ("latency", "s"),
    "response_time_ms": ("latency", "ms"),
    "response_time_s": ("latency", "s"),
    "query_time_ms": ("latency", "ms"),
    "query_time_s": ("latency", "s"),
    "time_ms": ("latency", "ms"),
    "time_s": ("latency", "s"),
    # Cost (Canonical unit: usd)
    "cost": ("cost", None),
    "cost_usd": ("cost", "usd"),
    "cost_$": ("cost", "usd"),
    "price": ("cost", "usd"),
    # Memory (Decimal MB vs Binary MiB)
    "vram_mb": ("vram_decimal", "MB"),
    "vram_gb": ("vram_decimal", "GB"),
    "memory_mb": ("vram_decimal", "MB"),
    "memory_gb": ("vram_decimal", "GB"),
    "vram_mib": ("vram_binary", "MiB"),
    "vram_gib": ("vram_binary", "GiB"),
    "memory_mib": ("vram_binary", "MiB"),
    "memory_gib": ("vram_binary", "GiB"),
}


def resolve_metric_identity(raw_key: str) -> Tuple[str, Optional[str]]:
    """Resolve a raw metric key into (canonical_metric_name, parsed_unit)."""
    norm_key = raw_key.strip().lower()
    if norm_key in ALIAS_MAP:
        return ALIAS_MAP[norm_key]
    # Fallback: clean key, direction unknown, unit None
    clean_name = re.sub(r"[\s\-]+", "_", norm_key)
    return clean_name, None


def normalize_unit(
    canonical_metric: str,
    val: float,
    raw_unit: Optional[str],
) -> Tuple[Optional[float], Optional[str], bool]:
    """
    Normalize value to canonical unit.
    Returns: (normalized_value, canonical_or_raw_unit, is_compatible)
    """
    metric_def = METRIC_REGISTRY.get(canonical_metric)
    if not metric_def or not metric_def.requires_unit:
        # Unitless or custom metric
        return val, raw_unit, True

    canonical_unit = metric_def.canonical_unit

    # Missing unit metadata when unit is required
    if raw_unit is None:
        return val, None, False

    u = raw_unit.strip().lower()

    # Time normalization (Canonical: ms)
    if canonical_metric == "latency":
        if u in ("ms", "milliseconds"):
            return val, "ms", True
        if u in ("s", "sec", "seconds"):
            return val * 1000.0, "ms", True
        if u in ("min", "minutes"):
            return val * 60000.0, "ms", True
        return val, raw_unit, False  # Incompatible unit (e.g. tokens/sec)

    # Memory normalization - Decimal (Canonical: MB)
    if canonical_metric == "vram_decimal":
        if u in ("mb", "megabytes"):
            return val, "MB", True
        if u in ("gb", "gigabytes"):
            return val * 1000.0, "MB", True
        if u in ("kb", "kilobytes"):
            return val / 1000.0, "MB", True
        return val, raw_unit, False

    # Memory normalization - Binary (Canonical: MiB)
    if canonical_metric == "vram_binary":
        if u in ("mib", "mebibytes"):
            return val, "MiB", True
        if u in ("gib", "gibibytes"):
            return val * 1024.0, "MiB", True
        if u in ("kib", "kibibytes"):
            return val / 1024.0, "MiB", True
        return val, raw_unit, False

    # Cost normalization (Canonical: usd)
    if canonical_metric == "cost":
        if u in ("usd", "$", "dollars"):
            return val, "usd", True
        return val, raw_unit, False

    return val, raw_unit, True


# --- Baseline Delta & Direction Engine ---

def compute_delta_status(
    val: float,
    baseline: float,
    direction: MetricDirection,
    tolerance: float = 1e-6,
) -> str:
    """
    Determine improvement status.
    CRITICAL: Checks UNKNOWN direction first, returning 'unspecified' even on zero delta.
    """
    if direction == MetricDirection.UNKNOWN:
        return "unspecified"

    diff = val - baseline
    if abs(diff) <= tolerance:
        return "neutral"

    if direction == MetricDirection.HIGHER_IS_BETTER:
        return "improvement" if diff > 0 else "regression"
    if direction == MetricDirection.LOWER_IS_BETTER:
        return "improvement" if diff < 0 else "regression"

    return "unspecified"


def compute_baseline_deltas(
    val: Optional[float],
    baseline: Optional[float],
    direction: MetricDirection,
    is_compatible: bool,
    tolerance: float = 1e-6,
) -> Tuple[Optional[float], Optional[float], str]:
    """Compute (baseline_delta, percent_change, status)."""
    if not is_compatible:
        return None, None, "incompatible_units"

    if val is None or baseline is None:
        return None, None, "not_applicable"

    delta = round(val - baseline, 6)
    if abs(baseline) > tolerance:
        pct = round(((val - baseline) / abs(baseline)) * 100.0, 4)
    else:
        pct = None

    status = compute_delta_status(val, baseline, direction, tolerance=tolerance)
    return delta, pct, status


# --- Configuration Divergence Engine ---

def build_configuration_matrix(experiments: list[Any]) -> list[ComparisonConfigRow]:
    """Compare parameters and variables across experiments using deep canonical JSON serialization."""
    rows: list[ComparisonConfigRow] = []

    for category in ("parameter", "variable"):
        all_keys: Set[str] = set()
        for exp in experiments:
            d = (getattr(exp, "parameters", {}) if category == "parameter" else getattr(exp, "variables", {})) or {}
            all_keys.update(d.keys())

        for key in sorted(all_keys):
            values_map: Dict[int, ComparisonConfigValue] = {}
            repr_set: Set[str] = set()

            for exp in experiments:
                d = (getattr(exp, "parameters", {}) if category == "parameter" else getattr(exp, "variables", {})) or {}
                if key not in d:
                    values_map[exp.id] = ComparisonConfigValue(presence=ConfigValuePresence.MISSING, value=None)
                    repr_set.add("__MISSING__")
                elif d[key] is None:
                    values_map[exp.id] = ComparisonConfigValue(presence=ConfigValuePresence.EXPLICIT_NULL, value=None)
                    repr_set.add("__NULL__")
                else:
                    v = d[key]
                    values_map[exp.id] = ComparisonConfigValue(presence=ConfigValuePresence.SET, value=v)
                    try:
                        serialized = json.dumps(v, sort_keys=True, allow_nan=False)
                    except (TypeError, ValueError):
                        serialized = str(v)
                    repr_set.add(serialized)

            is_varying = len(repr_set) > 1
            rows.append(
                ComparisonConfigRow(
                    category=category,  # type: ignore[arg-type]
                    key=key,
                    values=values_map,
                    is_varying=is_varying,
                )
            )

    return rows


# --- Quantitative Metrics Matrix Engine ---

def build_metrics_matrix(
    experiments: list[Any],
    baseline_id: int,
    focus_metrics: Optional[list[str]] = None,
    tolerance: float = 1e-6,
) -> list[ComparisonMetricRow]:
    """Assemble quantitative metric matrix with canonicalization, normalization, and deltas."""
    # 1. Discover all metrics present across experiments
    metric_entries: Dict[str, Dict[int, Tuple[Any, Optional[str]]]] = {}
    # metric_name -> exp_id -> (raw_value, unit)

    for exp in experiments:
        results = getattr(exp, "results", {}) or {}
        for raw_k, raw_v in results.items():
            metric_name, parsed_unit = resolve_metric_identity(raw_k)

            # Check if structured dict with unit: {"value": 0.15, "unit": "s"}
            if isinstance(raw_v, dict) and "value" in raw_v:
                extracted_val = raw_v["value"]
                extracted_unit = raw_v.get("unit") or parsed_unit
            else:
                extracted_val = raw_v
                extracted_unit = parsed_unit

            if metric_name not in metric_entries:
                metric_entries[metric_name] = {}
            metric_entries[metric_name][exp.id] = (extracted_val, extracted_unit)

    # Filter metrics if focus_metrics provided
    if focus_metrics:
        canonical_focus = {resolve_metric_identity(m)[0] for m in focus_metrics}
        metric_entries = {k: v for k, v in metric_entries.items() if k in canonical_focus}

    rows: list[ComparisonMetricRow] = []

    for metric_name in sorted(metric_entries.keys()):
        exp_data = metric_entries[metric_name]
        metric_def = METRIC_REGISTRY.get(metric_name)
        direction = metric_def.direction if metric_def else MetricDirection.UNKNOWN
        display_name = metric_def.display_name if metric_def else metric_name.replace("_", " ").title()
        canonical_unit = metric_def.canonical_unit if metric_def else None

        # Parse normalized values for all experiments
        normalized_vals: Dict[int, Optional[float]] = {}
        units_map: Dict[int, Optional[str]] = {}
        compatibility_map: Dict[int, bool] = {}

        for exp in experiments:
            if exp.id in exp_data:
                raw_v, raw_u = exp_data[exp.id]
                if is_valid_numeric(raw_v):
                    norm_v, u, is_comp = normalize_unit(metric_name, float(raw_v), raw_u)
                    normalized_vals[exp.id] = norm_v if is_comp else None
                    units_map[exp.id] = u
                    compatibility_map[exp.id] = is_comp
                else:
                    normalized_vals[exp.id] = None
                    units_map[exp.id] = raw_u
                    compatibility_map[exp.id] = True
            else:
                normalized_vals[exp.id] = None
                units_map[exp.id] = None
                compatibility_map[exp.id] = True

        # Baseline normalized value
        baseline_norm_v = normalized_vals.get(baseline_id)
        baseline_is_comp = compatibility_map.get(baseline_id, True)

        # Compute summary stats over valid normalized values
        valid_floats = [v for v in normalized_vals.values() if v is not None]
        min_v = round(min(valid_floats), 6) if valid_floats else None
        max_v = round(max(valid_floats), 6) if valid_floats else None
        avg_v = round(sum(valid_floats) / len(valid_floats), 6) if valid_floats else None

        # Compute best value(s) strictly on normalized numeric values with known direction
        best_ids: list[int] = []
        has_tie = False
        if valid_floats and direction != MetricDirection.UNKNOWN:
            target_val = max(valid_floats) if direction == MetricDirection.HIGHER_IS_BETTER else min(valid_floats)
            for exp_id, n_val in normalized_vals.items():
                if n_val is not None and abs(n_val - target_val) <= tolerance:
                    best_ids.append(exp_id)
            has_tie = len(best_ids) > 1

        # Build ComparisonMetricValue map
        values_dict: Dict[int, ComparisonMetricValue] = {}
        for exp in experiments:
            raw_v = exp_data.get(exp.id, (None, None))[0]
            norm_v = normalized_vals.get(exp.id)
            u = units_map.get(exp.id)
            is_comp = compatibility_map.get(exp.id, True) and baseline_is_comp

            if exp.id == baseline_id:
                status = "baseline"
                delta, pct = 0.0, 0.0
            else:
                delta, pct, status = compute_baseline_deltas(
                    norm_v, baseline_norm_v, direction, is_comp, tolerance=tolerance
                )

            is_best = (exp.id in best_ids)
            values_dict[exp.id] = ComparisonMetricValue(
                experiment_id=exp.id,
                title=exp.title,
                raw_value=raw_v,
                numeric_value=norm_v,
                unit=u,
                baseline_delta=delta,
                percent_change=pct,
                status=status,  # type: ignore[arg-type]
                is_best=is_best,
            )

        rows.append(
            ComparisonMetricRow(
                metric_name=metric_name,
                display_name=display_name,
                direction=direction,
                canonical_unit=canonical_unit,
                values=values_dict,
                best_experiment_ids=best_ids,
                has_tie=has_tie,
                min_value=min_v,
                max_value=max_v,
                average_value=avg_v,
            )
        )

    return rows


# --- Pareto Frontier Analysis Engine ---

def compute_pareto_frontier(
    experiments: list[Any],
    objective_x: ParetoObjectiveConfig,
    objective_y: ParetoObjectiveConfig,
    tolerance: float = 1e-6,
) -> ParetoAnalysis:
    """
    Compute 2-objective Pareto non-domination.
    Raises ValueError for duplicate canonical metrics or missing direction.
    """
    canon_x, _ = resolve_metric_identity(objective_x.metric)
    canon_y, _ = resolve_metric_identity(objective_y.metric)

    # 1. Reject duplicate canonical objectives
    if canon_x == canon_y:
        raise ValueError(
            f"Pareto analysis requires two distinct metrics. Both objectives refer to canonical metric '{canon_x}'."
        )

    # 2. Resolve directions
    dir_x = objective_x.direction
    if not dir_x:
        metric_def_x = METRIC_REGISTRY.get(canon_x)
        if metric_def_x and metric_def_x.direction == MetricDirection.HIGHER_IS_BETTER:
            dir_x = ParetoObjectiveDirection.MAXIMIZE
        elif metric_def_x and metric_def_x.direction == MetricDirection.LOWER_IS_BETTER:
            dir_x = ParetoObjectiveDirection.MINIMIZE
        else:
            raise ValueError(
                f"Direction for metric '{canon_x}' is unknown and must be explicitly specified as 'maximize' or 'minimize'."
            )

    dir_y = objective_y.direction
    if not dir_y:
        metric_def_y = METRIC_REGISTRY.get(canon_y)
        if metric_def_y and metric_def_y.direction == MetricDirection.HIGHER_IS_BETTER:
            dir_y = ParetoObjectiveDirection.MAXIMIZE
        elif metric_def_y and metric_def_y.direction == MetricDirection.LOWER_IS_BETTER:
            dir_y = ParetoObjectiveDirection.MINIMIZE
        else:
            raise ValueError(
                f"Direction for metric '{canon_y}' is unknown and must be explicitly specified as 'maximize' or 'minimize'."
            )

    # 3. Extract and normalize objective values
    points_dict: Dict[int, Tuple[float, float, str]] = {}  # exp_id -> (norm_x, norm_y, title)
    excluded: list[ParetoExcludedExperiment] = []

    for exp in experiments:
        results = getattr(exp, "results", {}) or {}
        # Find matching raw keys
        raw_vx, raw_ux, raw_vy, raw_uy = None, None, None, None
        for k, v in results.items():
            c_name, parsed_u = resolve_metric_identity(k)
            extracted_val = v.get("value") if isinstance(v, dict) and "value" in v else v
            extracted_unit = (v.get("unit") if isinstance(v, dict) else None) or parsed_u

            if c_name == canon_x and raw_vx is None:
                raw_vx, raw_ux = extracted_val, extracted_unit
            elif c_name == canon_y and raw_vy is None:
                raw_vy, raw_uy = extracted_val, extracted_unit

        # Check validity for objective X
        if raw_vx is None or not is_valid_numeric(raw_vx):
            excluded.append(
                ParetoExcludedExperiment(
                    experiment_id=exp.id,
                    title=exp.title,
                    reason=f"Missing numeric value for objective '{canon_x}'",
                )
            )
            continue
        norm_x, _, comp_x = normalize_unit(canon_x, float(raw_vx), raw_ux)
        if not comp_x or norm_x is None:
            excluded.append(
                ParetoExcludedExperiment(
                    experiment_id=exp.id,
                    title=exp.title,
                    reason=f"Missing or incompatible unit metadata for objective '{canon_x}'",
                )
            )
            continue

        # Check validity for objective Y
        if raw_vy is None or not is_valid_numeric(raw_vy):
            excluded.append(
                ParetoExcludedExperiment(
                    experiment_id=exp.id,
                    title=exp.title,
                    reason=f"Missing numeric value for objective '{canon_y}'",
                )
            )
            continue
        norm_y, _, comp_y = normalize_unit(canon_y, float(raw_vy), raw_uy)
        if not comp_y or norm_y is None:
            excluded.append(
                ParetoExcludedExperiment(
                    experiment_id=exp.id,
                    title=exp.title,
                    reason=f"Missing or incompatible unit metadata for objective '{canon_y}'",
                )
            )
            continue

        points_dict[exp.id] = (norm_x, norm_y, exp.title)

    if not points_dict:
        raise ValueError("Pareto analysis requested but zero eligible experiments exist.")

    # 4. Compute Dominance
    # A dominates B iff A is no worse than B on both objectives, and strictly better on at least one
    dominated_by: Dict[int, list[int]] = {eid: [] for eid in points_dict}
    dominates: Dict[int, list[int]] = {eid: [] for eid in points_dict}

    eligible_ids = list(points_dict.keys())
    for i in range(len(eligible_ids)):
        id_a = eligible_ids[i]
        xa, ya, _ = points_dict[id_a]
        for j in range(len(eligible_ids)):
            if i == j:
                continue
            id_b = eligible_ids[j]
            xb, yb, _ = points_dict[id_b]

            # A vs B on X
            diff_x = xa - xb
            a_ge_x = (diff_x >= -tolerance) if dir_x == ParetoObjectiveDirection.MAXIMIZE else (diff_x <= tolerance)
            a_gt_x = (diff_x > tolerance) if dir_x == ParetoObjectiveDirection.MAXIMIZE else (diff_x < -tolerance)

            # A vs B on Y
            diff_y = ya - yb
            a_ge_y = (diff_y >= -tolerance) if dir_y == ParetoObjectiveDirection.MAXIMIZE else (diff_y <= tolerance)
            a_gt_y = (diff_y > tolerance) if dir_y == ParetoObjectiveDirection.MAXIMIZE else (diff_y < -tolerance)

            if a_ge_x and a_ge_y and (a_gt_x or a_gt_y):
                dominates[id_a].append(id_b)
                dominated_by[id_b].append(id_a)

    pareto_optimal_ids = [eid for eid, dom_list in dominated_by.items() if len(dom_list) == 0]

    pareto_points: list[ParetoPoint] = []
    for eid, (nx, ny, title) in points_dict.items():
        is_optimal = eid in pareto_optimal_ids
        pareto_points.append(
            ParetoPoint(
                experiment_id=eid,
                title=title,
                objective_values={canon_x: nx, canon_y: ny},
                is_pareto_optimal=is_optimal,
                dominated_by=dominated_by[eid],
                dominates=dominates[eid],
            )
        )

    summary = (
        f"Evaluated {len(points_dict)} eligible experiments across {canon_x} ({dir_x.value}) "
        f"and {canon_y} ({dir_y.value}). Found {len(pareto_optimal_ids)} Pareto-optimal configurations "
        f"(IDs: {pareto_optimal_ids}). {len(excluded)} experiments excluded due to missing or incompatible values."
    )

    return ParetoAnalysis(
        objective_x=ParetoObjectiveConfig(metric=canon_x, direction=dir_x),
        objective_y=ParetoObjectiveConfig(metric=canon_y, direction=dir_y),
        pareto_optimal_experiment_ids=pareto_optimal_ids,
        points=pareto_points,
        excluded_experiments=excluded,
        trade_off_summary=summary,
    )


# --- Hypothesis Consensus Engine ---

def compute_hypothesis_consensus(
    experiments: list[Any],
) -> Tuple[list[HypothesisConsensusRow], list[int], list[int]]:
    """
    Deterministic hypothesis verdict aggregator.
    Returns: (consensus_rows, manual_hypothesis_experiment_ids, unassigned_experiment_ids)
    """
    plan_groups: Dict[Tuple[int, str], list[Any]] = {}  # (research_plan_id, hyp_id) -> exps
    manual_hyp_ids: list[int] = []
    unassigned_ids: list[int] = []

    for exp in experiments:
        hyp_id = getattr(exp, "hypothesis_id", None)
        plan_id = getattr(exp, "research_plan_id", None)

        if not hyp_id or not hyp_id.strip():
            unassigned_ids.append(exp.id)
            continue

        clean_hyp_id = hyp_id.strip()

        # If manual experiment without research plan, isolate from cross-experiment consensus
        if plan_id is None:
            manual_hyp_ids.append(exp.id)
            continue

        key = (plan_id, clean_hyp_id)
        if key not in plan_groups:
            plan_groups[key] = []
        plan_groups[key].append(exp)

    consensus_rows: list[HypothesisConsensusRow] = []

    for (plan_id, hyp_id), group_exps in sorted(plan_groups.items(), key=lambda x: (x[0][0], x[0][1])):
        supp_ids: list[int] = []
        refute_ids: list[int] = []
        inconc_ids: list[int] = []
        no_verdict_ids: list[int] = []
        statements: list[str] = []

        for exp in group_exps:
            stmt = getattr(exp, "hypothesis_statement", None)
            if stmt and stmt.strip() and stmt.strip() not in statements:
                statements.append(stmt.strip())

            findings = getattr(exp, "findings", {}) or {}
            verdict = findings.get("hypothesis_verdict")
            if verdict == "supported":
                supp_ids.append(exp.id)
            elif verdict == "refuted":
                refute_ids.append(exp.id)
            elif verdict == "inconclusive":
                inconc_ids.append(exp.id)
            else:
                no_verdict_ids.append(exp.id)

        s_cnt, r_cnt, i_cnt = len(supp_ids), len(refute_ids), len(inconc_ids)

        if s_cnt > 0 and r_cnt == 0:
            consensus_state = HypothesisConsensusState.SUPPORTED
        elif r_cnt > 0 and s_cnt == 0:
            consensus_state = HypothesisConsensusState.CONTRADICTED
        elif s_cnt > 0 and r_cnt > 0:
            consensus_state = HypothesisConsensusState.MIXED
        elif i_cnt > 0:
            consensus_state = HypothesisConsensusState.INCONCLUSIVE
        else:
            consensus_state = HypothesisConsensusState.INSUFFICIENT_DATA

        primary_stmt = statements[0] if statements else None
        statement_variants = statements if len(statements) > 1 else []

        consensus_rows.append(
            HypothesisConsensusRow(
                hypothesis_id=hyp_id,
                research_plan_id=plan_id,
                hypothesis_statement=primary_stmt,
                statement_variants=statement_variants,
                supporting_count=s_cnt,
                supporting_experiment_ids=supp_ids,
                refuting_count=r_cnt,
                refuting_experiment_ids=refute_ids,
                inconclusive_count=i_cnt,
                inconclusive_experiment_ids=inconc_ids,
                no_verdict_count=len(no_verdict_ids),
                no_verdict_experiment_ids=no_verdict_ids,
                consensus=consensus_state,
                contributing_experiment_ids=[e.id for e in group_exps],
            )
        )

    return consensus_rows, manual_hyp_ids, unassigned_ids


# --- Markdown Table Generator ---

def generate_markdown_report(
    experiments: list[Any],
    baseline_id: int,
    config_rows: list[ComparisonConfigRow],
    metric_rows: list[ComparisonMetricRow],
    pareto: Optional[ParetoAnalysis],
    consensus: list[HypothesisConsensusRow],
    manual_hyp_ids: list[int],
    unassigned_ids: list[int],
) -> str:
    """Generate clean, GitHub-Flavored Markdown comparison table."""
    lines: list[str] = ["# Experiment Comparison Report\n"]

    # 1. Summary Header
    lines.append(f"**Experiments Compared**: {len(experiments)} | **Baseline Experiment ID**: {baseline_id}\n")

    # 2. Configurations Table
    varying_configs = [r for r in config_rows if r.is_varying]
    if varying_configs:
        lines.append("## Configuration Divergence\n")
        exp_headers = [f"Exp {e.id}" for e in experiments]
        header = f"| Category | Hyperparameter | {' | '.join(exp_headers)} |"
        sep = f"|:---|:---|{'|:---' * len(experiments)}|"
        lines.extend([header, sep])

        for row in varying_configs:
            val_strs = []
            for e in experiments:
                cv = row.values.get(e.id)
                if not cv or cv.presence == ConfigValuePresence.MISSING:
                    val_strs.append("*missing*")
                elif cv.presence == ConfigValuePresence.EXPLICIT_NULL:
                    val_strs.append("*null*")
                else:
                    val_strs.append(f"`{cv.value}`")
            lines.append(f"| {row.category} | `{row.key}` | {' | '.join(val_strs)} |")
        lines.append("")

    # 3. Metrics Matrix Table
    if metric_rows:
        lines.append("## Quantitative Evaluation Metrics\n")
        exp_headers = [f"Exp {e.id}{' (Base)' if e.id == baseline_id else ''}" for e in experiments]
        header = f"| Metric | Unit | Direction | {' | '.join(exp_headers)} |"
        sep = f"|:---|:---|:---:|{'|:---' * len(experiments)}|"
        lines.extend([header, sep])

        for mr in metric_rows:
            unit_str = mr.canonical_unit or "-"
            dir_str = "↑" if mr.direction == MetricDirection.HIGHER_IS_BETTER else ("↓" if mr.direction == MetricDirection.LOWER_IS_BETTER else "?")
            val_cols = []
            for e in experiments:
                mv = mr.values.get(e.id)
                if not mv or mv.numeric_value is None:
                    val_cols.append("-")
                elif e.id == baseline_id:
                    star = " ★" if mv.is_best else ""
                    val_cols.append(f"**{mv.numeric_value}**{star}")
                else:
                    star = " ★" if mv.is_best else ""
                    delta_str = f" ({'+' if (mv.baseline_delta or 0) > 0 else ''}{mv.baseline_delta})" if mv.baseline_delta is not None else ""
                    val_cols.append(f"{mv.numeric_value}{delta_str}{star}")
            lines.append(f"| **{mr.display_name}** | {unit_str} | {dir_str} | {' | '.join(val_cols)} |")
        lines.append("\n*★ indicates best performing configuration for metric.*\n")

    # 4. Pareto Frontier
    if pareto:
        lines.append("## Multi-Objective Pareto Frontier\n")
        lines.append(f"- **Objective X**: `{pareto.objective_x.metric}` ({pareto.objective_x.direction.value})")
        lines.append(f"- **Objective Y**: `{pareto.objective_y.metric}` ({pareto.objective_y.direction.value})")
        lines.append(f"- **Pareto-Optimal Runs**: {', '.join(f'Exp {eid}' for eid in pareto.pareto_optimal_experiment_ids)}")
        lines.append(f"- {pareto.trade_off_summary}\n")

    # 5. Hypothesis Consensus
    if consensus:
        lines.append("## Hypothesis Verdict Consensus\n")
        lines.append("| Plan ID | Hypothesis | Verdict Consensus | Supporting | Refuting | Inconclusive |")
        lines.append("|:---:|:---|:---:|:---:|:---:|:---:|")
        for h in consensus:
            plan_str = f"Plan {h.research_plan_id}" if h.research_plan_id else "None"
            lines.append(
                f"| {plan_str} | **{h.hypothesis_id}** | `{h.consensus.value}` | "
                f"{h.supporting_count} (Exp {h.supporting_experiment_ids}) | "
                f"{h.refuting_count} (Exp {h.refuting_experiment_ids}) | "
                f"{h.inconclusive_count} (Exp {h.inconclusive_experiment_ids}) |"
            )
        lines.append("")

    if manual_hyp_ids:
        lines.append(f"*Note: Manual experiments {manual_hyp_ids} have hypotheses but were excluded from cross-experiment consensus aggregation.*")
    if unassigned_ids:
        lines.append(f"*Note: Experiments {unassigned_ids} have no hypothesis tag assigned.*")

    return "\n".join(lines)
