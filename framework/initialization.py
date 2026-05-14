"""
framework/initialization.py
----------------------------
Estado de INICIALIZACAO do REFramework.
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Any

from playwright.sync_api import sync_playwright, Browser, Page, Playwright

from config import load_config, AppConfig
from framework.exceptions import SystemException, ConfigurationException


@dataclass
class ExecutionContext:
    """Container de estado compartilhado entre os modulos do REFramework."""
    config: AppConfig
    logger: logging.Logger
    playwright: Optional[Playwright] = None
    browser: Optional[Browser] = None
    page: Optional[Page] = None
    excel_handler: Optional[Any] = None
    transactions: List[dict] = field(default_factory=list)
    processed_count: int = 0
    failed_count: int = 0
    retry_count: int = 0


class InitializationState:
    """
    Implementa o estado de Inicializacao do REFramework.

    Uso:
        ctx = InitializationState(config_path="config/config.yaml").run()
        ctx = InitializationState().run()   # usa o caminho padrao
    """

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path

    def run(self) -> ExecutionContext:
        """Executa todas as etapas de inicializacao e retorna o ExecutionContext."""
        try:
            config = load_config(self._config_path)
        except FileNotFoundError as e:
            raise ConfigurationException(str(e)) from e
        except ValueError as e:
            raise ConfigurationException(f"Configuracao invalida: {e}") from e

        logger = self._setup_logging(config.framework.log_level)
        logger.info("=" * 60)
        logger.info("NYTimes News Scraper - Inicializando")
        logger.info("=" * 60)

        self._create_output_folders(config, logger)

        logger.info(f"Search phrase : '{config.scraper.search_phrase}'")
        logger.info(f"Categories    : {config.scraper.categories or ['(nenhuma)']}")
        logger.info(f"Months        : {config.scraper.months}")

        try:
            playwright, browser, page = self._init_browser(config, logger)
        except Exception as e:
            raise SystemException(f"Falha ao inicializar o browser: {e}") from e

        logger.info("Inicializacao concluida com sucesso.")

        return ExecutionContext(
            config=config,
            logger=logger,
            playwright=playwright,
            browser=browser,
            page=page,
        )

    def _setup_logging(self, log_level: str) -> logging.Logger:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"

        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format=log_format,
            datefmt=date_format,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("logs/scraper.log", encoding="utf-8"),
            ],
        )
        return logging.getLogger("nytimes_scraper")

    def _create_output_folders(self, config: AppConfig, logger: logging.Logger) -> None:
        images_folder = Path(config.output.images_folder)
        excel_folder  = Path(config.output.excel_folder)
        excel_file    = excel_folder / config.output.excel_filename

        # Limpa imagens da execucao anterior
        if images_folder.exists():
            removed = 0
            for f in images_folder.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    f.unlink()
                    removed += 1
            if removed:
                logger.info(f"Limpeza: {removed} imagem(ns) removida(s) de '{images_folder}'")

        # Remove Excel anterior
        if excel_file.exists():
            excel_file.unlink()
            logger.info(f"Limpeza: arquivo '{excel_file.name}' removido.")

        # Garante que as pastas existem
        for folder in [excel_folder, images_folder]:
            folder.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Pasta garantida: {folder}")

    def _init_browser(self, config: AppConfig, logger: logging.Logger) -> tuple:
        headless_str = "headless" if config.browser.headless else "headed"
        logger.info(f"Iniciando browser Chromium ({headless_str})...")

        playwright = sync_playwright().start()

        browser = playwright.chromium.launch(
            headless=config.browser.headless,
            slow_mo=config.browser.slow_mo_ms,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-gpu",
                "--window-size=1366,768",
            ],
        )

        context = browser.new_context(
            user_agent=self._USER_AGENT,
            viewport={
                "width": config.browser.viewport_width,
                "height": config.browser.viewport_height,
            },
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/webp,*/*;q=0.8"
                ),
            },
        )

        anti_detection_script = """
            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Plugins realistas
            Object.defineProperty(navigator, 'plugins', {get: () => [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
                {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}
            ]});

            // Idioma e plataforma realistas
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'platform',  {get: () => 'Win32'});

            // Objeto chrome completo
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {isInstalled: false}
            };

            // Permissions API — evita deteccao por consulta de notificacoes
            const _origPermQuery = window.navigator.permissions.query.bind(navigator.permissions);
            window.navigator.permissions.query = (p) =>
                p.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : _origPermQuery(p);

            // WebGL — relata hardware real
            const _origGetParam = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                return _origGetParam.apply(this, [p]);
            };

            // Dimensoes de janela
            if (!window.outerWidth)  window.outerWidth  = window.innerWidth;
            if (!window.outerHeight) window.outerHeight = window.innerHeight;

            // Remove propriedades que delatam automacao
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """
        context.add_init_script(anti_detection_script)

        page = context.new_page()
        page.set_default_timeout(config.browser.timeout_ms)

        logger.info("Stealth mode aplicado (anti-deteccao via JS).")

        logger.info("Browser e pagina inicializados com sucesso.")
        return playwright, browser, page
