import math
import pytest
from unittest.mock import MagicMock

from app.models.document import Document, DocumentStatus
from app.models.experiment import Experiment, ExperimentPriority, ExperimentStatus
from app.models.project import Project
from app.models.research_plan import ResearchPlan
from app.schemas.experiment_comparison import (
    ComparisonConfigRow,
    ComparisonMetricRow,
    ConfigValuePresence,
    ExperimentComparisonRequest,
    HypothesisConsensusState,
    MetricDirection,
    ParetoObjectiveConfig,
    ParetoObjectiveDirection,
)
from app.services.experiment_comparison_engine import (
    ALIAS_MAP,
    METRIC_REGISTRY,
    build_configuration_matrix,
    build_metrics_matrix,
    compute_baseline_deltas,
    compute_delta_status,
    compute_hypothesis_consensus,
    compute_pareto_frontier,
    generate_markdown_report,
    is_valid_numeric,
    normalize_unit,
    resolve_metric_identity,
)
from app.services.experiment_comparison_service import ExperimentComparisonService
from app.services.tools.base import ToolContext
from app.services.tools.implementations import CompareExperimentsTool


# --- Helper Dummy Classes for Engine Unit Tests ---

class DummyExperiment:
    def __init__(
        self,
        id: int,
        title: str = "Exp",
        status: str = "completed",
        research_plan_id: int | None = None,
        hypothesis_id: str | None = None,
        hypothesis_statement: str | None = None,
        parameters: dict | None = None,
        variables: dict | None = None,
        results: dict | None = None,
        findings: dict | None = None,
    ):
        self.id = id
        self.title = title
        self.status = status
        self.research_plan_id = research_plan_id
        self.hypothesis_id = hypothesis_id
        self.hypothesis_statement = hypothesis_statement
        self.plan_experiment_id = f"E{id}"
        self.parameters = parameters or {}
        self.variables = variables or {}
        self.results = results or {}
        self.findings = findings or {}


# ============================================================================
# Engine Unit Tests (Tests 1 to 21)
# ============================================================================

def test_1_metric_canonicalization_and_aliases():
    """Verify raw alias variants resolve to canonical names with higher_is_better direction."""
    for alias in ("Recall@10", "recall_10", "recall 10", "r@10"):
        c_name, unit = resolve_metric_identity(alias)
        assert c_name == "recall@10"
        assert unit is None
        metric_def = METRIC_REGISTRY[c_name]
        assert metric_def.direction == MetricDirection.HIGHER_IS_BETTER


def test_2_semantic_metric_distinction():
    """Verify recall@10 and recall@20 are strictly kept separate and never merged."""
    c10, _ = resolve_metric_identity("recall@10")
    c20, _ = resolve_metric_identity("recall@20")
    assert c10 == "recall@10"
    assert c20 == "recall@20"
    assert c10 != c20


def test_3_metric_identity_and_unit_separation():
    """Verify latency_ms and latency_s resolve to identity 'latency' with units 'ms' and 's'."""
    c_ms, u_ms = resolve_metric_identity("latency_ms")
    c_s, u_s = resolve_metric_identity("latency_s")
    assert c_ms == "latency"
    assert u_ms == "ms"
    assert c_s == "latency"
    assert u_s == "s"


def test_4_unit_normalization_decimal_vs_binary():
    """Verify exact time normalization and strict decimal vs binary memory normalization."""
    # Time: 0.15s -> 150.0ms
    norm_val, unit, comp = normalize_unit("latency", 0.15, "s")
    assert comp is True
    assert unit == "ms"
    assert math.isclose(norm_val, 150.0, rel_tol=1e-5)

    # Decimal Memory: 1 GB = 1000 MB
    norm_gb, unit_mb, comp_dec = normalize_unit("vram_decimal", 1.0, "GB")
    assert comp_dec is True
    assert unit_mb == "MB"
    assert math.isclose(norm_gb, 1000.0, rel_tol=1e-5)

    # Binary Memory: 1 GiB = 1024 MiB
    norm_gib, unit_mib, comp_bin = normalize_unit("vram_binary", 1.0, "GiB")
    assert comp_bin is True
    assert unit_mib == "MiB"
    assert math.isclose(norm_gib, 1024.0, rel_tol=1e-5)


