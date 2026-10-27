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

    # LLM Configuration (Milestone 8)
    llm_provider: str = "ollama"            # "ollama" or "openai"
    llm_model: str = "llama3.1:8b"          # Model identifier
    llm_base_url: str = "http://localhost:11434"  # For Ollama
    llm_api_key: str = ""                   # For OpenAI/Gemini (from env)
    llm_temperature: float = 0.1           # Low for factual accuracy
    llm_max_tokens: int = 2000             # Max response length

    # RAG Configuration
    rag_top_k: int = 5                     # Default evidence passages
    rag_default_search_mode: str = "hybrid" # Default retrieval mode
    rag_default_rerank: bool = True         # Rerank by default

    # Agent Configuration (Milestone 13)
    agent_max_iterations: int = 10
    agent_max_tool_calls: int = 25
    agent_max_time_seconds: int = 300
    agent_max_observation_chars: int = 1500
    agent_context_budget_tokens: int = 6000
    agent_checkpoint_interval: int = 3
    agent_force_final_after_max: bool = True
    agent_max_consecutive_errors: int = 3

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()