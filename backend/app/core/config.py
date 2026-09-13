from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    upload_dir: str = "data/uploads"

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()