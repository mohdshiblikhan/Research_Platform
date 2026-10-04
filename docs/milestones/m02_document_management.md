# Milestone 2: Document Upload & Management

- **Status**: Completed
- **Version**: `v0.2`
- **Migration**: `959decb82d1f` (*create document table*)
- **Git Commits**:
  - `3209f78` (*feat: add Document model, relationship, upload dir config, and migration*)
  - `b766795` (*feat: add Document schema and implement document upload, metadata retrieval, and deletion endpoints*)
  - `9a35b02` (*test: add integration test suite for document upload and management*)
  - `1c387b6` (*docs: document Milestone 2 implementation, architecture*)

---

### 1. Objective & Problem Solved

#### The Problem
After Milestone 1, a researcher can create a project like *"RAG Hallucination Research"* — but there's no way to attach actual research material to it. The project exists as an empty container. Without documents, every future milestone (text extraction, search, retrieval, RAG) has nothing to operate on.

#### The Solution
Milestone 2 allows users to upload PDF research papers to a project and manage them. The system:
1. Accepts multipart file uploads (PDF only)
2. Validates the file (extension, MIME type, PDF integrity via PyMuPDF)
3. Saves the file to the local filesystem at `data/uploads/{project_id}/{filename}`
4. Extracts the page count as lightweight metadata
5. Stores structured metadata (filename, file_path, file_size, mime_type, page_count, status) in PostgreSQL
6. Supports listing, retrieving, and deleting documents
7. Cascade-deletes documents when their parent project is deleted

This milestone also introduces the **service layer** — a new architectural layer that was intentionally skipped in Milestone 1 because pure CRUD didn't need it. Document upload requires coordinating two side effects (disk I/O + database insert), which justifies the service layer's introduction.

---

### 2. What the API Exposes

All document endpoints are nested under `/api/projects/{project_id}/documents` for URL consistency:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{project_id}/documents` | Upload a PDF file | `201 Created` |
| `GET` | `/api/projects/{project_id}/documents` | List all documents for a project | `200 OK` |
| `GET` | `/api/projects/{project_id}/documents/{document_id}` | Get single document metadata | `200 OK` |
| `DELETE` | `/api/projects/{project_id}/documents/{document_id}` | Delete document + file from disk | `204 No Content` |

**Error responses:**

| Scenario | HTTP Status | Detail |
|:---|:---|:---|
| Project not found | `404 Not Found` | `"Project {id} not found"` |
| Document not found / wrong project | `404 Not Found` | `"Document {id} not found in project {id}"` |
| Non-PDF file uploaded | `400 Bad Request` | `"File type '.txt' is not allowed..."` |
| Duplicate filename in same project | `409 Conflict` | `"A document named 'x.pdf' already exists..."` |

**URL nesting decision**: We considered a flat `/api/documents/{id}` for single-document operations (since document IDs are globally unique). However, keeping all document endpoints consistently nested under their parent project makes the API more predictable and self-documenting. Every document operation explicitly states which project it belongs to.

---

### 3. Architectural Evolution: Introducing the Service Layer

Milestone 1 used a 3-layer architecture: **Endpoint → Repository → Database**. The service layer was intentionally skipped because Project CRUD had no business logic beyond simple SQL operations.

Milestone 2 introduces a 4-layer architecture for documents because the upload workflow requires **multi-resource coordination**:

```
HTTP Request (multipart file)
     │
     ▼