def test_5_incompatible_unit_handling_metric_row():
    """Verify mismatched units get status 'incompatible_units' and None delta without throwing 400."""
    exp1 = DummyExperiment(1, results={"latency": {"value": 150, "unit": "ms"}})
    exp2 = DummyExperiment(2, results={"latency": {"value": 50, "unit": "tokens/sec"}})  # Incompatible unit

    matrix = build_metrics_matrix([exp1, exp2], baseline_id=1)
    assert len(matrix) == 1
    latency_row = matrix[0]
    assert latency_row.metric_name == "latency"
    assert latency_row.values[2].status == "incompatible_units"
    assert latency_row.values[2].baseline_delta is None
    assert latency_row.values[2].percent_change is None


def test_6_strict_numeric_validation_is_valid_numeric():
    """Verify is_valid_numeric rejects booleans, NaN, and inf."""
    assert is_valid_numeric(42) is True
    assert is_valid_numeric(0.85) is True
    assert is_valid_numeric(0) is True

    # Critical edge cases: bool is subclass of int, and NaN/inf are floats
    assert is_valid_numeric(True) is False
    assert is_valid_numeric(False) is False
    assert is_valid_numeric(float("nan")) is False
    assert is_valid_numeric(float("inf")) is False
    assert is_valid_numeric(float("-inf")) is False
    assert is_valid_numeric("not a number") is False
    assert is_valid_numeric(None) is False


def test_7_directional_delta_and_status_calculation():
    """Verify deltas and status classification for higher_is_better and lower_is_better."""
    # Higher is better: 0.85 vs 0.80 baseline -> +0.05 (+6.25%, improvement)
    d, pct, s = compute_baseline_deltas(0.85, 0.80, MetricDirection.HIGHER_IS_BETTER, is_compatible=True)
    assert math.isclose(d, 0.05, abs_tol=1e-5)
    assert math.isclose(pct, 6.25, abs_tol=1e-4)
    assert s == "improvement"

    # Lower is better: 35ms vs 50ms baseline -> -15ms (-30.0%, improvement)
    d, pct, s = compute_baseline_deltas(35.0, 50.0, MetricDirection.LOWER_IS_BETTER, is_compatible=True)
    assert math.isclose(d, -15.0, abs_tol=1e-5)
    assert math.isclose(pct, -30.0, abs_tol=1e-4)
    assert s == "improvement"

    # Lower is better: 60ms vs 50ms baseline -> +10ms (+20.0%, regression)
    d, pct, s = compute_baseline_deltas(60.0, 50.0, MetricDirection.LOWER_IS_BETTER, is_compatible=True)
    assert math.isclose(d, 10.0, abs_tol=1e-5)
    assert math.isclose(pct, 20.0, abs_tol=1e-4)
    assert s == "regression"


def test_8_unknown_direction_checked_first():
    """Verify unknown direction returns 'unspecified' even when delta is exactly zero."""
    status_diff = compute_delta_status(10.0, 10.0, MetricDirection.UNKNOWN, tolerance=1e-6)
    assert status_diff == "unspecified"

    status_nonzero = compute_delta_status(12.0, 10.0, MetricDirection.UNKNOWN, tolerance=1e-6)
    assert status_nonzero == "unspecified"


def test_9_missing_unit_metadata_policy():
    """Verify bare metric requiring units without metadata yields incompatible_units."""
    exp1 = DummyExperiment(1, results={"latency_ms": 150})
    exp2 = DummyExperiment(2, results={"latency": 0.15})  # Bare key without unit metadata

    matrix = build_metrics_matrix([exp1, exp2], baseline_id=1)
    latency_row = matrix[0]
    assert latency_row.values[2].status == "incompatible_units"
    assert latency_row.values[2].baseline_delta is None


def test_10_parameterized_tolerance():
    """Verify custom tolerance classifies small differences as neutral."""
    # Difference is 0.03. With tolerance 0.05 -> neutral. With default 1e-6 -> improvement.
    status_tolerant = compute_delta_status(0.83, 0.80, MetricDirection.HIGHER_IS_BETTER, tolerance=0.05)
    assert status_tolerant == "neutral"

    status_strict = compute_delta_status(0.83, 0.80, MetricDirection.HIGHER_IS_BETTER, tolerance=1e-6)
    assert status_strict == "improvement"


