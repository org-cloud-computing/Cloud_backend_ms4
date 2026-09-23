"""
Configuración de MS4
"""

import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Configuración del servicio"""

    # URLs de otros microservicios
    MS1_URL: str = os.getenv("MS1_URL", "http://localhost:8080")
    MS2_URL: str = os.getenv("MS2_URL", "http://localhost:8081")
    MS3_URL: str = os.getenv("MS3_URL", "http://localhost:8082")

    # Configuración general
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))
    PORT: int = int(os.getenv("PORT", "8083"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
