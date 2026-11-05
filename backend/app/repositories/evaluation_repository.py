from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation import (
    EvaluationDataset,
    EvaluationDatasetItem,
    EvaluationItemResult,
    EvaluationRun,
)


class EvaluationRepository:
    """Repository handling database operations for Evaluation entities."""

    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # EvaluationDataset CRUD
    # =========================================================================

    def create_dataset(self, dataset: EvaluationDataset) -> EvaluationDataset:
        """Persist a new evaluation dataset."""
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def get_dataset(
        self, dataset_id: int, project_id: Optional[int] = None
    ) -> Optional[EvaluationDataset]:
        """Fetch a single dataset by ID, optionally validating project ownership."""
        stmt = select(EvaluationDataset).where(EvaluationDataset.id == dataset_id)
        if project_id is not None:
            stmt = stmt.where(EvaluationDataset.project_id == project_id)
        return self.db.execute(stmt).scalars().first()

    def list_datasets(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> List[EvaluationDataset]:
        """List evaluation datasets for a project ordered by creation date descending."""
        stmt = (
            select(EvaluationDataset)
            .where(EvaluationDataset.project_id == project_id)
            .order_by(EvaluationDataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def delete_dataset(self, dataset: EvaluationDataset) -> None:
        """Delete an evaluation dataset. Historical evaluation runs and results are preserved via ON DELETE SET NULL."""
        self.db.delete(dataset)
        self.db.commit()

    # =========================================================================
    # EvaluationDatasetItem CRUD
    # =========================================================================

    def create_item(self, item: EvaluationDatasetItem) -> EvaluationDatasetItem:
        """Persist a single evaluation dataset item."""
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def create_items_bulk(
        self, items: List[EvaluationDatasetItem]
    ) -> List[EvaluationDatasetItem]:
        """Bulk persist evaluation dataset items."""
        if not items:
            return []
        self.db.add_all(items)
        self.db.commit()
        for item in items:
            self.db.refresh(item)
        return items

    def get_item(
        self, item_id: int, dataset_id: Optional[int] = None
    ) -> Optional[EvaluationDatasetItem]:
        """Fetch a single dataset item by ID, optionally validating dataset ownership."""
        stmt = select(EvaluationDatasetItem).where(EvaluationDatasetItem.id == item_id)
        if dataset_id is not None:
            stmt = stmt.where(EvaluationDatasetItem.dataset_id == dataset_id)
        return self.db.execute(stmt).scalars().first()

    def list_items(
        self,
        dataset_id: int,
        validated_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EvaluationDatasetItem]:
        """List items in a dataset with optional validated-only filtering and pagination."""
        stmt = select(EvaluationDatasetItem).where(
            EvaluationDatasetItem.dataset_id == dataset_id
        )
        if validated_only:
            stmt = stmt.where(EvaluationDatasetItem.is_validated.is_(True))
        stmt = stmt.order_by(EvaluationDatasetItem.id.asc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def patch_item(
        self, item: EvaluationDatasetItem, update_data: Dict[str, Any]
    ) -> EvaluationDatasetItem:
        """Update attributes of a dataset item."""
        for key, value in update_data.items():
            if hasattr(item, key):
                setattr(item, key, value)
        item.updated_at = datetime.now(timezone.utc)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete_item(self, item: EvaluationDatasetItem) -> None:
        """Delete a dataset item. Historical evaluation results are preserved via ON DELETE SET NULL."""
        self.db.delete(item)
        self.db.commit()

    # =========================================================================
    # EvaluationRun CRUD
    # =========================================================================

    def create_run(self, run: EvaluationRun) -> EvaluationRun:
        """Persist a new evaluation run (defaults to status='running')."""
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(
        self, run_id: int, project_id: Optional[int] = None
    ) -> Optional[EvaluationRun]:
        """Fetch a single evaluation run by ID, optionally validating project ownership."""
        stmt = select(EvaluationRun).where(EvaluationRun.id == run_id)
        if project_id is not None:
            stmt = stmt.where(EvaluationRun.project_id == project_id)
        return self.db.execute(stmt).scalars().first()

    def list_runs(
        self,
        project_id: int,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[EvaluationRun]:
        """List evaluation runs for a project with optional type and status filtering."""
        stmt = select(EvaluationRun).where(EvaluationRun.project_id == project_id)
        if run_type:
            stmt = stmt.where(EvaluationRun.run_type == run_type)
        if status:
            stmt = stmt.where(EvaluationRun.status == status)
        stmt = (
            stmt.order_by(EvaluationRun.created_at.desc()).limit(limit).offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_run(self, run: EvaluationRun) -> EvaluationRun:
        """Update and commit changes to an evaluation run."""
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finalize_run(
        self,
        run: EvaluationRun,
        status: str,
        summary_metrics: Dict[str, Any],
        duration_ms: int,
        error_message: Optional[str] = None,
    ) -> EvaluationRun:
        """Finalize an evaluation run with status, summary metrics, and timing."""
        run.status = status
        run.summary_metrics = summary_metrics
        run.duration_ms = duration_ms
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    # =========================================================================
    # EvaluationItemResult CRUD
    # =========================================================================

    def create_item_results_bulk(
        self, results: List[EvaluationItemResult]
    ) -> List[EvaluationItemResult]:
        """Bulk persist evaluation item results."""
        if not results:
            return []
        self.db.add_all(results)
        self.db.commit()
        for res in results:
            self.db.refresh(res)
        return results

    def list_item_results(
        self, run_id: int, limit: int = 100, offset: int = 0
    ) -> List[EvaluationItemResult]:
        """List per-item evaluation results for a run ordered by ID ascending."""
        stmt = (
            select(EvaluationItemResult)
            .where(EvaluationItemResult.run_id == run_id)
            .order_by(EvaluationItemResult.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())