def test_11_zero_baseline_safe_handling():
    """Verify baseline 0.0 does not crash with ZeroDivisionError and sets percent_change to None."""
    delta, pct, status = compute_baseline_deltas(5.0, 0.0, MetricDirection.HIGHER_IS_BETTER, is_compatible=True)
    assert delta == 5.0
    assert pct is None
    assert status == "improvement"


def test_12_missing_metric_handling():
    """Verify missing metric yields raw_value None, not 0.0, and delta None."""
    exp1 = DummyExperiment(1, results={"recall@10": 0.85})
    exp2 = DummyExperiment(2, results={})  # Missing recall@10

    matrix = build_metrics_matrix([exp1, exp2], baseline_id=1)
    row = matrix[0]
    assert row.values[2].raw_value is None
    assert row.values[2].numeric_value is None
    assert row.values[2].baseline_delta is None
    assert row.values[2].status == "not_applicable"


def test_13_is_best_with_ties_and_missing():
    """Verify tied best values both receive is_best = True and set has_tie = True; missing values get False."""
    exp1 = DummyExperiment(1, results={"recall@10": 0.90})
    exp2 = DummyExperiment(2, results={"recall@10": 0.90})  # Tied best
    exp3 = DummyExperiment(3, results={"recall@10": 0.80})
    exp4 = DummyExperiment(4, results={})                   # Missing

    matrix = build_metrics_matrix([exp1, exp2, exp3, exp4], baseline_id=1)
    row = matrix[0]
    assert row.best_experiment_ids == [1, 2]
    assert row.has_tie is True
    assert row.values[1].is_best is True
    assert row.values[2].is_best is True
    assert row.values[3].is_best is False
    assert row.values[4].is_best is False


def test_14_configuration_deep_equality():
    """Verify deep equality via canonical JSON serialization distinguishes SET, EXPLICIT_NULL, and MISSING."""
    exp1 = DummyExperiment(1, parameters={"retriever": "hybrid", "chunk_size": 1000, "meta": {"a": 1, "b": 2}})
    # Same dict with different key ordering should match (deep equality)
    exp2 = DummyExperiment(2, parameters={"chunk_size": 1000, "retriever": "hybrid", "meta": {"b": 2, "a": 1}})
    # Explicit null
    exp3 = DummyExperiment(3, parameters={"chunk_size": None, "retriever": "dense"})
    # Missing chunk_size
    exp4 = DummyExperiment(4, parameters={"retriever": "dense"})

    rows = build_configuration_matrix([exp1, exp2, exp3, exp4])
    chunk_row = next(r for r in rows if r.key == "chunk_size")
    assert chunk_row.values[1].presence == ConfigValuePresence.SET
    assert chunk_row.values[2].presence == ConfigValuePresence.SET
    assert chunk_row.values[3].presence == ConfigValuePresence.EXPLICIT_NULL
    assert chunk_row.values[4].presence == ConfigValuePresence.MISSING

    # exp1 and exp2 have identical meta dicts
    meta_row = next(r for r in rows if r.key == "meta")
    assert meta_row.values[1].value == meta_row.values[2].value


def test_15_pareto_frontier_calculation():
    """Verify 2D Pareto non-domination detection."""
    # Objective X: recall@10 (maximize), Objective Y: latency (minimize)
    # Exp 1: Recall 0.88, Latency 150ms (Pareto optimal)
    # Exp 2: Recall 0.82, Latency 30ms  (Pareto optimal)
    # Exp 3: Recall 0.75, Latency 80ms  (Dominated by Exp 2: worse recall and worse latency)
    exp1 = DummyExperiment(1, title="Exp 1", results={"recall@10": 0.88, "latency_ms": 150.0})
    exp2 = DummyExperiment(2, title="Exp 2", results={"recall@10": 0.82, "latency_ms": 30.0})
    exp3 = DummyExperiment(3, title="Exp 3", results={"recall@10": 0.75, "latency_ms": 80.0})

    obj_x = ParetoObjectiveConfig(metric="recall@10", direction=ParetoObjectiveDirection.MAXIMIZE)
    obj_y = ParetoObjectiveConfig(metric="latency", direction=ParetoObjectiveDirection.MINIMIZE)

    pareto = compute_pareto_frontier([exp1, exp2, exp3], obj_x, obj_y)
    assert set(pareto.pareto_optimal_experiment_ids) == {1, 2}
    assert 3 not in pareto.pareto_optimal_experiment_ids

    point3 = next(p for p in pareto.points if p.experiment_id == 3)
    assert point3.is_pareto_optimal is False
    assert 2 in point3.dominated_by


