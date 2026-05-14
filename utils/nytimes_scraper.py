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
        "div[data-testid='search-results']",   # estrutura atual (2025+)
        "ol[data-testid='search-results']",    # fallback estrutura antiga
        "ol.css-1l4spti",
    ],
    "article_item": [
        "div[data-testid='search-bodega-result']",  # estrutura atual (div)
        "li[data-testid='search-bodega-result']",   # fallback estrutura antiga (li)
    ],
    "title": [
        "div[data-tpl='h'] a",             # estrutura atual
        "h4",                               # fallback estrutura antiga
        "a h4",
        "[data-testid='topper-headline']",
    ],
    "link": [
        "div[data-tpl='h'] a",             # estrutura atual (titulo e link juntos)
        "a[href^='/']",
        "a[href^='https://www.nytimes.com']",
    ],
    "date": [
        "span[data-testid='todays-date']",  # estrutura atual
        "div[data-tpl='la'] span",          # fallback por data-tpl
        "span[data-testid='topper-timestamp']",
        "time[datetime]",
        "span[class*='date']",
        "time",
    ],
    "description": [
        "div[data-tpl='bo']",              # estrutura atual
        "p[class*='summary']",             # fallback estrutura antiga
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
        "button[data-testid='search-show-more-button']",  # igual nos dois layouts
        "button:has-text('Show More')",
        "button:has-text('Load More')",
    ],
    "cookie_accept": [
        "#fides-banner .fides-accept-all-button",      # Fides: classe do botao accept
        "#fides-banner button.fides-btn-primary",       # Fides: botao primario
        "#fides-overlay button:has-text('Accept all')", # Fides: por texto
        "#fides-overlay button:has-text('Reject all')", # Fides: rejeitar tambem fecha
        "button[data-testid='Accept all-btn']",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "#complianceOverlay button[class*='accept']",
    ],
    "section_filter_btn": [
        "button#search-sections",                          # estrutura atual (por id)
        "button[aria-label='Section']",                    # fallback por aria-label
        "button[data-testid='search-multiselect-button']", # fallback estrutura antiga
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
            self._dismiss_any_overlay()
            self.page.wait_for_timeout(2000)
            self._dismiss_any_overlay()   # segunda passagem — overlay pode reaparecer

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
            articles = self._filter_by_relevance(articles)

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

    def _filter_by_relevance(self, articles: List[dict]) -> List[dict]:
        """
        Remove artigos onde a frase de busca nao aparece no titulo nem na descricao.
        Isso evita coletar conteudo irrelevante retornado pelo algoritmo do NYTimes.
        """
        phrase = self.config.scraper.search_phrase.lower()
        filtered = []
        for article in articles:
            title       = (article.get("title", "") or "").lower()
            description = (article.get("description", "") or "").lower()
            if phrase in title or phrase in description:
                filtered.append(article)
            else:
                logger.debug(f"Artigo ignorado (frase ausente): {article.get('title', '')[:60]}")

        removed = len(articles) - len(filtered)
        if removed:
            logger.info(f"Filtro de relevancia: {removed} artigos removidos, {len(filtered)} mantidos.")
        return filtered

    # =========================================================================
    # Navegacao
    # =========================================================================

    def _navigate_to_search(self, start_date: date, end_date: date) -> None:
        # Removido dropmab=false que interferia no algoritmo de busca
        params = {
            "query":     self.config.scraper.search_phrase,
            "sort":      "newest",
            "startDate": start_date.strftime("%Y%m%d"),
            "endDate":   end_date.strftime("%Y%m%d"),
        }
        url = f"{self.SEARCH_URL}?{urlencode(params)}"
        logger.info(f"Navegando para: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
        self.page.wait_for_timeout(3000)

        # Aguarda rede estabilizar para garantir carregamento completo em headless
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # continua mesmo se timeout

        # Salva screenshot de debug para inspecionar o que o headless esta vendo
        try:
            self.page.screenshot(path="output/debug_screenshot.png", full_page=False)
            logger.info("Screenshot salvo em output/debug_screenshot.png")
        except Exception:
            pass

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

    def _dismiss_any_overlay(self) -> None:
        """Remove forcadamente qualquer overlay de cookies/privacidade via JavaScript."""
        try:
            self.page.evaluate("""
                () => {
                    // Remove overlay Fides e todos os seus elementos
                    ['#fides-overlay', '#fides-banner', '.fides-modal-overlay',
                     '.fides-overlay', '#complianceOverlay'].forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });
                    // Restaura scroll do body caso esteja bloqueado
                    document.body.style.overflow = '';
                    document.body.style.pointerEvents = '';
                }
            """)
            logger.debug("Overlays removidos via JavaScript.")
        except Exception as e:
            logger.debug(f"_dismiss_any_overlay: {e}")

    def _apply_section_filters(self, categories: List[str]) -> None:
        logger.info(f"Aplicando filtros de secao: {categories}")

        # Aguarda o botao de filtro estar presente e visivel na pagina
        section_btn = None
        for selector in SELECTORS["section_filter_btn"]:
            try:
                self.page.wait_for_selector(selector, timeout=5000)
                el = self.page.locator(selector).first
                if el.is_visible(timeout=2000):
                    section_btn = el
                    break
            except Exception:
                continue

        if section_btn is None:
            logger.warning("Botao de filtro de secao nao encontrado. Pulando filtro.")
            return

        # Remove overlay ANTES de clicar no botao Section
        self._dismiss_any_overlay()

        # Clica via JavaScript para bypassar qualquer overlay remanescente
        try:
            self.page.evaluate("document.querySelector('button#search-sections')?.click()")
        except Exception:
            section_btn.click(force=True)

        # Aguarda o dropdown abrir
        try:
            self.page.wait_for_selector(
                "ul[data-testid='facet-filter-list']", timeout=5000
            )
            self.page.wait_for_timeout(500)
        except Exception:
            logger.warning("Dropdown de secao nao abriu. Pulando filtro.")
            return

        # Remove overlay novamente antes de interagir com as opcoes
        self._dismiss_any_overlay()

        for category in categories:
            self._select_section_option(category)

        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(1500)
        self._wait_for_results()

    def _select_section_option(self, category: str) -> None:
        category_lower = category.lower()
        try:
            # Estrutura atual: ul[data-testid='facet-filter-list'] > li[data-testid='facet-filter-option']
            options = self.page.locator(
                "ul[data-testid='facet-filter-list'] li[data-testid='facet-filter-option']"
            )
            count = options.count()
            for i in range(count):
                option = options.nth(i)
                # Texto fica dentro do <span> dentro do <label>
                text = (option.locator("span").first.text_content() or "").strip().lower()
                if category_lower == text or category_lower in text:
                    checkbox = option.locator("input[data-testid='facet-filter-checkbox']").first
                    if not checkbox.is_checked():
                        # Clica via JS para bypassar overlay
                        self._dismiss_any_overlay()
                        try:
                            self.page.evaluate(
                                f"""document.querySelectorAll(
                                    "li[data-testid='facet-filter-option']"
                                )[{i}]?.click()"""
                            )
                        except Exception:
                            option.click(force=True)
                        self.page.wait_for_timeout(500)
                    logger.info(f"Secao selecionada: '{category}'")
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

            # URL do artigo — na estrutura atual o link e o proprio titulo
            href = ""
            for link_sel in SELECTORS["link"]:
                try:
                    link_el = item.locator(link_sel).first
                    href = link_el.get_attribute("href") or ""
                    if href:
                        break
                except Exception:
                    continue
            article_url = (
                href if href.startswith("http")
                else f"{self.BASE_URL}{href}" if href
                else ""
            )

            # Data — tenta aria-label primeiro (mais completo), depois texto
            date_text = ""
            try:
                date_el = item.locator("span[data-testid='todays-date']").first
                date_text = date_el.get_attribute("aria-label") or date_el.text_content() or ""
            except Exception:
                pass
            if not date_text:
                date_text = self._get_text(item, SELECTORS["date"]) or ""
            # Fallback: atributo datetime do elemento time
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

        # Textual com ano: "May 13, 2024" / "May. 13, 2024"
        for fmt in ["%B %d, %Y", "%b. %d, %Y", "%b %d, %Y"]:
            try:
                return datetime.strptime(date_text, fmt).date()
            except ValueError:
                continue

        # Textual sem ano: "May 13" — assume ano atual
        for fmt in ["%B %d", "%b %d"]:
            try:
                parsed = datetime.strptime(date_text, fmt)
                return parsed.replace(year=date.today().year).date()
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
