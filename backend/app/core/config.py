from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    upload_dir: str = "data/uploads"

    # Document chunking defaults (Milestone 3)
    chunk_size: int = 1000
    chunk_overlap: int = 200

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()