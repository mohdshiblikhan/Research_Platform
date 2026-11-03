import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


@dataclass
class PageText:
    """Raw text extracted from a single PDF page."""

    page_number: int  # 1-based
    text: str


@dataclass
class ChunkData:
    """Intermediate representation of a chunk before DB insertion."""

    chunk_index: int
    content: str
    page_start: int
    page_end: int
    char_offset_start: int
    char_offset_end: int


class ProcessingService:
    """Orchestrates PDF text extraction and chunking.

    Pipeline:
        1. Validate document exists and is in 'uploaded' status
        2. Set status → 'processing'
        3. Extract text from each PDF page (PyMuPDF)
        4. Clean the extracted text
        5. Chunk the text with recursive boundary-aware splitting (or fixed-size window)
        6. Bulk insert chunks into the database
        7. Set status → 'processed'

    On failure: status → 'failed', chunk inserts rolled back.
    """

    def __init__(self, db: Session):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.project_repo = ProjectRepository(db)
        self.chunk_repo = ChunkRepository(db)

    def process_document(self, project_id: int, document_id: int) -> dict:
        """Extract text from a PDF, chunk it, and store the chunks.

        Returns:
            A dict with document_id, filename, status, page_count, chunk_count.

        Raises:
            FileNotFoundError: If project or document not found.
            ValueError: If document is not in 'uploaded' status.
        """
        # 1. Validate project exists
        project = self.project_repo.get_by_id(project_id)
        if project is None:
            raise FileNotFoundError(f"Project {project_id} not found")

        # 2. Validate document exists and belongs to project
        document = self.doc_repo.get_by_id(document_id)
        if document is None or document.project_id != project_id:
            raise FileNotFoundError(
                f"Document {document_id} not found in project {project_id}"
            )

        # 3. Validate document is in 'uploaded' status
        if document.status != DocumentStatus.UPLOADED.value:
            raise ValueError(
                f"Document {document_id} cannot be processed: "
                f"current status is '{document.status}'. "
                f"Only documents with status 'uploaded' can be processed."
            )

        # 4. Set status → 'processing'
        self.doc_repo.update_status(document, DocumentStatus.PROCESSING.value)

        try:
            # 5. Extract text from PDF
            file_path = Path(document.file_path)
            if not file_path.exists():
                raise FileNotFoundError(
                    f"PDF file not found on disk: {file_path}"
                )

            pages = self._extract_text(file_path)
            logger.info(
                "Extracted text from %d pages of document %d",
                len(pages),
                document_id,
            )

            # 6. Chunk the extracted text
            chunk_data_list = self._chunk_text(
                pages,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            logger.info(
                "Created %d chunks for document %d",
                len(chunk_data_list),
                document_id,
            )

            # 7. Convert to ORM objects and bulk insert
            chunk_objects = [
                Chunk(
                    document_id=document_id,
                    chunk_index=cd.chunk_index,
                    content=cd.content,
                    page_start=cd.page_start,
                    page_end=cd.page_end,
                    char_offset_start=cd.char_offset_start,
                    char_offset_end=cd.char_offset_end,
                    chunk_size=len(cd.content),
                )
                for cd in chunk_data_list
            ]
            self.chunk_repo.bulk_create(chunk_objects)

            # 8. Set status → 'processed' and commit everything atomically
            self.doc_repo.update_status(document, DocumentStatus.PROCESSED.value)
            self.db.commit()

            logger.info(
                "Document %d processed: %d chunks created",
                document_id,
                len(chunk_objects),
            )

            return {
                "document_id": document.id,
                "filename": document.filename,
                "status": document.status,
                "page_count": document.page_count or len(pages),
                "chunk_count": len(chunk_objects),
            }

        except Exception:
            # Roll back any pending changes (chunks, status)
            self.db.rollback()

            # Set status → 'failed' in a fresh transaction
            try:
                self.doc_repo.update_status(document, DocumentStatus.FAILED.value)
                self.db.commit()
            except Exception:
                logger.error(
                    "Failed to set document %d status to 'failed'",
                    document_id,
                    exc_info=True,
                )

            logger.error(
                "Processing failed for document %d", document_id, exc_info=True
            )
            raise

    # ── Private helpers ──────────────────────────────────────────────────

    def _extract_text(self, file_path: Path) -> list[PageText]:
        """Open a PDF and extract cleaned text from each page.

        Returns:
            List of PageText objects, one per page, with 1-based page numbers.
        """
        pages: list[PageText] = []

        with pymupdf.open(str(file_path)) as pdf_doc:
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                raw_text = page.get_text()
                cleaned = self._clean_text(raw_text)

                if cleaned:  # skip blank pages
                    pages.append(
                        PageText(page_number=page_num + 1, text=cleaned)
                    )

        return pages

    def _clean_text(self, raw_text: str) -> str:
        """Normalize extracted PDF text.

        Handles:
        - Strip NUL (0x00) bytes incompatible with PostgreSQL text fields
        - Collapse multiple spaces into one
        - Collapse 3+ newlines into 2 (preserve paragraph breaks)
        - Strip leading/trailing whitespace
        - Rejoin hyphenated words at line breaks (e.g., "com-\\nputer" → "computer")
        """
        text = raw_text

        # Remove null bytes (PostgreSQL VARCHAR/TEXT cannot contain \x00)
        text = text.replace("\x00", "")

        # Rejoin hyphenated words split across lines
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

        # Collapse multiple spaces (but not newlines) into one
        text = re.sub(r"[^\S\n]+", " ", text)

        # Collapse 3+ consecutive newlines into 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    SEPARATORS: list[str] = ["\n\n", "\n", ". ", " ", ""]

    def _chunk_text(
        self,
        pages: list[PageText],
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        """Split page texts into chunks using recursive separator hierarchy.

        Strategy:
            1. Concatenate all page texts, tracking page boundaries.
            2. If configured to 'fixed', use fixed-size sliding window.
            3. Otherwise, recursively split text using separator hierarchy:
               - Paragraph breaks ("\\n\\n")
               - Line breaks ("\\n")
               - Sentence endings (". ")
               - Word boundaries (" ")
               - Character level as last resort ("")
            4. Merge splits up to chunk_size and apply overlap.
            5. Preserve page provenance via char offset tracking.

        Returns:
            List of ChunkData objects ready for DB insertion.
        """
        if not pages:
            return []

        # Build the full document text and track page boundaries.
        # page_boundaries[i] = (start_offset, end_offset, page_number)
        full_text = ""
        page_boundaries: list[tuple[int, int, int]] = []

        for page in pages:
            start = len(full_text)
            full_text += page.text + "\n"  # newline separator between pages
            end = len(full_text)
            page_boundaries.append((start, end, page.page_number))

        # Remove the trailing newline
        full_text = full_text.rstrip("\n")
        # Adjust the last boundary
        if page_boundaries:
            start, _, page_num = page_boundaries[-1]
            page_boundaries[-1] = (start, len(full_text), page_num)

        if not full_text:
            return []

        # If configured for legacy fixed chunking, run legacy window logic
        if getattr(settings, "chunk_method", "recursive") == "fixed":
            return self._fixed_chunk_text(
                full_text=full_text,
                page_boundaries=page_boundaries,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

        # Recursive text splitting
        splits = self._recursive_split(full_text, chunk_size, self.SEPARATORS)
        return self._merge_with_overlap(
            splits=splits,
            full_text=full_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            page_boundaries=page_boundaries,
        )

    def _split_text_with_separator(self, text: str, separator: str) -> list[str]:
        """Split text while keeping the separator with the preceding split."""
        if not separator:
            return list(text)

        splits = re.split(f"({re.escape(separator)})", text)
        parts: list[str] = []
        for i in range(0, len(splits), 2):
            part = splits[i]
            if i + 1 < len(splits):
                part += splits[i + 1]
            if part:
                parts.append(part)
        return parts

    def _recursive_split(
        self, text: str, chunk_size: int, separators: list[str]
    ) -> list[str]:
        """Recursively split text using separator hierarchy."""
        if len(text) <= chunk_size:
            return [text] if text else []

        # Find the first separator present in text
        chosen_sep = None
        for sep in separators:
            if sep and sep in text:
                chosen_sep = sep
                break

        # Fallback to character-level slicing if no non-empty separator matches
        if chosen_sep is None:
            return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

        parts = self._split_text_with_separator(text, chosen_sep)
        remaining_seps = separators[separators.index(chosen_sep) + 1 :]

        result: list[str] = []
        current = ""

        for part in parts:
            if not part:
                continue

            candidate = current + part
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    result.append(current)
                    current = ""

                # If this single part exceeds chunk_size, recursively split it
                if len(part) > chunk_size:
                    if remaining_seps:
                        sub_splits = self._recursive_split(part, chunk_size, remaining_seps)
                        result.extend(sub_splits)
                    else:
                        for i in range(0, len(part), chunk_size):
                            result.append(part[i : i + chunk_size])
                else:
                    current = part

        if current:
            result.append(current)

        return result

    def _merge_with_overlap(
        self,
        splits: list[str],
        full_text: str,
        chunk_size: int,
        chunk_overlap: int,
        page_boundaries: list[tuple[int, int, int]],
    ) -> list[ChunkData]:
        """Convert splits into ChunkData with overlap and page provenance."""
        chunks: list[ChunkData] = []
        current_offset = 0

        for i, split_text in enumerate(splits):
            if not split_text:
                continue

            found = full_text.find(split_text, current_offset)
            if found != -1:
                offset_start = found
            else:
                offset_start = current_offset

            raw_end = offset_start + len(split_text)

            # Apply overlap: prepend tail of previous chunk's text
            if i > 0 and chunk_overlap > 0:
                overlap_start = max(0, offset_start - chunk_overlap)
                if chunks:
                    overlap_start = max(chunks[-1].char_offset_start, overlap_start)
                effective_start = overlap_start
            else:
                effective_start = offset_start

            raw_content = full_text[effective_start:raw_end]
            content = raw_content.rstrip()
            if not content:
                current_offset = raw_end
                continue

            offset_end = effective_start + len(content)

            page_start = self._find_page_at_offset(effective_start, page_boundaries)
            page_end = self._find_page_at_offset(
                max(effective_start, offset_end - 1), page_boundaries
            )

            chunks.append(
                ChunkData(
                    chunk_index=len(chunks),
                    content=content,
                    page_start=page_start,
                    page_end=page_end,
                    char_offset_start=effective_start,
                    char_offset_end=offset_end,
                )
            )
            current_offset = raw_end

        return chunks

    def _fixed_chunk_text(
        self,
        full_text: str,
        page_boundaries: list[tuple[int, int, int]],
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        """Legacy fixed-size chunking with sliding window."""
        step = chunk_size - chunk_overlap
        if step <= 0:
            step = 1  # safety: overlap must be less than chunk_size

        chunks: list[ChunkData] = []
        chunk_index = 0
        offset = 0

        while offset < len(full_text):
            end = min(offset + chunk_size, len(full_text))
            content = full_text[offset:end]

            # Determine which pages this chunk spans
            page_start = self._find_page_at_offset(offset, page_boundaries)
            page_end = self._find_page_at_offset(end - 1, page_boundaries)

            chunks.append(
                ChunkData(
                    chunk_index=chunk_index,
                    content=content,
                    page_start=page_start,
                    page_end=page_end,
                    char_offset_start=offset,
                    char_offset_end=end,
                )
            )

            chunk_index += 1
            offset += step

            if end >= len(full_text):
                break

        return chunks

    def _find_page_at_offset(
        self, offset: int, page_boundaries: list[tuple[int, int, int]]
    ) -> int:
        """Find the page number for a given character offset.

        Args:
            offset: Character offset in the full document text.
            page_boundaries: List of (start, end, page_number) tuples.

        Returns:
            1-based page number.
        """
        for start, end, page_number in page_boundaries:
            if start <= offset < end:
                return page_number

        # If offset is at or past the end, return the last page
        return page_boundaries[-1][2]
