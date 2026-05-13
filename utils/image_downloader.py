"""
utils/image_downloader.py
--------------------------
Responsavel pelo download das imagens das noticias.

Comportamento:
  - Recebe a URL da imagem e o titulo da noticia
  - Gera um nome de arquivo seguro (sem caracteres especiais)
  - Salva a imagem em output/images/
  - Retorna o nome do arquivo para registro no Excel
  - Se URL invalida ou download falhar, retorna string vazia
  - Evita re-download se o arquivo ja existir (idempotente)
"""

import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("nytimes_scraper.image_downloader")

_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nytimes.com/",
}

_VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _build_session() -> requests.Session:
    """Cria uma Session com retry automatico em falhas de rede."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class ImageDownloader:
    """
    Faz download de imagens e as salva localmente.

    Uso:
        downloader = ImageDownloader(config)
        filename = downloader.download(image_url, news_title)
    """

    def __init__(self, config):
        self.config = config
        self.images_folder = Path(config.output.images_folder)
        self.images_folder.mkdir(parents=True, exist_ok=True)
        self._session = _build_session()

    def download(self, image_url: Optional[str], title: str) -> str:
        """
        Faz o download da imagem e retorna o nome do arquivo salvo.

        Args:
            image_url: URL completa da imagem. Pode ser None se nao houver imagem.
            title    : Titulo da noticia - usado para nomear o arquivo.

        Returns:
            Nome do arquivo salvo, ou string vazia se falhar.
        """
        if not image_url or not image_url.startswith("http"):
            logger.debug(f"URL de imagem invalida ou ausente para: '{title[:60]}'")
            return ""

        try:
            extension = self._get_extension_from_url(image_url)
            filename = self._sanitize_filename(title, extension)
            filepath = self.images_folder / filename

            # Evita re-download se o arquivo ja existe
            if filepath.exists():
                logger.debug(f"Imagem ja existe, pulando download: {filename}")
                return filename

            # Realiza o download
            response = self._session.get(
                image_url,
                headers=_DOWNLOAD_HEADERS,
                timeout=15,
                stream=True,
            )
            response.raise_for_status()

            filepath.write_bytes(response.content)
            size_kb = filepath.stat().st_size / 1024
            logger.debug(f"Imagem salva: {filename} ({size_kb:.1f} KB)")
            return filename

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout ao baixar imagem: {image_url}")
            return ""

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Erro HTTP {e.response.status_code} ao baixar imagem: {image_url}")
            return ""

        except Exception as e:
            logger.warning(f"Falha ao baixar imagem '{image_url}': {e}")
            return ""

    def _sanitize_filename(self, title: str, extension: str = ".jpg") -> str:
        """
        Gera um nome de arquivo seguro a partir do titulo da noticia.
        """
        safe = re.sub(r"[^\w\s\-]", "", title, flags=re.UNICODE)
        safe = re.sub(r"[\s_]+", "_", safe.strip())
        safe = safe.strip("_")
        safe = safe[:80]

        if not safe:
            safe = "image"

        filename = f"{safe}{extension}"

        filepath = self.images_folder / filename
        if filepath.exists():
            counter = 1
            while (self.images_folder / f"{safe}_{counter}{extension}").exists():
                counter += 1
            filename = f"{safe}_{counter}{extension}"

        return filename

    def _get_extension_from_url(self, url: str) -> str:
        """
        Extrai a extensao da imagem a partir da URL.
        """
        try:
            parsed = urlparse(url)
            path = parsed.path
            suffix = Path(path).suffix.lower()

            if suffix in _VALID_EXTENSIONS:
                return suffix

            if ".jpg" in path or ".jpeg" in path:
                return ".jpg"
            if ".png" in path:
                return ".png"
            if ".webp" in path:
                return ".webp"

        except Exception:
            pass

        return ".jpg"
