from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    app_name: str = "LearnFlow"
    app_version: str = "0.1.0"

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # Database
    database_url: str = "sqlite+aiosqlite:///./learnflow.db"

    # Embedding
    embedding_backend: str = "local"  # local | api
    embedding_model: str = "text-embedding-ada-002"  # for api backend
    embedding_api_key: str = ""  # separate from llm_api_key
    embedding_base_url: str = ""  # separate from llm_base_url (empty = use llm_base_url)

    # CORS — stored as comma-separated in env, split at use
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    log_level: str = "info"

    class Config:
        env_file = ".env"

    @property
    def cors_origins_list(self) -> List[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]


settings = Settings()
