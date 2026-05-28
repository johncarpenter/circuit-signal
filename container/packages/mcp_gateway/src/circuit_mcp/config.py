import os
from pydantic_settings import BaseSettings


class GatewayConfig(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://circuit:circuit_dev@localhost:5432/circuit"
    MCP_PORT: int = 8001

    model_config = {"env_file": ".env", "extra": "ignore"}


config = GatewayConfig()
