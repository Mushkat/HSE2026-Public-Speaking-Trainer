from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///./app.db"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    storage_root: str = "storage"

    class Config:
        env_prefix = ""
        env_file = ".env"
        case_sensitive = False


settings = Settings()
