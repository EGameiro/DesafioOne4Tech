"""
framework/exceptions.py
------------------------
Hierarquia de excecoes do REFramework.

No padrao REFramework existem dois tipos de excecao:

  SystemException (SE):
    - Problema no ambiente ou infraestrutura (browser caiu, disco cheio,
      rede inacessivel, etc.)
    - O processo deve ser ABORTADO imediatamente.
    - NAO faz retry do item — o problema nao e do item, e do sistema.

  BusinessRuleException (BRE):
    - O item de transacao e invalido ou nao atende uma regra de negocio
      (ex: artigo sem titulo, URL invalida, formato inesperado de data).
    - O item e DESCARTADO sem retry.
    - O processo continua com o proximo item.

  ApplicationException (padrao do main.py):
    - Falha inesperada mas potencialmente transiente (timeout, elemento
      nao encontrado temporariamente, etc.).
    - Faz retry ate max_retries.
    - Se esgotar retries, descarta o item e continua.
"""


class ScraperBaseException(Exception):
    """Base para todas as excecoes do NYTimes Scraper."""
    pass


class SystemException(ScraperBaseException):
    """
    Excecao de sistema — aborta o processo imediatamente.

    Use quando o ambiente estiver comprometido:
      - Browser travado ou encerrado inesperadamente
      - Falha ao inicializar o Playwright
      - Erro de I/O critico (disco cheio, sem permissao)
      - Erro ao salvar o Excel no final
    """
    pass


class BusinessRuleException(ScraperBaseException):
    """
    Excecao de regra de negocio — descarta o item, sem retry.

    Use quando o item de transacao for invalido por natureza:
      - Artigo sem titulo (nao processavel)
      - Data do artigo fora do periodo configurado
      - URL do artigo malformada
      - Conteudo do artigo bloqueado por paywall
    """
    pass


class BrowserException(SystemException):
    """Browser encerrou ou ficou inacessivel durante o processamento."""
    pass


class ConfigurationException(SystemException):
    """Configuracao invalida que impede a execucao do processo."""
    pass


class NoTransactionsFound(ScraperBaseException):
    """
    Nenhum artigo encontrado para os parametros configurados.
    Nao e um erro — o processo termina normalmente com aviso.
    """
    pass