def test_16_pareto_ties():
    """Verify identical objective points do not dominate each other; both remain Pareto-optimal."""
    exp1 = DummyExperiment(1, title="Exp 1", results={"recall@10": 0.85, "latency_ms": 50.0})
    exp2 = DummyExperiment(2, title="Exp 2", results={"recall@10": 0.85, "latency_ms": 50.0})

    obj_x = ParetoObjectiveConfig(metric="recall@10", direction=ParetoObjectiveDirection.MAXIMIZE)
    obj_y = ParetoObjectiveConfig(metric="latency", direction=ParetoObjectiveDirection.MINIMIZE)

    pareto = compute_pareto_frontier([exp1, exp2], obj_x, obj_y)
    assert set(pareto.pareto_optimal_experiment_ids) == {1, 2}
    point1 = next(p for p in pareto.points if p.experiment_id == 1)
    assert point1.dominated_by == []


def test_17_pareto_exclusions_missing_values_and_units():
    """Verify missing values or missing unit metadata exclude runs from Pareto analysis."""
    exp1 = DummyExperiment(1, title="Exp 1", results={"recall@10": 0.85, "latency_ms": 50.0})
    exp2 = DummyExperiment(2, title="Exp 2", results={"recall@10": 0.80})  # Missing latency
    exp3 = DummyExperiment(3, title="Exp 3", results={"recall@10": 0.78, "latency": 0.05})  # Missing unit metadata

    obj_x = ParetoObjectiveConfig(metric="recall@10", direction=ParetoObjectiveDirection.MAXIMIZE)
    obj_y = ParetoObjectiveConfig(metric="latency", direction=ParetoObjectiveDirection.MINIMIZE)

    pareto = compute_pareto_frontier([exp1, exp2, exp3], obj_x, obj_y)
    assert pareto.pareto_optimal_experiment_ids == [1]
    assert len(pareto.excluded_experiments) == 2
    excluded_ids = {e.experiment_id for e in pareto.excluded_experiments}
    assert excluded_ids == {2, 3}


def test_18_pareto_duplicate_canonical_objective_rejection():
    """Verify supplying duplicate canonical objectives (latency_ms and latency_s) raises ValueError."""
    exp1 = DummyExperiment(1, results={"latency_ms": 50.0, "latency_s": 0.05})
    exp2 = DummyExperiment(2, results={"latency_ms": 60.0, "latency_s": 0.06})

    obj_x = ParetoObjectiveConfig(metric="latency_ms")
    obj_y = ParetoObjectiveConfig(metric="latency_s")

    with pytest.raises(ValueError, match="Pareto analysis requires two distinct metrics"):
        compute_pareto_frontier([exp1, exp2], obj_x, obj_y)