┌───────────────────────────────────────┐
│  API Layer (endpoints/documents.py)    │  Receives UploadFile, translates
│                                        │  service exceptions → HTTP status codes.
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────┐
│  Service Layer (document_service.py)   │  NEW: Orchestrates the upload workflow:
│                                        │  validate → save to disk → extract page
│                                        │  count → insert DB row → cleanup on failure.
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────────┐
│  Repository Layer (document_repository.py) │  Pure DB queries. No file I/O.
└──────────────────┬────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────┐
│  ORM Model Layer (document.py)    │  Declares the `documents` table.
└──────────────────────────────────┘
```

#### Why not just put the file I/O logic in the endpoint?

Putting disk writes, PyMuPDF calls, and error cleanup in a route handler creates a 100-line function that mixes HTTP concerns with business logic. The service layer keeps the endpoint thin (just exception-to-HTTP translation) and makes the upload logic independently testable.

#### Why not put the file I/O in the repository?

The repository's job is **pure database operations**. Mixing disk I/O into the repository would violate its single responsibility and make it impossible to test DB queries without touching the filesystem.

#### The cleanup contract

The service layer guarantees:
- If the DB insert fails after the file was already saved to disk → **the file is cleaned up** (deleted)
- If PyMuPDF can't open the file (invalid PDF) → **the file is cleaned up** and the request is rejected
- If validation fails (wrong extension/MIME type, duplicate filename) → **no file is written** at all

This is why the service exists: it coordinates two side effects (disk + database) and handles partial failures.

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. ORM Model: `backend/app/models/document.py`

```python
class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"

class Document(Base):
    __tablename__ = "documents"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(nullable=False)
    file_path: Mapped[str] = mapped_column(nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=DocumentStatus.UPLOADED.value
    )

    project: Mapped["Project"] = relationship(back_populates="documents")
```

Key design points:

- **`DocumentStatus` inherits from `str, enum.Enum`**: This "str mixin" pattern makes the enum JSON-serializable out of the box. `DocumentStatus.UPLOADED` serializes as `"uploaded"` — no custom encoder needed.
- **`status` stored as `String` (VARCHAR), not Postgres `ENUM`**: PostgreSQL native ENUM types (`CREATE TYPE`) require an `ALTER TYPE ... ADD VALUE` migration to add new values, which is a special DDL statement that cannot run inside a transaction. VARCHAR with Python-side validation is operationally simpler and equally safe.
- **`ForeignKey("projects.id", ondelete="CASCADE")`**: Tells PostgreSQL to automatically delete document rows when their parent project row is deleted. This is the **database-level** cascade — it works even if you bypass the ORM and run raw SQL.
- **`index=True` on `project_id`**: Documents are almost always queried by project. Without this index, `SELECT * FROM documents WHERE project_id = ?` would require a full table scan.
- **`page_count` is nullable**: It's extracted from the PDF at upload time using PyMuPDF. If extraction somehow fails in a future edge case, the document can still exist without this metadata.
- **`TYPE_CHECKING` guard for imports**: `from app.models.project import Project` is inside `if TYPE_CHECKING:` to avoid circular imports at runtime (Project imports Document for the relationship, and Document imports Project). Python's type checker still sees the import for static analysis.

#### B. Updated Project Model: `backend/app/models/project.py`

```python
documents: Mapped[list["Document"]] = relationship(
    back_populates="project", cascade="all, delete-orphan"
)
```

- **`cascade="all, delete-orphan"`**: This is the **ORM-level** cascade. When you call `db.delete(project)` through SQLAlchemy, it automatically emits `DELETE` statements for all related documents. `delete-orphan` additionally ensures that if a document is removed from `project.documents` (detached from the collection), it gets deleted — an "orphan" document with no project is not allowed.
- **Two levels of cascade**: The `ondelete="CASCADE"` on the FK handles database-level cascades (raw SQL, direct DB access). The `cascade="all, delete-orphan"` handles ORM-level cascades (when using SQLAlchemy's session). Both are needed for defense in depth.

#### C. Pydantic Schema: `backend/app/schemas/document.py`

```python
class DocumentRead(BaseModel):
    id: int
    project_id: int
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    page_count: Optional[int]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- **No `DocumentCreate` or `DocumentUpdate` schemas**: Unlike projects (which use JSON body for create/update), documents are created via multipart file upload (`UploadFile`). There's no JSON body to validate with Pydantic. Document updates aren't supported — if you need a new version, delete and re-upload. This keeps the API simple.
- **`status: str` (not `DocumentStatus`)**: The schema intentionally uses `str` rather than the enum type. This keeps the Pydantic schema decoupled from the ORM model's internal enum definition.

#### D. Repository: `backend/app/repositories/document_repository.py`

Follows the same pattern established in Milestone 1's `ProjectRepository`:

```python
def get_by_project_and_filename(self, project_id: int, filename: str) -> Optional[Document]:
    return (
        self.db.query(Document)
        .filter(Document.project_id == project_id, Document.filename == filename)
        .first()
    )
```

