from app.db.base_class import Base

# Import all models here so Alembic can discover them
from app.models.project import Project
from app.models.document import Document
from app.models.chunk import Chunk