def test_19_hypothesis_verdict_consensus():
    """Verify deterministic mapping to supported, contradicted, mixed, and inconclusive states."""
    # Plan 1, Hypothesis H1: Supported + Supported -> supported
    e1 = DummyExperiment(1, research_plan_id=1, hypothesis_id="H1", findings={"hypothesis_verdict": "supported"})
    e2 = DummyExperiment(2, research_plan_id=1, hypothesis_id="H1", findings={"hypothesis_verdict": "supported"})

    # Plan 1, Hypothesis H2: Refuted + Refuted -> contradicted
    e3 = DummyExperiment(3, research_plan_id=1, hypothesis_id="H2", findings={"hypothesis_verdict": "refuted"})

    # Plan 2, Hypothesis H1: Supported + Refuted -> mixed
    e4 = DummyExperiment(4, research_plan_id=2, hypothesis_id="H1", findings={"hypothesis_verdict": "supported"})
    e5 = DummyExperiment(5, research_plan_id=2, hypothesis_id="H1", findings={"hypothesis_verdict": "refuted"})

    # Plan 3, Hypothesis H3: Inconclusive -> inconclusive
    e6 = DummyExperiment(6, research_plan_id=3, hypothesis_id="H3", findings={"hypothesis_verdict": "inconclusive"})

    # Unassigned
    e7 = DummyExperiment(7, hypothesis_id=None)

    consensus, manual_ids, unassigned = compute_hypothesis_consensus([e1, e2, e3, e4, e5, e6, e7])
    assert unassigned == [7]
    assert len(consensus) == 4

    h1_p1 = next(h for h in consensus if h.research_plan_id == 1 and h.hypothesis_id == "H1")
    assert h1_p1.consensus == HypothesisConsensusState.SUPPORTED
    assert h1_p1.supporting_count == 2

    h2_p1 = next(h for h in consensus if h.research_plan_id == 1 and h.hypothesis_id == "H2")
    assert h2_p1.consensus == HypothesisConsensusState.CONTRADICTED

    h1_p2 = next(h for h in consensus if h.research_plan_id == 2 and h.hypothesis_id == "H1")
    assert h1_p2.consensus == HypothesisConsensusState.MIXED

    h3_p3 = next(h for h in consensus if h.research_plan_id == 3 and h.hypothesis_id == "H3")
    assert h3_p3.consensus == HypothesisConsensusState.INCONCLUSIVE


def test_20_manual_hypothesis_isolation():
    """Verify manual experiments without a research plan are isolated in manual_hypothesis_experiment_ids."""
    m1 = DummyExperiment(10, research_plan_id=None, hypothesis_id="H1", findings={"hypothesis_verdict": "supported"})
    m2 = DummyExperiment(11, research_plan_id=None, hypothesis_id="H1", findings={"hypothesis_verdict": "refuted"})
    plan_exp = DummyExperiment(12, research_plan_id=1, hypothesis_id="H1", findings={"hypothesis_verdict": "supported"})

    consensus, manual_ids, unassigned = compute_hypothesis_consensus([m1, m2, plan_exp])
    assert set(manual_ids) == {10, 11}
    assert len(consensus) == 1
    assert consensus[0].research_plan_id == 1
    assert consensus[0].contributing_experiment_ids == [12]


def test_21_markdown_export_formatting():
    """Verify Markdown report contains configuration divergence, metrics matrix, Pareto, and consensus."""
    e1 = DummyExperiment(1, research_plan_id=1, hypothesis_id="H1", parameters={"top_k": 5}, results={"recall@10": 0.85})
    e2 = DummyExperiment(2, research_plan_id=1, hypothesis_id="H1", parameters={"top_k": 10}, results={"recall@10": 0.90})

    config_rows = build_configuration_matrix([e1, e2])
    metric_rows = build_metrics_matrix([e1, e2], baseline_id=1)
    consensus, manual_ids, unassigned = compute_hypothesis_consensus([e1, e2])

    md = generate_markdown_report([e1, e2], baseline_id=1, config_rows=config_rows, metric_rows=metric_rows, pareto=None, consensus=consensus, manual_hyp_ids=manual_ids, unassigned_ids=unassigned)
    assert "# Experiment Comparison Report" in md
    assert "Configuration Divergence" in md
    assert "Quantitative Evaluation Metrics" in md
    assert "Hypothesis Verdict Consensus" in md


# ============================================================================
# Integration & API Tests (Tests 22 to 26)
# ============================================================================

@pytest.fixture
def comparison_project(db_session):
    p = Project(title="M15 Comparison Project", description="Testing multi-experiment comparison")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture
