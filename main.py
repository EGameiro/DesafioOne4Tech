"""
main.py
-------
Ponto de entrada da aplicacao -- implementa a maquina de estados do REFramework.

Fluxo de estados:
  INITIALIZATION -> GET TRANSACTION -> PROCESS TRANSACTION -> END PROCESS

Tratamento de excecoes por tipo:
  SystemException        -> aborta o processo imediatamente (sem retry)
  BusinessRuleException  -> descarta o item (sem retry), continua para o proximo
  Exception generica     -> retry ate max_retries; se esgotar, descarta o item

Uso:
  python main.py
  python main.py --config config/config.yaml
  python main.py --validate
"""

import argparse
import logging
import sys
import time

from framework import (
    InitializationState,
    GetTransactionState,
    ProcessTransactionState,
    EndProcessState,
    SystemException,
    BusinessRuleException,
    NoTransactionsFound,
)

logger = logging.getLogger("nytimes_scraper.main")


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Executa o processo completo seguindo a arquitetura REFramework.

    Returns:
        0 em caso de sucesso, 1 em caso de erro de sistema.
    """
    args = _parse_args()

    # Modo de validacao: roda validate.py e sai
    if args.validate:
        return _run_validation()

    ctx = None
    success = True

    # =========================================================================
    # ESTADO 1: INITIALIZATION
    # =========================================================================
    try:
        logger.info("Estado: INITIALIZATION")
        ctx = InitializationState(config_path=args.config).run()

    except SystemException as e:
        logger.critical(f"[INITIALIZATION] SystemException: {e}", exc_info=True)
        return 1

    except Exception as e:
        logger.critical(f"[INITIALIZATION] Falha inesperada: {e}", exc_info=True)
        return 1

    # =========================================================================
    # ESTADOS 2 e 3: GET TRANSACTION -> PROCESS TRANSACTION (loop)
    # =========================================================================
    get_state     = GetTransactionState(ctx)
    process_state = ProcessTransactionState(ctx)
    max_retries   = ctx.config.framework.max_retries
    retry_delay   = ctx.config.framework.retry_delay_seconds

    try:
        transaction_number = 0

        while True:
            # -----------------------------------------------------------------
            # ESTADO 2: GET TRANSACTION ITEM
            # -----------------------------------------------------------------
            logger.info("Estado: GET TRANSACTION ITEM")

            try:
                transaction = get_state.get_next()
            except NoTransactionsFound:
                logger.info("Nenhum artigo encontrado para os parametros configurados.")
                break
            except SystemException as e:
                logger.critical(f"[GET TRANSACTION] SystemException: {e}", exc_info=True)
                success = False
                break
            except Exception as e:
                logger.error(f"[GET TRANSACTION] Erro inesperado: {e}", exc_info=True)
                success = False
                break

            if transaction is None:
                logger.info("Sem mais transacoes. Encerrando loop.")
                break

            transaction_number += 1
            logger.info(f"--- Transacao #{transaction_number} ---")

            # -----------------------------------------------------------------
            # ESTADO 3: PROCESS TRANSACTION (com retry para Application Exceptions)
            # -----------------------------------------------------------------
            logger.info("Estado: PROCESS TRANSACTION")
            ctx.retry_count = 0

            while True:
                try:
                    process_state.process(transaction)
                    break  # Sucesso -- passa para a proxima transacao

                except SystemException as e:
                    # Erro de sistema: aborta tudo
                    logger.critical(f"[PROCESS] SystemException: {e}", exc_info=True)
                    success = False
                    raise  # Propaga para o bloco externo

                except BusinessRuleException as e:
                    # Regra de negocio violada: descarta sem retry
                    logger.warning(
                        f"[PROCESS] BusinessRuleException (sem retry): {e}"
                    )
                    ctx.failed_count += 1
                    break

                except Exception as e:
                    ctx.retry_count += 1
                    if ctx.retry_count <= max_retries:
                        logger.warning(
                            f"[PROCESS] Tentativa {ctx.retry_count}/{max_retries} "
                            f"falhou: {e}. Aguardando {retry_delay}s..."
                        )
                        time.sleep(retry_delay)
                    else:
                        logger.error(
                            f"[PROCESS] Item descartado apos {max_retries} tentativas: "
                            f"'{transaction.get('title', 'N/A')[:60]}'"
                        )
                        ctx.failed_count += 1
                        break

    except SystemException:
        success = False  # Ja logado acima

    except Exception as e:
        logger.critical(f"Erro inesperado no loop principal: {e}", exc_info=True)
        success = False

    finally:
        # =====================================================================
        # ESTADO 4: END PROCESS (sempre executado)
        # =====================================================================
        if ctx is not None:
            logger.info("Estado: END PROCESS")
            EndProcessState(ctx).run(success=success)

    return 0 if success else 1


# ---------------------------------------------------------------------------
# Modo de validacao
# ---------------------------------------------------------------------------

def _run_validation() -> int:
    """Executa o script de validacao e retorna o codigo de saida."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "validate.py"],
        capture_output=False,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NYTimes News Scraper -- Desafio Tecnico One4Tech",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python main.py\n"
            "  python main.py --config config/config.yaml\n"
            "  python main.py --validate\n"
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Caminho para o arquivo config.yaml (padrao: config/config.yaml)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Executa a suite de validacao sem iniciar o browser",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
