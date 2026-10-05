from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    upload_dir: str = "data/uploads"

    # Document chunking defaults (Milestone 3)
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Embedding configuration (Milestone 5)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_batch_size: int = 64

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()