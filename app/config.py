from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

class Settings(BaseSettings):
    app_name: str = "CubeMaster PoC API"
    app_version: str = "1.0.0"
    environment: str = "development"
    cubemaster_api_url: str
    cubemaster_token_id: str
    
    # Diretório base para response_data (configurável via ENV)
    # No Docker: /code/app/response_data (mapeado para /mnt/psappt1/AJ_LOGISTICA_TST)
    # Localmente: app/response_data
    response_output_dir: str = "app/response_data"
    
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    # ========== PROPRIEDADES PARA SUBDIRETÓRIOS ==========
    
    @property
    def json_pendiente_dir(self) -> Path:
        """Diretório para JSONs pendentes de processamento"""
        return Path(self.response_output_dir) / "json_pendiente"
    
    @property
    def json_procesado_dir(self) -> Path:
        """Diretório para JSONs já processados"""
        return Path(self.response_output_dir) / "json_procesado"
    
    @property
    def csv_procesado_dir(self) -> Path:
        """Diretório para CSVs e Excels gerados"""
        return Path(self.response_output_dir) / "csv_procesado"
    
    def ensure_directories_exist(self) -> None:
        """Cria todos os diretórios necessários se não existirem"""
        for directory in [
            self.json_pendiente_dir,
            self.json_procesado_dir,
            self.csv_procesado_dir
        ]:
            directory.mkdir(parents=True, exist_ok=True)

@lru_cache()
def get_settings():
    return Settings()
