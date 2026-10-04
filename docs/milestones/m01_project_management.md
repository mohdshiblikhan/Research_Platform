# Milestone 1: Research Project Management

- **Status**: Completed
- **Version**: `v0.1`
- **Git Commit**: `3bc3355` (*feat: add project CRUD — model, schemas, repository, API endpoints, and tests*)
- **Migration**: `2bb6b4a6e6d4` (*create project table*)

---

### 1. Objective & Problem Solved

#### The Problem
Our backend foundation from Milestone 0 can start, connect to PostgreSQL, and pass tests — but it has no domain knowledge. It has no concept of a "research project". Before we can upload papers, run searches, or track experiments, we need a root organizing entity that everything else will belong to.

#### The Solution
Introduce the `Project` entity — the top-level workspace in the platform. A researcher can create a named project (e.g., *"RAG Hallucination Research"*) and all future work — documents, chunks, search results, experiment runs — will be scoped to that project.

This milestone also establishes the **full layered architecture pattern** (Model → Schema → Repository → API) that every future feature will follow.

---

### 2. What the API Exposes

All endpoints are mounted under `/api`:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects` | Create a new project | `201 Created` |
| `GET` | `/api/projects` | List all projects (newest first) | `200 OK` |
| `GET` | `/api/projects/{id}` | Get a single project by ID | `200 OK` |
| `PATCH` | `/api/projects/{id}` | Partially update a project | `200 OK` |
| `DELETE` | `/api/projects/{id}` | Delete a project | `204 No Content` |

**API versioning decision**: We deliberately kept endpoints flat at `/api/projects` rather than nesting under `/api/v1/projects`. URL versioning only becomes necessary when you need to run two incompatible API versions simultaneously for different clients. We have no existing clients and no breaking changes to protect — adding the `v1/` folder would be complexity for a problem we don't have.

---

### 3. Layered Architecture & Why

Every feature in this project follows a strict 4-layer separation. Here is what each layer owns and why the separation matters:

```
HTTP Request
     │
     ▼
┌───────────────────────────────────┐
│  API Layer (endpoints/projects.py) │  Receives request, validates input via Pydantic,
│                                    │  returns typed response. No SQL here.
└──────────────────┬────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────┐
│  Repository Layer (project_repository.py)   │  The ONLY place that writes SQL / ORM queries.
│                                            │  Receives a Session, returns ORM objects.
└──────────────────┬─────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────┐
│  ORM Model Layer (project.py)    │  Declares the `projects` table structure.
│                                  │  Maps Python class attributes to DB columns.
└──────────────────────────────────┘

