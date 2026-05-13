"""
framework/get_transaction.py
-----------------------------
Estado de OBTENCAO DE TRANSACAO do REFramework.

Responsabilidades:
  - Calcular o intervalo de datas com base no parametro `months`
  - Usar NYTimesScraper para coletar todas as noticias do periodo
  - Retornar cada noticia como uma unidade de trabalho para ProcessTransaction
  - Retornar None quando nao ha mais transacoes (sinaliza fim do processo)

Excecoes:
  NoTransactionsFound  -> nenhum artigo no periodo (main.py encerra normalmente)
  BrowserException     -> browser inacessivel (SystemException - main.py aborta)
"""

import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Optional

from .initialization import ExecutionContext
from .exceptions import NoTransactionsFound, BrowserException, SystemException
from utils.nytimes_scraper import NYTimesScraper


class GetTransactionState:
    """
    Implementa o estado de Get Transaction Item do REFramework.

    Uso:
        state = GetTransactionState(ctx)
        item  = state.get_next()   # None quando nao ha mais itens
    """

    def __init__(self, ctx: ExecutionContext):
        self.ctx    = ctx
        self.logger = logging.getLogger("nytimes_scraper.get_transaction")
        self._fetched = False

    def get_next(self) -> Optional[dict]:
        """
        Retorna o proximo item de transacao (noticia) a ser processado.

        Na primeira chamada, aciona a coleta completa no NYTimes.
        Nas chamadas seguintes, retira itens da fila (FIFO).

        Returns:
            dict com os dados da noticia, ou None se a fila estiver vazia.

        Raises:
            NoTransactionsFound : nenhum artigo encontrado para os parametros.
            BrowserException    : browser inacessivel durante a coleta.
            SystemException     : erro de sistema nao recuperavel.
        """
        if not self._fetched:
            self._fetched = True
            self.logger.info("Primeira chamada - iniciando coleta no NYTimes...")
            self._fetch_all_transactions()

        if not self.ctx.transactions:
            self.logger.info("Fila de transacoes vazia. Processo encerrado.")
            return None

        item = self.ctx.transactions.pop(0)
        remaining = len(self.ctx.transactions)
        self.logger.info(
            f"Proximo item: '{item.get('title', 'sem titulo')[:70]}' "
            f"(restam {remaining})"
        )
        return item

    # -----------------------------------------------------------------------
    # Coleta de artigos
    # -----------------------------------------------------------------------

    def _fetch_all_transactions(self) -> None:
        """
        Usa NYTimesScraper para buscar todos os artigos no periodo configurado
        e popula self.ctx.transactions.

        Raises:
            NoTransactionsFound : propagada do NYTimesScraper.
            BrowserException    : propagada do NYTimesScraper.
            SystemException     : wraps erros inesperados de sistema.
        """
        start_date, end_date = self._calculate_date_range()

        self.logger.info(f"Periodo: {start_date} -> {end_date}")
        self.logger.info(
            f"Categorias: {self.ctx.config.scraper.categories or ['(sem filtro)']}"
        )

        try:
            scraper  = NYTimesScraper(config=self.ctx.config, page=self.ctx.page)
            articles = scraper.search_and_collect(start_date=start_date, end_date=end_date)

        except (NoTransactionsFound, BrowserException):
            raise   # Propaga sem wrap

        except Exception as e:
            raise SystemException(
                f"Erro inesperado durante coleta de transacoes: {e}"
            ) from e

        self.logger.info(f"{len(articles)} artigo(s) carregado(s) na fila.")
        self.ctx.transactions = articles

    # -----------------------------------------------------------------------
    # Calculo do periodo
    # -----------------------------------------------------------------------

    def _calculate_date_range(self) -> tuple:
        """
        Calcula o intervalo de datas com base em `months`.

          months <= 1  ->  1 dia do mes atual ate hoje
          months = 2   ->  mes atual + mes anterior
          months = N   ->  mes atual + N-1 meses anteriores
        """
        today    = date.today()
        end_date = today
        months   = self.ctx.config.scraper.months

        if months <= 1:
            start_date = today.replace(day=1)
        else:
            start_date = (today - relativedelta(months=months - 1)).replace(day=1)

        return start_date, end_date
