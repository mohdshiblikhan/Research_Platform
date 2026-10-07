import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.rag import (
    AskRequest,
    AskResponse,
    Citation,
    CitationVerification,
    SourcePassage,
)
from app.services.llm_service_factory import get_llm_service
from app.services.search_service import SearchService
from app.prompts.rag_prompts import RAG_SYSTEM_PROMPT, build_rag_user_prompt, format_evidence_block

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, db: Session):
        self.db = db
        self.search_service = SearchService(db)
        self.llm_service = get_llm_service()

    def ask(self, project_id: int, request: AskRequest) -> AskResponse:
        start_total = time.perf_counter()

        # 1. Retrieve Evidence
        logger.info(f"Retrieving evidence for project {project_id}, question: {request.question[:50]}...")
        
        # Determine effective top_k
        top_k = request.top_k if request.top_k else settings.rag_top_k
        
        search_response = self.search_service.search(
            project_id=project_id,
            query=request.question,
            mode=request.search_mode,
            rerank=request.rerank,
            document_id=request.document_id,
            limit=top_k,
            offset=0,
        )
        retrieval_time_ms = search_response.query_time_ms
        
        # Handle zero results
        if not search_response.results:
            empty_cv = CitationVerification(total=0, valid=0, invalid=0)
            return AskResponse(
                question=request.question,
                project_id=project_id,
                evidence_analysis=None,
                answer="I could not find relevant evidence in the uploaded documents to answer this question.",
                citations=[],
                sources=[],
                search_mode=request.search_mode,
                reranked=request.rerank,
                top_k=top_k,
                retrieval_time_ms=retrieval_time_ms,
                generation_time_ms=0.0,
                total_time_ms=round((time.perf_counter() - start_total) * 1000, 2),
                llm_model=self.llm_service.get_model_name(),
                citation_verification=empty_cv,
                confidence="low",
                has_sufficient_evidence=False
            )

        # 2. Build Evidence Context
        evidence_blocks = []
        sources = []
        
        for i, item in enumerate(search_response.results, start=1):
            block = format_evidence_block(
                index=i,
                filename=item.document_filename,
                page_start=item.page_start,
                page_end=item.page_end,
                content=item.content
            )
            evidence_blocks.append(block)
            
            # Determine best relevance score
            rel_score = item.rerank_score
            if rel_score is None:
                rel_score = item.rrf_score if item.rrf_score is not None else item.rank
            
            source = SourcePassage(
                index=i,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_filename=item.document_filename,
                page_start=item.page_start,
                page_end=item.page_end,
                content=item.content,
                relevance_score=rel_score
            )
            sources.append(source)

        user_prompt = build_rag_user_prompt(request.question, evidence_blocks)

        # 3. Call LLM
        logger.info(f"Generating answer using {self.llm_service.get_model_name()}")
        start_gen = time.perf_counter()
        
        llm_response = self.llm_service.generate(
            system_prompt=RAG_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_mode=True
        )
        
        generation_time_ms = round((time.perf_counter() - start_gen) * 1000, 2)

        # 4. Parse LLM JSON
        try:
            parsed_response = json.loads(llm_response.content)
            answer_text = parsed_response.get("answer", "")
            evidence_analysis = parsed_response.get("evidence_analysis")
            raw_citations = parsed_response.get("citations", [])
            confidence = parsed_response.get("confidence", "unknown")
            has_sufficient = parsed_response.get("has_sufficient_evidence", True)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}. Raw content: {llm_response.content}")
            answer_text = "Error: Failed to generate a structured response."
            evidence_analysis = None
            raw_citations = []
            confidence = "low"
            has_sufficient = False

        # 5. Verify and Build Citations
        citations = []
        valid_cites = 0
        invalid_cites = 0
        
        for cite in raw_citations:
            claim = cite.get("claim", "")
            source_indices = cite.get("source_indices", [])
            quote = cite.get("quote", "")
            
            if not isinstance(source_indices, list):
                source_indices = [source_indices] if isinstance(source_indices, int) else []
                
            for idx in source_indices:
                if 1 <= idx <= len(sources):
                    source = sources[idx - 1]
                    citations.append(Citation(
                        source_index=idx,
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                        document_filename=source.document_filename,
                        page_start=source.page_start,
                        page_end=source.page_end,
                        cited_text=quote or claim
                    ))
                    valid_cites += 1
                else:
                    invalid_cites += 1
                    logger.warning(f"LLM hallucinated citation index: {idx}")

        cv = CitationVerification(
            total=valid_cites + invalid_cites,
            valid=valid_cites,
            invalid=invalid_cites
        )

        total_time_ms = round((time.perf_counter() - start_total) * 1000, 2)

        return AskResponse(
            question=request.question,
            project_id=project_id,
            evidence_analysis=evidence_analysis,
            answer=answer_text,
            citations=citations,
            sources=sources,
            search_mode=request.search_mode,
            reranked=request.rerank,
            top_k=top_k,
            retrieval_time_ms=retrieval_time_ms,
            generation_time_ms=generation_time_ms,
            total_time_ms=total_time_ms,
            llm_model=llm_response.model,
            citation_verification=cv,
            confidence=confidence,
            has_sufficient_evidence=has_sufficient
        )
