from pydantic_settings import BaseSettings


class WorkerConfig(BaseSettings):
    DATABASE_URL: str = "postgresql://circuit:circuit_dev@localhost:5432/circuit"
    REDIS_URL: str = "redis://localhost:6379"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "circuit"
    MINIO_SECRET_KEY: str = "circuit_dev"
    MINIO_BUCKET: str = "circuit-signal"
    MINIO_SECURE: bool = False
    ANTHROPIC_API_KEY: str = ""
    BATCH_PARALLEL_WORKERS: int = 4

    model_config = {"env_file": ".env", "extra": "ignore"}


config = WorkerConfig()