- **`get_by_project_and_filename`**: This is the duplicate-detection query. Before uploading, the service checks if a file with the same name already exists in the same project. Using `.first()` rather than `.one()` — returns `None` if no match (rather than raising an exception).
- **`create()` sets `status=DocumentStatus.UPLOADED.value`**: The repository hardcodes the initial status. Every new document starts as `"uploaded"`. Future milestones will add repository methods to transition the status (e.g., `update_status(document, DocumentStatus.PROCESSING)`).

#### E. Service Layer: `backend/app/services/document_service.py`

This is the most important new file in Milestone 2. The upload method orchestrates a 7-step workflow:

```python
def upload(self, project_id: int, file: UploadFile) -> Document:
    # 1. Verify project exists               → FileNotFoundError
    # 2. Validate file extension (.pdf)       → ValueError
    # 3. Validate MIME type (application/pdf) → ValueError
    # 4. Check for duplicate filename         → FileExistsError
    # 5. Save file to disk                    → creates data/uploads/{id}/{name}
    # 6. Extract page count via PyMuPDF       → ValueError if invalid PDF
    # 7. Insert DB row                        → cleanup file on failure
```

Important implementation details:

- **Validation-first**: Steps 1–4 are pure validation with no side effects. If any fails, nothing has been written to disk or database.
- **File content is read into memory**: `file_content = file.file.read()` reads the entire file into memory before writing to disk. For research papers (typically 1–20 MB), this is fine. For very large files, you'd switch to streaming — but that's a premature optimization we don't need.
- **PyMuPDF as a PDF validator**: Opening the file with `pymupdf.open()` and checking `len(pdf_doc)` is not just metadata extraction — it's also a structural PDF validation. If someone renames a `.txt` file to `.pdf`, PyMuPDF will fail to parse it and the upload is rejected. This is defense in depth beyond MIME type checking (which only checks the HTTP header, not the actual file content).
- **Exception-based control flow**: The service raises standard Python exceptions (`FileNotFoundError`, `ValueError`, `FileExistsError`) rather than returning error codes. The endpoint layer catches these and translates them to HTTP status codes. This keeps the service layer HTTP-agnostic — it could be called from a CLI, a background task, or a test without any HTTP dependency.

#### F. API Endpoints: `backend/app/api/endpoints/documents.py`

```python
router = APIRouter(prefix="/projects", tags=["Documents"])
```

- **Shared prefix with Projects router**: Both `projects.py` and `documents.py` use `prefix="/projects"`. FastAPI's router system handles this correctly — the route paths don't collide because document routes all include `/documents` in their path template (e.g., `/{project_id}/documents`).
- **Thin endpoints**: Each endpoint is ~10 lines. It constructs the service, calls the method, catches exceptions, and translates to HTTP. No business logic.
- **Exception translation pattern**:

| Python Exception | HTTP Status | When |
|:---|:---|:---|
| `FileNotFoundError` | `404` | Project or document not found |
| `ValueError` | `400` | Invalid file type, corrupt PDF |
| `FileExistsError` | `409` | Duplicate filename in project |

#### G. Configuration: `backend/app/core/config.py`

```python
class Settings(BaseSettings):
    database_url: str
    upload_dir: str = "data/uploads"
```

- **`upload_dir` with default**: The upload directory is configurable via the `UPLOAD_DIR` environment variable. Defaults to `data/uploads` relative to the working directory. In tests, this is overridden to a temporary directory via the `test_upload_dir` fixture. In production, it could point to a mounted volume or cloud storage adapter path.

#### H. Test Fixtures: `backend/tests/conftest.py` (additions)

```python
@pytest.fixture(scope="session")
def sample_pdf_bytes():
    doc = pymupdf.open()  # new empty PDF
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Test document for research platform.")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
```

