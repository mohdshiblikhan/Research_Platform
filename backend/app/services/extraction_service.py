import json
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.schemas.extraction import ExtractionCreate
from app.services.search_service import SearchService
from app.services.llm_service_factory import get_llm_service
from app.models.extraction import DocumentExtraction

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, db: Session):
        self.db = db
        self.chunk_repo = ChunkRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.extraction_repo = ExtractionRepository(db)
        self.search_service = SearchService(db)
        self.llm_service = get_llm_service()

    def _gather_context(self, document: Document) -> str:
        """Gather context from the document using edge chunks and semantic search."""
        chunks = self.chunk_repo.list_by_document(document.id)
        if not chunks:
            return ""

        # Top edge chunks (usually Abstract/Intro)
        edge_chunks = chunks[:settings.extraction_edge_chunks]
        
        # Bottom edge chunks (usually Conclusion/Limitations)
        if len(chunks) > settings.extraction_edge_chunks:
            edge_chunks.extend(chunks[-settings.extraction_edge_chunks:])

        edge_chunk_ids = {c.id for c in edge_chunks}

        # Semantic search for methodology and datasets
        search_query = "research problem methodology datasets evaluation metrics results limitations baselines"
        try:
            # We use keyword search or semantic if hybrid is too slow, but hybrid gives the best of both
            search_response = self.search_service.search(
                project_id=document.project_id,
                query=search_query,
                mode="hybrid",
                document_id=document.id,
                limit=settings.extraction_search_limit,
            )
            semantic_chunks = search_response.results
        except Exception as e:
            logger.error(f"Error during semantic search for context: {e}")
            semantic_chunks = []

        context_parts = []
        # Add edge chunks
        for c in edge_chunks:
            context_parts.append(f"--- Chunk {c.chunk_index} ---\n{c.content}")

        # Add semantic chunks not already in edge_chunks
        for res in semantic_chunks:
            if res.chunk_id not in edge_chunk_ids:
                context_parts.append(f"--- Chunk {res.chunk_index} ---\n{res.content}")
                edge_chunk_ids.add(res.chunk_id)

        return "\n\n".join(context_parts)

    def extract(self, project_id: int, document_id: int) -> DocumentExtraction:
        document = self.doc_repo.get_by_id(document_id)
        if not document or document.project_id != project_id:
            raise FileNotFoundError("Document not found in project.")

        context = self._gather_context(document)
        if not context:
            raise ValueError("No content found for extraction.")

        system_prompt = (
            "You are an expert AI research assistant. Your task is to extract structured information "
            "from a research paper based on the provided text chunks.\n"
            "Return a JSON object with the following keys. If a field is not found in the text, leave it as null.\n"
            "- research_problem: The main problem addressed.\n"
            "- methodology: The approach used.\n"
            "- models_used: Machine learning models or architectures.\n"
            "- datasets: Datasets for training or evaluation.\n"
            "- evaluation_metrics: Metrics used.\n"
            "- results: Main findings.\n"
            "- limitations: Mentioned limitations.\n"
            "- baselines: Baselines compared against.\n"
            "Only output the valid JSON object. Do not output any markdown formatting or extra text."
        )

        user_prompt = f"Extract the requested fields from the following document chunks:\n\n{context}"

        llm_response = self.llm_service.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            json_mode=True
        )

        # Parse JSON
        try:
            raw_data = json.loads(llm_response.content)
            # Remove keys that aren't in the schema to avoid Pydantic validation errors on extra fields if strict
            valid_keys = ExtractionCreate.model_fields.keys()
            filtered_data = {k: v for k, v in raw_data.items() if k in valid_keys}
            extraction_in = ExtractionCreate(**filtered_data)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON output: {e}\nRaw output: {llm_response.content}")
            raise ValueError("Failed to parse structured output from LLM.")

        # Upsert
        extraction = self.extraction_repo.upsert(
            document_id=document_id,
            extraction_in=extraction_in,
            raw_llm_output=raw_data
        )

        return extraction

    def get_extraction(self, project_id: int, document_id: int) -> DocumentExtraction:
        document = self.doc_repo.get_by_id(document_id)
        if not document or document.project_id != project_id:
            raise FileNotFoundError("Document not found in project.")
            
        extraction = self.extraction_repo.get_by_document_id(document_id)
        if not extraction:
            raise FileNotFoundError("Extraction not found for this document.")
            
        return extraction