def comparison_experiments(db_session, comparison_project):
    e1 = Experiment(
        project_id=comparison_project.id,
        title="BM25 Baseline",
        methodology="Full-text keyword search",
        status=ExperimentStatus.COMPLETED.value,
        priority=ExperimentPriority.MEDIUM.value,
        parameters={"retriever": "bm25", "top_k": 10},
        variables={"chunk_size": 1000},
        results={"Recall@10": 0.70, "latency_ms": 15.0},
        findings={"summary": "Fast baseline", "hypothesis_verdict": "inconclusive"},
    )
    e2 = Experiment(
        project_id=comparison_project.id,
        title="Dense Vector",
        methodology="Cosine similarity over all-MiniLM-L6-v2",
        status=ExperimentStatus.COMPLETED.value,
        priority=ExperimentPriority.HIGH.value,
        parameters={"retriever": "dense", "top_k": 10},
        variables={"chunk_size": 1000},
        results={"Recall@10": 0.80, "latency_ms": 35.0},
        findings={"summary": "Better recall than baseline", "hypothesis_verdict": "supported"},
    )
    e3 = Experiment(
        project_id=comparison_project.id,
        title="Hybrid + Cross-Encoder Rerank",
        methodology="RRF followed by cross-encoder",
        status=ExperimentStatus.COMPLETED.value,
        priority=ExperimentPriority.HIGH.value,
        parameters={"retriever": "hybrid_rerank", "top_k": 10},
        variables={"chunk_size": 500},
        results={"Recall@10": 0.89, "latency_ms": 180.0},
        findings={"summary": "Highest recall but highest latency", "hypothesis_verdict": "supported"},
    )
    e4 = Experiment(
        project_id=comparison_project.id,
        title="Suboptimal Large Window",
        methodology="Blind 2000 char window",
        status=ExperimentStatus.COMPLETED.value,
        priority=ExperimentPriority.LOW.value,
        parameters={"retriever": "dense", "top_k": 10},
        variables={"chunk_size": 2000},
        results={"Recall@10": 0.65, "latency_ms": 50.0},
        findings={"summary": "Dominated run with poor recall and higher latency"},
    )
    db_session.add_all([e1, e2, e3, e4])
    db_session.commit()
    db_session.refresh(e1)
    db_session.refresh(e2)
    db_session.refresh(e3)
    db_session.refresh(e4)
    return [e1, e2, e3, e4]


def test_22_compare_experiments_api_happy_path(db_session, comparison_project, comparison_experiments):
    """Verify end-to-end comparison service returns valid response model with configurations and deltas."""
    service = ExperimentComparisonService(db_session)
    e1, e2, e3, e4 = comparison_experiments

    req = ExperimentComparisonRequest(
        experiment_ids=[e1.id, e2.id, e3.id, e4.id],
        baseline_experiment_id=e1.id,
        pareto_objectives=(
            ParetoObjectiveConfig(metric="recall@10", direction=ParetoObjectiveDirection.MAXIMIZE),
            ParetoObjectiveConfig(metric="latency_ms", direction=ParetoObjectiveDirection.MINIMIZE),
        ),
    )

    resp = service.compare(comparison_project.id, req)
    assert resp.project_id == comparison_project.id
    assert resp.experiments_compared == 4
    assert resp.baseline_experiment_id == e1.id
    assert len(resp.configuration_matrix) > 0
    assert len(resp.metrics_matrix) > 0

    # Pareto: e1, e2, e3 form the frontier; e4 is strictly dominated by e1 and e2
    assert resp.pareto_analysis is not None
    assert set(resp.pareto_analysis.pareto_optimal_experiment_ids) == {e1.id, e2.id, e3.id}
    assert e4.id not in resp.pareto_analysis.pareto_optimal_experiment_ids


def test_23_validation_responsibilities_422_vs_400_vs_404(db_session, comparison_project, comparison_experiments):
    """Verify distinct error status responsibilities for schema, business rules, and 404s."""
    service = ExperimentComparisonService(db_session)
    e1, e2, *rest = comparison_experiments

    # 1. Duplicate IDs in request payload -> Pydantic validator ValueError (HTTP 422)
    with pytest.raises(ValueError, match="Duplicate experiment IDs"):
        ExperimentComparisonRequest(experiment_ids=[e1.id, e1.id])

    # 2. Baseline experiment not in experiment_ids -> Service ValueError (HTTP 400)
    req_bad_baseline = ExperimentComparisonRequest(
        experiment_ids=[e1.id, e2.id],
        baseline_experiment_id=9999,
    )
    with pytest.raises(ValueError, match="Baseline experiment 9999 must be one of the compared experiments"):
        service.compare(comparison_project.id, req_bad_baseline)

    # 3. Duplicate canonical Pareto objectives -> Service ValueError (HTTP 400)
    req_dup_pareto = ExperimentComparisonRequest(
        experiment_ids=[e1.id, e2.id],
        pareto_objectives=(
            ParetoObjectiveConfig(metric="latency_ms"),
            ParetoObjectiveConfig(metric="latency_s"),
        ),
    )
    with pytest.raises(ValueError, match="Pareto analysis requires two distinct metrics"):
        service.compare(comparison_project.id, req_dup_pareto)

    # 4. Nonexistent experiment ID -> FileNotFoundError (HTTP 404)
    req_not_found = ExperimentComparisonRequest(experiment_ids=[e1.id, 99999])
    with pytest.raises(FileNotFoundError, match="Experiment 99999 not found"):
        service.compare(comparison_project.id, req_not_found)

    # 5. Nonexistent project ID -> FileNotFoundError (HTTP 404)
    with pytest.raises(FileNotFoundError, match="Project 99999 not found"):
        service.compare(99999, ExperimentComparisonRequest(experiment_ids=[e1.id, e2.id]))


