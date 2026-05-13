"""
utils/nytimes_scraper.py
-------------------------
Classe responsavel por toda a interacao com o site do NYTimes via Playwright.

Responsabilidades:
  - Construir a URL de busca com parametros de data e ordenacao
  - Navegar para a pagina de resultados
  - Dispensar banners de cookies/consentimento
  - Aplicar filtros de secao/categoria via interface
  - Iterar pelas paginas de resultados ("Show More") com limite de seguranca
  - Extrair dados de cada artigo (titulo, data, descricao, imagem, URL)
  - Filtrar artigos fora do periodo configurado

Edge cases tratados:
  - Resultado vazio (nenhum artigo encontrado)
  - Artigo sem titulo (ignorado)
  - Artigo sem descricao (campo vazio aceito)
  - Artigo sem imagem (image_url fica vazio)
  - Botao "Show More" inexistente/obsoleto (fim da paginacao)
  - Browser inacessivel (BrowserException propagada)
  - Limite maximo de paginas para evitar loop infinito
"""

import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urlencode

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, Error as PlaywrightError

from framework.exceptions import BrowserException, NoTransactionsFound

logger = logging.getLogger("nytimes_scraper.nytimes_scraper")

# ---------------------------------------------------------------------------
# Limite de seguranca
# ---------------------------------------------------------------------------
MAX_PAGES = 50        # maximo de cliques em "Show More"
MAX_ARTICLES = 500    # teto absoluto de artigos por execucao

# ---------------------------------------------------------------------------
# Seletores CSS com fallbacks
# ---------------------------------------------------------------------------
SELECTORS = {
    "results_list": [
        "ol[data-testid='search-results']",
        "ol.css-1l4spti",
    ],
    "article_item": [
        "li[data-testid='search-bodega-result']",
        "ol[data-testid='search-results'] > li",
    ],
    "title": [
        "h4",
        "a h4",
        "[data-testid='topper-headline']",
    ],
    "link": [
        "a[href^='/']",
        "a[href^='https://www.nytimes.com']",
    ],
    "date": [
        "span[data-testid='topper-timestamp']",
        "time[datetime]",
        "span[class*='date']",
        "time",
    ],
    "description": [
        "p[class*='summary']",
        "p[data-testid*='summary']",
        ".css-16nhkrn",
    ],
    "image": [
        "figure img",
        "img[src*='images/']",
        "img[src*='nytimes']",
        "img[src*='static01']",
    ],
    "show_more": [
        "button[data-testid='search-show-more-button']",
        "button:has-text('Show More')",
        "button:has-text('Load More')",
    ],
    "cookie_accept": [
        "button[data-testid='Accept all-btn']",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "#complianceOverlay button[class*='accept']",
    ],
    "section_filter_btn": [
        "button[data-testid='search-multiselect-button']",
        "button[class*='css-'][aria-label*='ection']",
    ],
    "no_results": [
        "[data-testid='no-results']",
        "p:has-text('No results')",
        "p:has-text('did not match')",
    ],
}


