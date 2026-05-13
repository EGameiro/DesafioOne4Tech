"""
framework/end_process.py
-------------------------
Estado de FIM DE PROCESSO do REFramework.

Responsabilidades:
  - Fechar o browser e encerrar o Playwright
  - Finalizar e salvar o arquivo Excel
  - Exibir sumario da execucao nos logs
  - Garantir limpeza mesmo em caso de erro (finally)
"""

import logging
from .initialization import ExecutionContext


class EndProcessState:
    """
    Implementa o estado de End Process do REFramework.

    Uso:
        EndProcessState(ctx).run()
    """

    def __init__(self, ctx: ExecutionContext):
        self.ctx = ctx
        self.logger = logging.getLogger("nytimes_scraper.end_process")

    def run(self, success: bool = True) -> None:
        """
        Executa todas as etapas de finalizacao.

        Args:
            success: indica se o processo terminou normalmente (True) ou por erro (False).
        """
        self.logger.info("=" * 60)
        self.logger.info("Iniciando finalizacao do processo...")

        try:
            self._finalize_excel()
        except Exception as e:
            self.logger.error(f"Erro ao finalizar Excel: {e}", exc_info=True)

        try:
            self._close_browser()
        except Exception as e:
            self.logger.error(f"Erro ao fechar browser: {e}", exc_info=True)

        self._log_summary(success)

    def _close_browser(self) -> None:
        """Fecha o browser e encerra o Playwright de forma segura."""
        if self.ctx.browser is not None:
            try:
                self.ctx.browser.close()
                self.logger.info("Browser fechado com sucesso.")
            except Exception as e:
                self.logger.warning(f"Erro ao fechar o browser: {e}")

        if self.ctx.playwright is not None:
            try:
                self.ctx.playwright.stop()
                self.logger.info("Playwright encerrado com sucesso.")
            except Exception as e:
                self.logger.warning(f"Erro ao encerrar o Playwright: {e}")

        if self.ctx.browser is None and self.ctx.playwright is None:
            self.logger.debug("Browser/Playwright nao estavam inicializados.")

    def _finalize_excel(self) -> None:
        """Salva o arquivo Excel se o ExcelHandler foi inicializado."""
        if self.ctx.excel_handler is not None:
            self.ctx.excel_handler.save()
        else:
            self.logger.warning(
                "ExcelHandler nao foi inicializado - "
                "nenhum artigo foi processado ou houve falha antes do processamento."
            )

    def _log_summary(self, success: bool) -> None:
        """Exibe o resumo da execucao nos logs."""
        status = "CONCLUIDO COM SUCESSO" if success else "ENCERRADO COM ERRO"
        self.logger.info("=" * 60)
        self.logger.info(f"PROCESSO {status}")
        self.logger.info(f"  Itens processados : {self.ctx.processed_count}")
        self.logger.info(f"  Itens com falha   : {self.ctx.failed_count}")
        self.logger.info(f"  Retentativas      : {self.ctx.retry_count}")
        self.logger.info("=" * 60)