def test_24_default_baseline_assignment(db_session, comparison_project, comparison_experiments):
    """Verify that omitting baseline_experiment_id defaults to the first experiment ID."""
    service = ExperimentComparisonService(db_session)
    e1, e2, *rest = comparison_experiments

    req = ExperimentComparisonRequest(experiment_ids=[e2.id, e1.id])  # e2 is first
    resp = service.compare(comparison_project.id, req)
    assert resp.baseline_experiment_id == e2.id


def test_25_available_metrics_discovery_api(db_session, comparison_project, comparison_experiments):
    """Verify available metrics discovery returns deduplicated metrics with distinct experiment counts."""
    service = ExperimentComparisonService(db_session)
    metrics = service.get_available_metrics(comparison_project.id)
    metric_names = {m.metric_name for m in metrics}
    assert "recall@10" in metric_names
    assert "latency" in metric_names

    latency_item = next(m for m in metrics if m.metric_name == "latency")
    assert latency_item.experiment_count == 4
    assert latency_item.direction == MetricDirection.LOWER_IS_BETTER
    assert latency_item.canonical_unit == "ms"


def test_26_resilient_llm_synthesis_failure_and_agent_tool(db_session, comparison_project, comparison_experiments):
    """Verify resilient LLM error containment and CompareExperimentsTool execution."""
    e1, e2, *rest = comparison_experiments

    # 1. Resilient synthesis failure handling
    mock_llm = MagicMock()
    mock_llm.get_model_name.return_value = "mock_model"
    mock_llm.generate.side_effect = RuntimeError("Ollama connection timed out")

    service = ExperimentComparisonService(db_session, llm_service=mock_llm)
    req = ExperimentComparisonRequest(
        experiment_ids=[e1.id, e2.id],
        include_synthesis=True,
    )
    resp = service.compare(comparison_project.id, req)
    assert resp.synthesis is None
    assert resp.synthesis_status == "failed"
    assert "Ollama connection timed out" in (resp.synthesis_error or "")
    assert len(resp.metrics_matrix) > 0  # Deterministic matrix still completely preserved!

    # 2. CompareExperimentsTool execution
    tool = CompareExperimentsTool()
    context = ToolContext(db=db_session, project_id=comparison_project.id)

    # Tool happy path
    tool_res = tool.run(context=context, experiment_ids=[e1.id, e2.id])
    assert tool_res.success is True
    assert "Experiment Comparison Report" in tool_res.result_summary
    assert tool_res.data is not None

    # Tool limit rejection: >10 experiments
    tool_overlimit_res = tool.run(context=context, experiment_ids=list(range(1, 13)))
    assert tool_overlimit_res.success is False
    assert "allows at most 10 experiments" in tool_overlimit_res.result_summary


