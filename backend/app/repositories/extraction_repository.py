from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction import DocumentExtraction
from app.schemas.extraction import ExtractionCreate


class ExtractionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_document_id(self, document_id: int) -> Optional[DocumentExtraction]:
        """Get the extraction for a specific document."""
        stmt = select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        result = self.db.execute(stmt)
        return result.scalars().first()

    def upsert(
        self, 
        document_id: int, 
        extraction_in: ExtractionCreate, 
        raw_llm_output: Optional[Dict[str, Any]] = None
    ) -> DocumentExtraction:
        """Create or update an extraction for a document."""
        extraction = self.get_by_document_id(document_id)
        
        if extraction:
            # Update existing
            for key, value in extraction_in.model_dump(exclude_unset=True).items():
                setattr(extraction, key, value)
            if raw_llm_output is not None:
                extraction.raw_llm_output = raw_llm_output
        else:
            # Create new
            extraction_data = extraction_in.model_dump()
            extraction_data["document_id"] = document_id
            extraction_data["raw_llm_output"] = raw_llm_output
            extraction = DocumentExtraction(**extraction_data)
            self.db.add(extraction)
            
        self.db.commit()
        self.db.refresh(extraction)
        return extraction