class NYTimesScraper:
    """
    Executa a busca no NYTimes e retorna a lista de artigos no periodo configurado.

    Uso:
        scraper = NYTimesScraper(config=config, page=page)
        articles = scraper.search_and_collect(start_date, end_date)
    """

    BASE_URL    = "https://www.nytimes.com"
    SEARCH_URL  = "https://www.nytimes.com/search"

    def __init__(self, config, page: Page):
        self.config  = config
        self.page    = page
        self.timeout = config.browser.timeout_ms

    # =========================================================================
    # Interface publica
    # =========================================================================

    def search_and_collect(self, start_date: date, end_date: date) -> List[dict]:
        """
        Executa a busca completa e retorna todos os artigos dentro do periodo.

        Raises:
            BrowserException: se o browser ficar inacessivel durante a execucao.
            NoTransactionsFound: se nenhum artigo for encontrado (nao e um erro).
        """
        logger.info(f"Iniciando busca: '{self.config.scraper.search_phrase}'")
        logger.info(f"Periodo: {start_date} -> {end_date}")

        try:
            self._navigate_to_search(start_date, end_date)
            self._dismiss_cookie_banner()

            if self._is_empty_results():
                logger.warning("Pagina de resultados retornou zero artigos.")
                raise NoTransactionsFound(
                    f"Nenhum artigo encontrado para '{self.config.scraper.search_phrase}' "
                    f"no periodo {start_date} -> {end_date}"
                )

            if self.config.scraper.categories:
                self._apply_section_filters(self.config.scraper.categories)

            self._wait_for_results()
            articles = self._collect_all_articles(start_date, end_date)

        except (NoTransactionsFound, BrowserException):
            raise
        except PlaywrightError as e:
            raise BrowserException(f"Erro do Playwright durante scraping: {e}") from e
        except Exception as e:
            # Re-levanta preservando o tipo original
            raise

        if not articles:
            raise NoTransactionsFound(
                f"Nenhum artigo no periodo {start_date} -> {end_date} "
                f"para '{self.config.scraper.search_phrase}'."
            )

        logger.info(f"Total de artigos coletados: {len(articles)}")
        return articles

    # =========================================================================
    # Navegacao
    # =========================================================================

    def _navigate_to_search(self, start_date: date, end_date: date) -> None:
        params = {
            "dropmab": "false",
            "query":   self.config.scraper.search_phrase,
            "sort":    "newest",
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate":   end_date.strftime("%Y%m%d"),
        }
        url = f"{self.SEARCH_URL}?{urlencode(params)}"
        logger.info(f"Navegando para: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
        self.page.wait_for_timeout(2000)

    # =========================================================================
    # Cookie banner
    # =========================================================================

    def _dismiss_cookie_banner(self) -> None:
        for selector in SELECTORS["cookie_accept"]:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    logger.debug(f"Cookie banner encontrado ({selector}). Dispensando...")
                    btn.click()
                    self.page.wait_for_timeout(1000)
                    return
            except Exception:
                continue
        logger.debug("Nenhum cookie banner detectado.")

    # =========================================================================
    # Verificacao de resultado vazio
    # =========================================================================

    def _is_empty_results(self) -> bool:
        for selector in SELECTORS["no_results"]:
            try:
                if self.page.locator(selector).first.is_visible(timeout=2000):
                    return True
            except Exception:
                continue
        return False

    # =========================================================================
    # Filtros de secao
    # =========================================================================

    def _apply_section_filters(self, categories: List[str]) -> None:
        logger.info(f"Aplicando filtros de secao: {categories}")

        section_btn = self._find_element(SELECTORS["section_filter_btn"])
        if section_btn is None:
            logger.warning("Botao de filtro de secao nao encontrado. Pulando filtro.")
            return

        section_btn.click()
        self.page.wait_for_timeout(1000)

        for category in categories:
            self._select_section_option(category)

        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(1500)
        self._wait_for_results()

    def _select_section_option(self, category: str) -> None:
        category_lower = category.lower()
        try:
            options = self.page.locator("ul[data-testid='multi-select-dropdown-list'] li")
            count = options.count()
            for i in range(count):
                option = options.nth(i)
                text = (option.text_content() or "").lower()
                if category_lower in text:
                    checkbox = option.locator("input[type='checkbox']").first
                    if not checkbox.is_checked():
                        option.click()
                        self.page.wait_for_timeout(500)
                    logger.debug(f"Secao selecionada: '{category}'")
                    return
            logger.warning(f"Secao '{category}' nao encontrada no dropdown.")
        except Exception as e:
            logger.warning(f"Erro ao selecionar secao '{category}': {e}")

    # =========================================================================
    # Coleta de artigos
    # =========================================================================

    def _wait_for_results(self) -> None:
        for selector in SELECTORS["results_list"]:
            try:
                self.page.wait_for_selector(selector, timeout=self.timeout)
                return
            except PlaywrightTimeout:
                continue
        logger.warning("Lista de resultados nao encontrada apos timeout.")

    def _collect_all_articles(self, start_date: date, end_date: date) -> List[dict]:
        articles: List[dict] = []
        page_num = 1

        while page_num <= MAX_PAGES:
            logger.info(f"Coletando artigos - pagina {page_num}")

            new_articles, should_stop = self._extract_articles_from_page(
                start_date, end_date, already_collected=len(articles)
            )
            articles.extend(new_articles)
            logger.info(f"  +{len(new_articles)} artigos (total: {len(articles)})")

            if should_stop:
                logger.info("Data limite atingida. Encerrando paginacao.")
                break

            if len(articles) >= MAX_ARTICLES:
                logger.warning(f"Limite de {MAX_ARTICLES} artigos atingido.")
                break

            if not self._click_show_more():
                logger.info("Botao 'Show More' indisponivel. Fim dos resultados.")
                break

            page_num += 1
            self.page.wait_for_timeout(2000)

        if page_num > MAX_PAGES:
            logger.warning(f"Limite de {MAX_PAGES} paginas atingido.")

        return articles

    def _extract_articles_from_page(
        self, start_date: date, end_date: date, already_collected: int
    ) -> Tuple[List[dict], bool]:
        articles = []
        should_stop = False

        items = None
        for selector in SELECTORS["article_item"]:
            try:
                locator = self.page.locator(selector)
                if locator.count() > 0:
                    items = locator
                    break
            except Exception:
                continue

        if items is None:
            logger.warning("Nenhum artigo encontrado na pagina.")
            return articles, True

        total_items = items.count()
        logger.debug(f"Total de itens na pagina: {total_items}")

        for i in range(already_collected, total_items):
            try:
                item = items.nth(i)
                article = self._extract_article_data(item)

                if article is None:
                    continue

                article_date = article.pop("_date_obj", None)
                if article_date:
                    if article_date < start_date:
                        should_stop = True
                        break
                    if article_date > end_date:
                        continue

                articles.append(article)

            except Exception as e:
                logger.warning(f"Erro ao extrair artigo {i}: {e}")
                continue

        return articles, should_stop

    def _extract_article_data(self, item) -> Optional[dict]:
        try:
            title = self._get_text(item, SELECTORS["title"])
            if not title or not title.strip():
                logger.debug("Artigo sem titulo - ignorado.")
                return None

            # URL do artigo
            href = ""
            try:
                link_el = item.locator(SELECTORS["link"][0]).first
                href = link_el.get_attribute("href") or ""
            except Exception:
                pass
            article_url = (
                href if href.startswith("http")
                else f"{self.BASE_URL}{href}" if href
                else ""
            )

            # Data
            date_text = self._get_text(item, SELECTORS["date"])
            # Tenta tambem o atributo datetime do elemento time
            if not date_text:
                try:
                    date_text = item.locator("time").first.get_attribute("datetime") or ""
                except Exception:
                    pass
            date_obj = self._parse_date(date_text) if date_text else None

            # Descricao (campo opcional)
            description = self._get_text(item, SELECTORS["description"]) or ""

            # Imagem (campo opcional)
            image_url = self._get_image_url(item) or ""

            return {
                "title":       title.strip(),
                "date":        date_obj.strftime("%Y-%m-%d") if date_obj else (date_text or "").strip(),
                "description": description.strip(),
                "image_url":   image_url,
                "article_url": article_url,
                "_date_obj":   date_obj,
            }

        except Exception as e:
            logger.debug(f"Erro ao extrair dados do artigo: {e}")
            return None

    # =========================================================================
    # Paginacao
    # =========================================================================

    def _click_show_more(self) -> bool:
        for selector in SELECTORS["show_more"]:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.scroll_into_view_if_needed()
                    self.page.wait_for_timeout(500)
                    btn.click()
                    logger.debug("Botao 'Show More' clicado.")
                    return True
            except Exception:
                continue
        return False

    # =========================================================================
    # Helpers de extracao
    # =========================================================================

    def _find_element(self, selectors: List[str]):
        for selector in selectors:
            try:
                el = self.page.locator(selector).first
                if el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    def _get_text(self, parent, selectors: List[str]) -> Optional[str]:
        for selector in selectors:
            try:
                el = parent.locator(selector).first
                text = el.text_content(timeout=2000)
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return None

    def _get_image_url(self, parent) -> Optional[str]:
        for selector in SELECTORS["image"]:
            try:
                img = parent.locator(selector).first
                src = img.get_attribute("src", timeout=2000)
                if src and src.startswith("http"):
                    return src
                srcset = img.get_attribute("srcset", timeout=1000)
                if srcset:
                    return self._parse_srcset(srcset)
            except Exception:
                continue
        return None

    def _parse_srcset(self, srcset: str) -> Optional[str]:
        try:
            entries = [e.strip().split() for e in srcset.split(",") if e.strip()]
            with_width = [
                (int(e[1].rstrip("w")) if len(e) > 1 and e[1].endswith("w") else 0, e[0])
                for e in entries
            ]
            with_width.sort(reverse=True)
            return with_width[0][1] if with_width else None
        except Exception:
            return None

    # =========================================================================
    # Parsing de data
    # =========================================================================

    def _parse_date(self, date_text: str) -> Optional[date]:
        if not date_text:
            return None

        date_text = date_text.strip()

        # ISO: "2024-05-13" ou "2024-05-13T10:30:00Z"
        iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", date_text)
        if iso_match:
            try:
                return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Textual: "May 13, 2024" / "May. 13, 2024"
        for fmt in ["%B %d, %Y", "%b. %d, %Y", "%b %d, %Y"]:
            try:
                return datetime.strptime(date_text, fmt).date()
            except ValueError:
                continue

        # Relativo: "2h ago", "3 days ago", "1 week ago"
        today = date.today()
        rel = re.search(r"(\d+)\s*(h|hour|min|minute|day|week)s?\s*ago", date_text, re.I)
        if rel:
            amount = int(rel.group(1))
            unit   = rel.group(2).lower()
            if unit in ("h", "hour", "min", "minute"):
                return today
            if unit == "day":
                return today - timedelta(days=amount)
            if unit == "week":
                return today - timedelta(weeks=amount)

        logger.debug(f"Nao foi possivel parsear a data: '{date_text}'")
        return None