if __name__ == "__main__":
    print("=" * 60)
    print("Running Milestone 15 Test Suite (26 tests)...")
    print("=" * 60)

    # 1. Run Unit Tests (1-21)
    unit_tests = [
        test_1_metric_canonicalization_and_aliases,
        test_2_semantic_metric_distinction,
        test_3_metric_identity_and_unit_separation,
        test_4_unit_normalization_decimal_vs_binary,
        test_5_incompatible_unit_handling_metric_row,
        test_6_strict_numeric_validation_is_valid_numeric,
        test_7_directional_delta_and_status_calculation,
        test_8_unknown_direction_checked_first,
        test_9_missing_unit_metadata_policy,
        test_10_parameterized_tolerance,
        test_11_zero_baseline_safe_handling,
        test_12_missing_metric_handling,
        test_13_is_best_with_ties_and_missing,
        test_14_configuration_deep_equality,
        test_15_pareto_frontier_calculation,
        test_16_pareto_ties,
        test_17_pareto_exclusions_missing_values_and_units,
        test_18_pareto_duplicate_canonical_objective_rejection,
        test_19_hypothesis_verdict_consensus,
        test_20_manual_hypothesis_isolation,
        test_21_markdown_export_formatting,
    ]

    for ut in unit_tests:
        ut()
        print(f"  ✓ {ut.__name__}")

    # 2. Run Service / Integration Tests (22-26) with Mock Repositories
    mock_proj = Project(id=1, title="Comparison Project", description="Test Proj")
    mock_e1 = Experiment(
        id=101, project_id=1, title="BM25 Baseline", methodology="BM25",
        status=ExperimentStatus.COMPLETED.value, priority=ExperimentPriority.MEDIUM.value,
        parameters={"retriever": "bm25", "top_k": 10}, variables={"chunk_size": 1000},
        results={"Recall@10": 0.70, "latency_ms": 15.0},
        findings={"summary": "Fast baseline", "hypothesis_verdict": "inconclusive"},
    )
    mock_e2 = Experiment(
        id=102, project_id=1, title="Dense Vector", methodology="Dense",
        status=ExperimentStatus.COMPLETED.value, priority=ExperimentPriority.HIGH.value,
        parameters={"retriever": "dense", "top_k": 10}, variables={"chunk_size": 1000},
        results={"Recall@10": 0.80, "latency_ms": 35.0},
        findings={"summary": "Better recall than baseline", "hypothesis_verdict": "supported"},
    )
    mock_e3 = Experiment(
        id=103, project_id=1, title="Hybrid + Cross-Encoder Rerank", methodology="Hybrid",
        status=ExperimentStatus.COMPLETED.value, priority=ExperimentPriority.HIGH.value,
        parameters={"retriever": "hybrid_rerank", "top_k": 10}, variables={"chunk_size": 500},
        results={"Recall@10": 0.89, "latency_ms": 180.0},
        findings={"summary": "Highest recall but highest latency", "hypothesis_verdict": "supported"},
    )
    mock_e4 = Experiment(
        id=104, project_id=1, title="Suboptimal Large Window", methodology="Window",
        status=ExperimentStatus.COMPLETED.value, priority=ExperimentPriority.LOW.value,
        parameters={"retriever": "dense", "top_k": 10}, variables={"chunk_size": 2000},
        results={"Recall@10": 0.65, "latency_ms": 50.0},
        findings={"summary": "Dominated run with poor recall and higher latency"},
    )
    comparison_exps = [mock_e1, mock_e2, mock_e3, mock_e4]
    exp_dict = {e.id: e for e in comparison_exps}

    class MockSession:
        def __init__(self):
            pass

    mock_db = MockSession()

    # Monkeypatch ExperimentComparisonService to wire mock repos if db is MockSession
    orig_init = ExperimentComparisonService.__init__

    def patched_init(self, db, llm_service=None):
        orig_init(self, db, llm_service)
        if isinstance(db, MockSession):
            self.project_repo = MagicMock()
            self.project_repo.get_by_id.side_effect = lambda p_id: mock_proj if p_id == 1 else None
            self.exp_repo = MagicMock()
            self.exp_repo.get_by_id.side_effect = lambda e_id, **kwargs: exp_dict.get(e_id)
            self.exp_repo.list_by_project.return_value = comparison_exps

    ExperimentComparisonService.__init__ = patched_init

    integration_tests = [
        test_22_compare_experiments_api_happy_path,
        test_23_validation_responsibilities_422_vs_400_vs_404,
        test_24_default_baseline_assignment,
        test_25_available_metrics_discovery_api,
        test_26_resilient_llm_synthesis_failure_and_agent_tool,
    ]

    for it in integration_tests:
        it(mock_db, mock_proj, comparison_exps)
        print(f"  ✓ {it.__name__}")

    print("=" * 60)
    print("ALL 26 TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