Pydantic Schemas (schemas/project.py) — Cross-cutting: validate API input & serialize output.
```

**Why not just write SQL inside the route handler?**  
Route handlers become 100-line functions that mix HTTP concerns, validation, and SQL. The moment you want to add pagination, caching, or bulk operations, you have to untangle everything. Repositories keep queries in one testable, reusable place.

**Why a separate schemas layer from models?**  
The ORM model reflects the database — it owns `id`, `created_at`, `updated_at`, and potentially future internal/sensitive fields. Pydantic schemas reflect the API contract — what the client is allowed to send and receive. If you expose the ORM object directly, you lose control over what gets serialized (fields may appear or disappear depending on ORM loading state).

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. ORM Model: `backend/app/models/project.py`
```python
class Project(Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
```
- Inherits `id`, `created_at`, `updated_at` from `Base` (Milestone 0).
- `Mapped[str]` and `Mapped[Optional[str]]` use SQLAlchemy 2.0 typed syntax — Python's type checker understands these as actual `str` / `str | None` types, not opaque `Column` descriptors.
- `nullable=False` on `title` means PostgreSQL will enforce that a title must always be present at the database level — not just at the API validation level. Defense in depth.

#### B. Model Registry: `backend/app/models/__init__.py`
```python
from app.db.base_class import Base
from app.models.project import Project  # registered for Alembic
```
- Alembic's autogenerate works by inspecting `Base.metadata` — the registry of all tables. If `Project` is never imported anywhere that `Base.metadata` can see, Alembic silently ignores it and generates an empty migration. This import makes it visible.

#### C. Pydantic Schemas: `backend/app/schemas/project.py`

Three schemas, each with a specific job:

| Schema | Purpose | Key Design |
|:---|:---|:---|
| `ProjectCreate` | Client → API when creating | `title` required, `description` optional |
| `ProjectUpdate` | Client → API when updating | All fields optional (partial update) |
| `ProjectRead` | API → Client in response | Includes `id`, `created_at`, `updated_at` |

```python
class ProjectRead(BaseModel):
    model_config = {"from_attributes": True}
```
`from_attributes = True` tells Pydantic: "when converting, read attributes off the object directly, not just from a dict". This is required to convert a SQLAlchemy ORM instance into a Pydantic model. Without it you get a `ValidationError`.

#### D. Repository: `backend/app/repositories/project_repository.py`

Key implementation detail — the `update` method:
```python
def update(self, project: Project, data: ProjectUpdate) -> Project:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    self.db.commit()
    self.db.refresh(project)
    return project
```
- `model_dump(exclude_unset=True)` returns only the fields the client actually sent in the request body. If the client sends `{"title": "New Title"}` and omits `description`, the dict is `{"title": "New Title"}` — not `{"title": "New Title", "description": None}`. This prevents accidentally overwriting a field with `None` just because the client didn't include it.
- `db.refresh(project)` re-reads the row from the database after commit. This ensures `updated_at` (which PostgreSQL updates on the server side) is reflected in the returned object.

#### E. API Endpoints: `backend/app/api/endpoints/projects.py`
```python
router = APIRouter(prefix="/projects", tags=["Projects"])
```
- `prefix="/projects"` means all routes in this file are automatically under `/projects`. When mounted with `prefix="/api"` in `main.py`, the full path becomes `/api/projects`.
- `tags=["Projects"]` groups all these routes under a "Projects" section in the Swagger UI (`/docs`).
- `status_code=status.HTTP_201_CREATED` on the `POST` route — creation should return `201`, not `200`. This is the semantically correct HTTP status.
- `status_code=status.HTTP_204_NO_CONTENT` on `DELETE` — successful deletion returns no body, which is why `204` is correct (not `200`).

#### F. Central Router: `backend/app/api/router.py`
```python
from app.api.endpoints import projects
router = APIRouter()
router.include_router(projects.router)
```
- Acts as a central registry. When Milestone 2 adds `documents.py`, it gets one line added here: `router.include_router(documents.router)`. `main.py` doesn't need to change.

#### G. Application Mount: `backend/app/main.py`
```python
app.include_router(api_router, prefix="/api")
```
- The `/api` prefix is applied globally here. Every future feature mounted through `api/router.py` automatically lives under `/api/...`.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **API versioning** | Flat `/api/projects` | `/api/v1/projects` | No existing clients, no breaking changes. Versioning adds complexity for a problem that doesn't exist yet. |
| **Partial update method** | `PATCH` with `exclude_unset=True` | `PUT` full replacement | `PUT` forces the client to send all fields even if only one changed. `PATCH` is semantically correct for partial updates and prevents accidental overwrites. |
| **Repository pattern** | Dedicated repository class | SQL in route handler | Keeps route handlers slim, makes queries reusable, and makes the data access layer independently testable. |
| **No service layer** | Skipped for simple CRUD | Service layer for all features | A service layer makes sense when business logic is complex (e.g., "creating a project also needs to initialize an embedding index"). For basic CRUD, it would just be empty pass-through code. |
| **Integer primary key** | `id: int` autoincrement | UUID | Integer PKs are simpler, faster for joins, and sufficient at this stage. UUIDs become valuable when distributing data across systems or exposing IDs externally — not a current requirement. |

---

### 6. Database Schema & Migration

#### Resulting `projects` table in PostgreSQL:

| Column | PostgreSQL Type | Constraints |
|:---|:---|:---|
| `id` | `INTEGER` | PRIMARY KEY, NOT NULL, AUTO INCREMENT |
| `title` | `VARCHAR` | NOT NULL |
| `description` | `VARCHAR` | NULLABLE |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |

#### Migration commands:
```bash
cd backend
alembic revision --autogenerate -m "create project table"
alembic upgrade head
```
- `--autogenerate` — Alembic connects to the DB, inspects existing tables, compares with `Base.metadata`, and generates the SQL diff.
- `upgrade head` — Applies all unapplied migrations up to the latest version.

The generated migration file (`2bb6b4a6e6d4_create_project_table.py`) lives in `backend/alembic/versions/` and is committed to Git so every developer and every deployment environment runs the exact same schema changes in the same order.

---

### 7. How to Run, Test, and Verify

#### Run the server:
```bash
cd backend
source ../.venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Try creating a project, listing, updating, and deleting via the interactive docs.

#### Run the tests:
```bash
cd /path/to/research-platform
.venv/bin/pytest backend/tests/ -v
```

#### All 11 tests that pass:
| Test | What it verifies |
|:---|:---|
| `test_create_project_success` | `POST` returns `201` with correct fields including `id` and timestamps |
| `test_create_project_with_description` | Optional description is stored correctly |
| `test_create_project_missing_title` | Missing required field returns `422 Unprocessable Entity` (Pydantic validation) |
| `test_list_projects_empty` | Empty database returns an empty list `[]` |
| `test_list_projects_returns_created` | Created projects appear in the list |
| `test_get_project_by_id` | Correct project returned for a valid ID |
| `test_get_project_not_found` | Non-existent ID returns `404` with `"Project not found"` |
| `test_update_project_title` | Only the title changes; description remains untouched |
| `test_update_project_not_found` | `PATCH` on non-existent ID returns `404` |
| `test_delete_project` | `DELETE` returns `204`; subsequent `GET` returns `404` |
| `test_delete_project_not_found` | `DELETE` on non-existent ID returns `404` |

---

### 8. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why PATCH instead of PUT for updates?**
   *"PUT requires the client to send the entire resource representation. PATCH is semantically correct for partial updates. Practically, we use `model_dump(exclude_unset=True)` in the Pydantic schema so only the fields the client explicitly provided are applied — this prevents accidentally overwriting existing data with `None` when the client omits a field."*

2. **Why a Repository layer? Isn't it overkill for simple CRUD?**
   *"For simple CRUD it adds one file of indirection. The payoff comes when you need pagination, soft deletes, caching, or bulk operations — all in one place rather than scattered across route handlers. It also makes testing cleaner: the repository gets a session injected, so you can test queries directly without going through HTTP."*

3. **How does `from_attributes = True` work in Pydantic?**
   *"By default, Pydantic reads data from dict-like inputs. SQLAlchemy ORM objects aren't dicts — they're Python objects with attributes. `from_attributes = True` tells Pydantic to call `getattr(obj, field_name)` instead of `obj[field_name]`, which is how it can deserialize a SQLAlchemy model instance directly."*

4. **Why keep the API flat at `/api/projects` rather than `/api/v1/projects`?**
   *"URL versioning only matters when you need two incompatible API versions running at the same time — for example, old mobile app clients that can't be updated. We have no existing clients. Adding the `v1/` directory would be complexity for a problem we don't have. We can always introduce `v2/` when there's a genuine breaking change."*
