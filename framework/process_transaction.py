"""
framework/process_transaction.py
---------------------------------
Estado de PROCESSAMENTO DE TRANSACAO do REFramework.

Responsabilidades:
  - Receber um item de transacao (noticia) e processa-lo completamente:
      1. Validar os campos minimos obrigatorios (BusinessRuleException se invalido)
      2. Normalizar titulo, data e descricao
      3. Fazer download da imagem da noticia
      4. Contar ocorrencias da frase de pesquisa no titulo e descricao
      5. Detectar mencoes a valores monetarios
      6. Gravar os dados no arquivo Excel

Tipos de excecao:
  BusinessRuleException  -> item invalido (sem titulo), sem retry
  SystemException        -> falha critica de I/O, aborta processo
  Exception              -> falha transiente, main.py faz retry
"""

import logging
from typing import Optional

from .initialization import ExecutionContext
from .exceptions import BusinessRuleException, SystemException
from utils.excel_handler import ExcelHandler
from utils.image_downloader import ImageDownloader
from utils.money_detector import MoneyDetector


class ProcessTransactionState:
    """
    Implementa o estado de Process Transaction do REFramework.

    O ExcelHandler e inicializado apenas uma vez (lazy init) e reutilizado
    para todos os artigos. ImageDownloader e MoneyDetector sao stateless.
    """

    def __init__(self, ctx: ExecutionContext):
        self.ctx = ctx
        self.logger = logging.getLogger("nytimes_scraper.process_transaction")
        self._image_downloader = ImageDownloader(ctx.config)
        self._money_detector   = MoneyDetector()

    def process(self, transaction: dict) -> None:
        """
        Processa um unico item de noticia de ponta a ponta.

        Args:
            transaction: dict com title, date, description, image_url, article_url

        Raises:
            BusinessRuleException: item sem titulo (nao processavel, sem retry).
            SystemException: falha critica ao gravar Excel.
            Exception: falha transiente (main.py fara retry).
        """
        title = (transaction.get("title") or "").strip()

        # Validacao de regra de negocio: artigo sem titulo nao e processavel
        if not title:
            raise BusinessRuleException(
                "Artigo sem titulo - nao processavel (regra de negocio)."
            )

        self.logger.info(f"Processando: '{title[:80]}'")

        # 1. Garante que o ExcelHandler esta pronto
        self._ensure_excel_ready()

        # 2. Normaliza os campos
        date        = (transaction.get("date") or "").strip()
        description = (transaction.get("description") or "").strip()
        image_url   = (transaction.get("image_url") or "").strip()

        # 3. Download da imagem (falha aqui nao e critica - retorna string vazia)
        image_filename = self._download_image(image_url, title)

        # 4. Contagem da frase de pesquisa
        search_phrase_count = self._count_search_phrase(title, description)

        # 5. Deteccao de valores monetarios
        contains_money = self._check_for_money(title, description)

        # 6. Monta o registro
        row_data = {
            "title":               title,
            "date":                date,
            "description":         description,
            "image_filename":      image_filename,
            "search_phrase_count": search_phrase_count,
            "contains_money":      contains_money,
        }

        # 7. Grava no Excel (falha aqui e critica)
        self._write_to_excel(row_data)

        self.logger.debug(
            f"  title   : {title[:60]}\n"
            f"  date    : {date}\n"
            f"  image   : {image_filename or '(sem imagem)'}\n"
            f"  count   : {search_phrase_count}\n"
            f"  money   : {contains_money}"
        )

        self.ctx.processed_count += 1

    # -----------------------------------------------------------------------
    # Excel - lazy init
    # -----------------------------------------------------------------------

    def _ensure_excel_ready(self) -> None:
        if self.ctx.excel_handler is None:
            try:
                handler = ExcelHandler(self.ctx.config)
                handler.initialize()
                self.ctx.excel_handler = handler
                self.logger.info("ExcelHandler inicializado.")
            except Exception as e:
                raise SystemException(
                    f"Falha ao inicializar o ExcelHandler: {e}"
                ) from e

    # -----------------------------------------------------------------------
    # Download de imagem
    # -----------------------------------------------------------------------

    def _download_image(self, image_url: Optional[str], title: str) -> str:
        try:
            return self._image_downloader.download(image_url, title)
        except Exception as e:
            self.logger.warning(f"Falha ao baixar imagem (ignorando): {e}")
            return ""

    # -----------------------------------------------------------------------
    # Contagem da frase de pesquisa
    # -----------------------------------------------------------------------

    def _count_search_phrase(self, title: str, description: str) -> int:
        phrase = self.ctx.config.scraper.search_phrase.lower()
        if not phrase:
            return 0
        combined = f"{title} {description}".lower()
        return combined.count(phrase)

    # -----------------------------------------------------------------------
    # Deteccao de dinheiro
    # -----------------------------------------------------------------------

    def _check_for_money(self, title: str, description: str) -> bool:
        return self._money_detector.contains_money(f"{title} {description}")

    # -----------------------------------------------------------------------
    # Escrita no Excel
    # -----------------------------------------------------------------------

    def _write_to_excel(self, data: dict) -> None:
        try:
            self.ctx.excel_handler.append_row(data)
        except Exception as e:
            raise SystemException(
                f"Falha critica ao gravar no Excel: {e}"
            ) from e