- **Generated PDF, not committed binary**: Rather than committing a `.pdf` file to the Git repository, we use PyMuPDF to generate a minimal valid 1-page PDF programmatically. This is deterministic, keeps the repo clean, and tests the same PyMuPDF library that production code uses.
- **`scope="session"`**: The PDF bytes are generated once per test run and reused across tests. Generating a 1-page PDF takes microseconds, but the session scope avoids even that tiny overhead.
- **`test_upload_dir` fixture**: Overrides `settings.upload_dir` to point to `tmp_path/uploads` for each test. This ensures tests don't write to the real `data/uploads/` directory, and the temporary directory is automatically cleaned up by pytest.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Service layer** | Introduced for documents | Keep endpoint + repository only | Upload requires coordinating disk I/O + DB. Service provides error cleanup guarantees. Projects keep the simpler 3-layer pattern since they don't need this. |
| **URL nesting** | Fully nested `/projects/{id}/documents/{id}` | Flat `/documents/{id}` for single-doc operations | Consistency. Every document operation explicitly declares its parent project. Avoids confusion about which project a document belongs to. |
| **VARCHAR for status** | Python `str, enum.Enum` + VARCHAR column | PostgreSQL native `ENUM` type | Postgres `ENUM` requires `ALTER TYPE ... ADD VALUE` to extend, which can't run in a transaction. VARCHAR + Python validation is simpler to migrate. |
| **Status field in Milestone 2** | Added now with default `"uploaded"` | Add in Milestone 3 when processing is implemented | Avoids a schema migration later. One column now saves operational complexity later. The field accurately describes the current state (`"uploaded"` = no processing done). |
| **PDF-only restriction** | Validate extension + MIME type + PyMuPDF parse | Accept any file type | The platform is for research papers. Restricting to PDF reduces attack surface and simplifies the ingestion pipeline. Other types can be added later. |
| **Duplicate filename rejection** | `409 Conflict` for same filename in same project | Auto-rename (e.g., `paper_2.pdf`) | Explicit rejection forces the user to be intentional. Auto-renaming hides the duplicate, which could cause confusion when citing sources later. |
| **Page count at upload** | Extract via PyMuPDF during upload | Defer to processing phase | Takes milliseconds, validates PDF integrity, and provides immediately useful metadata. Not premature — it's the simplest possible PDF operation. |
| **File stored on local filesystem** | `data/uploads/{project_id}/{filename}` | Cloud storage (S3, GCS) | Local storage is correct for development. Cloud storage is a Milestone 18 concern. The configurable `upload_dir` setting makes future migration straightforward. |
| **Read entire file into memory** | `file.file.read()` | Streaming to disk | Research papers are 1–20 MB. Reading into memory is simple and sufficient. Streaming adds complexity for a problem we don't have at this scale. |

---

### 6. Database Schema & Migration

#### Resulting `documents` table in PostgreSQL:

| Column | PostgreSQL Type | Constraints |
|:---|:---|:---|
| `id` | `INTEGER` | PRIMARY KEY, NOT NULL, AUTO INCREMENT, INDEXED |
| `project_id` | `INTEGER` | NOT NULL, FK → `projects.id` ON DELETE CASCADE, INDEXED |
| `filename` | `VARCHAR` | NOT NULL |
| `file_path` | `VARCHAR` | NOT NULL |
| `file_size` | `INTEGER` | NOT NULL |
| `mime_type` | `VARCHAR` | NOT NULL |
| `page_count` | `INTEGER` | NULLABLE |
| `status` | `VARCHAR` | NOT NULL, DEFAULT `'uploaded'` |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |

#### Updated `projects` table relationship:

The `projects` table itself is unchanged. The relationship exists only at the ORM level (`Project.documents`) and in the `documents` table's foreign key.

#### Migration commands:
```bash
cd backend
alembic revision --autogenerate -m "create document table"
alembic upgrade head
```

The generated migration (`959decb82d1f`) creates the `documents` table with all columns, the FK constraint with `ON DELETE CASCADE`, and indexes on `id` and `project_id`.

---

### 7. How to Run, Test, and Verify

