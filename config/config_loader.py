"""
config_loader.py
----------------
Responsável por carregar e validar o arquivo config.yaml usando Pydantic.
Garante que todos os parâmetros obrigatórios estejam presentes e com tipos corretos
antes de qualquer execução do framework.
"""

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Modelos de configuração (Pydantic)
# ---------------------------------------------------------------------------

class ScraperConfig(BaseModel):
    search_phrase: str = Field(..., min_length=1, description="Frase de pesquisa no NYTimes")
    categories: List[str] = Field(default=[], description="Categorias/seções para filtrar")
    months: int = Field(default=1, ge=0, description="Número de meses de cobertura (0 ou 1 = mês atual)")

    @field_validator("search_phrase")
    @classmethod
    def search_phrase_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("search_phrase não pode ser uma string vazia ou somente espaços.")
        return v.strip()

    @field_validator("categories", mode="before")
    @classmethod
    def normalize_categories(cls, v) -> List[str]:
        if v is None:
            return []
        return [cat.strip() for cat in v if cat and cat.strip()]


class OutputConfig(BaseModel):
    excel_filename: str = Field(default="nytimes_news.xlsx")
    images_folder: str = Field(default="output/images")
    excel_folder: str = Field(default="output")


class BrowserConfig(BaseModel):
    headless: bool = Field(default=True)
    timeout_ms: int = Field(default=30000, gt=0)
    slow_mo_ms: int = Field(default=100, ge=0)
    viewport_width: int = Field(default=1366, gt=0)
    viewport_height: int = Field(default=768, gt=0)


class FrameworkConfig(BaseModel):
    max_retries: int = Field(default=3, ge=1)
    retry_delay_seconds: int = Field(default=5, ge=0)
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level deve ser um de: {valid}")
        return upper


class UrlsConfig(BaseModel):
    base_url: str = Field(default="https://www.nytimes.com")
    search_url: str = Field(default="https://www.nytimes.com/search")


class AppConfig(BaseModel):
    """Configuração raiz que agrega todos os blocos do config.yaml"""
    scraper: ScraperConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    framework: FrameworkConfig = Field(default_factory=FrameworkConfig)
    urls: UrlsConfig = Field(default_factory=UrlsConfig)


# ---------------------------------------------------------------------------
# Função pública de carregamento
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Carrega e valida o arquivo config.yaml.

    Args:
        config_path: Caminho para o arquivo YAML. Se None, usa o padrão
                     'config/config.yaml' relativo à raiz do projeto.

    Returns:
        AppConfig: objeto de configuração validado e tipado.

    Raises:
        FileNotFoundError: se o arquivo não for encontrado.
        ValueError: se algum campo falhar na validação do Pydantic.
    """
    if config_path is None:
        # Resolve o caminho relativo à raiz do projeto (um nível acima de /config)
        root = Path(__file__).resolve().parent.parent
        config_path = root / "config" / "config.yaml"

    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {config_path}\n"
            "Verifique se o arquivo 'config/config.yaml' existe na raiz do projeto."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError("O arquivo config.yaml está vazio ou inválido.")

    return AppConfig(**raw)


# ---------------------------------------------------------------------------
# Execução direta para teste rápido
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = load_config()
    print("=== Configuração carregada com sucesso ===")
    print(f"  Search phrase : {config.scraper.search_phrase}")
    print(f"  Categories    : {config.scraper.categories or '(nenhuma)'}")
    print(f"  Months        : {config.scraper.months}")
    print(f"  Headless      : {config.browser.headless}")
    print(f"  Max retries   : {config.framework.max_retries}")
    print(f"  Output folder : {config.output.excel_folder}")
