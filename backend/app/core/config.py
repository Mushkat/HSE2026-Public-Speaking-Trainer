from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///./app.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    storage_root: str = "/app/storage"
    redis_url: str = "redis://localhost:6379/0"
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_model_cache_dir: str = "/models/faster-whisper"
    local_llm_enabled: bool = False
    local_llm_base_url: str = "http://llm:8080"
    local_llm_timeout_sec: float = 120.0
    local_llm_max_retries: int = 0
    local_llm_temperature: float = 0.2
    local_llm_max_tokens: int = 256
    local_llm_max_tokens_questions: int = 180
    local_llm_max_tokens_keymoments: int = 180
    local_llm_max_input_chars: int = 700
    local_llm_json_strict: bool = True
    local_llm_max_parallel_requests: int = 1
    debug_llm: bool = False
    debug_llm_quality: bool = False
    debug_metrics: bool = False
    asr_low_confidence_threshold: float = Field(
        default=0.3,
        validation_alias=AliasChoices("ASR_LOW_CONF_THRESHOLD", "ASR_LOW_CONFIDENCE_THRESHOLD"),
    )

    @field_validator("asr_low_confidence_threshold")
    @classmethod
    def validate_asr_low_confidence_threshold(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    class Config:
        env_prefix = ""
        env_file = ".env"
        case_sensitive = False


settings = Settings()
