"""Application configuration from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Container settings sourced from environment variables."""

    # Required
    agent_api_token: str = ""
    claude_code_oauth_token: str = ""

    # Optional
    agent_name: str = "signal-agent"
    workspace_path: Path = Path("/workspace")
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
