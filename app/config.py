from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "CubeMaster PoC API"
    app_version: str = "1.0.0"
    environment: str = "development"
    cubemaster_api_url: str
    cubemaster_token_id: str
    response_output_dir: str = "app/response_data"
    
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings():
    return Settings()
