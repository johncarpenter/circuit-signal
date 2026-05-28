from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://circuit:circuit_dev@localhost:5432/circuit"
    REDIS_URL: str = "redis://localhost:6379"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "circuit"
    MINIO_SECRET_KEY: str = "circuit_dev"
    MINIO_BUCKET: str = "circuit-signal"
    MINIO_SECURE: bool = False
    MAX_UPLOAD_SIZE_MB: int = 500
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