#### Run the server:
```bash
cd backend
source ../.venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Upload a PDF via the `POST /api/projects/{project_id}/documents` endpoint (click "Try it out" → choose file)
- Verify the file appears in `data/uploads/{project_id}/`
- Verify the `status` field shows `"uploaded"`

#### Run the tests:
```bash
cd /path/to/research-platform
.venv/bin/pytest backend/tests/ -v
```

#### All 13 document tests that pass:

| Test | What it verifies |
|:---|:---|
| `test_upload_document_success` | `POST` returns `201` with correct metadata (filename, mime_type, page_count=1, status=uploaded), file exists on disk |
| `test_upload_to_nonexistent_project` | Upload to non-existent project returns `404` |
| `test_upload_non_pdf_rejected` | Uploading a `.txt` file returns `400` with "not allowed" |
| `test_upload_duplicate_filename_rejected` | Same filename twice in same project returns `409` with "already exists" |
| `test_list_documents_empty` | Empty project returns `200` with `[]` |
| `test_list_documents_returns_uploaded` | Uploaded documents appear in list with correct filenames |
| `test_list_documents_nonexistent_project` | List for non-existent project returns `404` |
| `test_get_document_by_id` | Correct document returned for valid project + document ID |
| `test_get_document_not_found` | Non-existent document returns `404` |
| `test_get_document_wrong_project` | Document exists but queried via wrong project ID → `404` |
| `test_delete_document` | `DELETE` returns `204`, file removed from disk, subsequent `GET` returns `404` |
| `test_delete_document_not_found` | `DELETE` non-existent document returns `404` |
| `test_delete_project_cascades_documents` | Deleting a project also deletes its documents (cascade) |

**Total test suite**: 26 tests (13 documents + 11 projects + 2 infrastructure), all passing.

---

### 8. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why did you introduce a service layer for documents but not for projects?**
   *"The project CRUD operations are pure database reads and writes — there's no side effect coordination needed. A service layer would have been an empty pass-through. Document upload is fundamentally different: it requires saving a file to disk, validating the file with PyMuPDF, and inserting a database row. If the DB insert fails after the file is written, we need to clean up the file. This multi-step, multi-resource coordination is exactly what a service layer is for."*

2. **Why store the document status as VARCHAR instead of a PostgreSQL ENUM type?**
   *"PostgreSQL's native ENUM type is rigid. Adding a new value requires `ALTER TYPE ... ADD VALUE`, which is a DDL statement that cannot run inside a transaction. If you need to add a new status like `'queued'` in a future migration, it becomes operationally painful. Storing as VARCHAR with a Python-side `str, enum.Enum` gives us the same validation guarantees in application code while keeping migrations simple — it's just a regular VARCHAR column."*

3. **How do you handle partial failures during file upload?**
   *"The upload follows a validate-first pattern: we check the project exists, validate the file type, and check for duplicates before writing anything. Once we start writing, we use try/except blocks with cleanup: if PyMuPDF fails to parse the saved file, we delete it. If the DB insert fails after the file is saved, we delete the file. The service layer guarantees that the system never ends up in an inconsistent state — a file on disk without a DB record, or a DB record without a file."*

4. **Why validate the PDF three different ways (extension, MIME type, and PyMuPDF)?**
   *"Defense in depth. The file extension check catches obvious mismatches like `.txt` files. The MIME type check validates the HTTP content-type header. But neither actually examines the file contents — you could rename a JPEG to `.pdf` and set the header to `application/pdf`. PyMuPDF actually tries to parse the PDF structure, catching corrupt or fake files. Each layer catches a different class of invalid input."*

5. **Why cascade deletes at both the ORM level and the database level?**
   *"`ondelete='CASCADE'` on the FK is a database-level constraint — PostgreSQL enforces it regardless of whether you're using SQLAlchemy or raw SQL. `cascade='all, delete-orphan'` on the relationship is an ORM-level behavior — SQLAlchemy emits DELETE statements for related objects when you call `session.delete(project)`. Having both means cascades work correctly no matter how the deletion is triggered — through the ORM, through a migration, through a database admin tool, or through a raw SQL query."*

6. **Why nest all document endpoints under `/projects/{id}/documents` instead of having `/documents/{id}`?**
   *"Consistency over convenience. The document ID is globally unique, so `/documents/{id}` would technically work. But nesting forces every operation to explicitly declare the parent project, which makes the API self-documenting and prevents subtle bugs where a document is accessed through the wrong project context. It also makes authorization straightforward in the future — access control is naturally scoped to the project."*
