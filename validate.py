"""
validate.py
-----------
Suite de validacao do NYTimes Scraper -- executa SEM browser.

Testa todos os componentes que podem ser verificados localmente:
  1. Config Loader      -- carrega e valida config.yaml
  2. MoneyDetector      -- todos os formatos de dinheiro suportados
  3. ExcelHandler       -- criacao, escrita, salvamento e verificacao do arquivo
  4. ImageDownloader    -- sanitizacao de nomes de arquivo e parsing de extensao
  5. Date Range         -- calculo de periodo por numero de meses
  6. Exception hierarchy -- heranca correta das excecoes do REFramework

Uso:
  python validate.py
  python main.py --validate
"""

import sys
import os
import traceback
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Garante que a raiz do projeto esta no PYTHONPATH
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Controle de resultado
# ---------------------------------------------------------------------------

_results = []   # (nome, passou, mensagem_erro)


def test(name: str):
    """Decorador que registra o resultado de cada teste."""
    def decorator(fn):
        def wrapper():
            try:
                fn()
                _results.append((name, True, ""))
                print(f"  OK  {name}")
            except AssertionError as e:
                _results.append((name, False, str(e)))
                print(f"  FAIL {name}")
                print(f"       {e}")
            except Exception as e:
                _results.append((name, False, f"{type(e).__name__}: {e}"))
                print(f"  ERR  {name}")
                print(f"       {type(e).__name__}: {e}")
                traceback.print_exc()
        return wrapper
    return decorator


# ===========================================================================
# 1. Config Loader
# ===========================================================================

@test("Config: carrega config.yaml sem erro")
def test_config_loads():
    from config import load_config
    cfg = load_config()
    assert cfg is not None, "load_config() retornou None"

@test("Config: search_phrase nao vazio")
def test_config_search_phrase():
    from config import load_config
    cfg = load_config()
    assert cfg.scraper.search_phrase.strip(), "search_phrase esta vazio"

@test("Config: months >= 0")
def test_config_months():
    from config import load_config
    cfg = load_config()
    assert cfg.scraper.months >= 0, f"months invalido: {cfg.scraper.months}"

@test("Config: categories e lista (pode ser vazia)")
def test_config_categories():
    from config import load_config
    cfg = load_config()
    assert isinstance(cfg.scraper.categories, list), "categories deve ser list"

@test("Config: rejeita arquivo inexistente com FileNotFoundError")
def test_config_missing_file():
    from config import load_config
    try:
        load_config("/caminho/inexistente/config.yaml")
        assert False, "Deveria ter lancado FileNotFoundError"
    except FileNotFoundError:
        pass  # esperado


# ===========================================================================
# 2. MoneyDetector
# ===========================================================================

@test("MoneyDetector: detecta $ com valor numerico")
def test_money_dollar_sign():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    assert d.contains_money("Bitcoin at $30,000") is True
    assert d.contains_money("Cost: $11,1 per unit") is True

@test("MoneyDetector: detecta US$ e USD")
def test_money_usd():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    assert d.contains_money("Deal worth US$ 111.111,11") is True
    assert d.contains_money("USD500 deal closed") is True

@test("MoneyDetector: detecta 'dollars' como palavra")
def test_money_word_dollars():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    assert d.contains_money("She earned 1 dollar") is True
    assert d.contains_money("50 dolares por acao") is True

@test("MoneyDetector: detecta valores por extenso")
def test_money_written():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    assert d.contains_money("Company raised 5 million dollars") is True
    assert d.contains_money("Revenue: two billion dollars") is True

@test("MoneyDetector: nao detecta falsos positivos")
def test_money_false_positives():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    assert d.contains_money("Economy grew 2.3%") is False
    assert d.contains_money("The $ sign alone") is False
    assert d.contains_money("Stocks fell after Fed raised rates") is False

@test("MoneyDetector: find_all retorna lista de matches")
def test_money_find_all():
    from utils.money_detector import MoneyDetector
    d = MoneyDetector()
    matches = d.find_all("Prices rose $30 and USD50 in one day")
    assert len(matches) >= 2, f"Esperado >= 2 matches, obtido {len(matches)}: {matches}"


# ===========================================================================
# 3. ExcelHandler
# ===========================================================================

_EXCEL_TEST_PATH = Path("/tmp") / "_validate_test.xlsx"

@test("ExcelHandler: inicializa workbook sem erro")
def test_excel_initialize():
    from utils.excel_handler import ExcelHandler
    from config import load_config
    cfg = load_config()
    h = ExcelHandler(cfg)
    h.initialize()
    assert h._workbook is not None, "Workbook nao foi criado"
    assert h._worksheet is not None, "Worksheet nao foi criada"
    assert h._row_index == 2, "row_index inicial deve ser 2"

@test("ExcelHandler: append_row adiciona dados corretamente")
def test_excel_append():
    from utils.excel_handler import ExcelHandler, COLUMNS
    from config import load_config
    cfg = load_config()
    h = ExcelHandler(cfg)
    h.initialize()

    sample = {
        "title":               "AI Reshapes the Newsroom",
        "date":                "2024-05-13",
        "description":         "How artificial intelligence is changing journalism.",
        "image_filename":      "AI_Reshapes_the_Newsroom.jpg",
        "search_phrase_count": 2,
        "contains_money":      False,
    }
    h.append_row(sample)
    assert h._row_index == 3, f"row_index esperado 3, obtido {h._row_index}"

    cell_title = h._worksheet.cell(row=2, column=1).value
    assert cell_title == sample["title"], f"Titulo incorreto: {cell_title}"

@test("ExcelHandler: save cria arquivo em disco")
def test_excel_save():
    from utils.excel_handler import ExcelHandler
    from config import load_config
    import pydantic

    cfg = load_config()

    # Sobrescreve output_path para arquivo temporario de teste
    h = ExcelHandler(cfg)
    h.output_path = _EXCEL_TEST_PATH
    h.initialize()
    h.append_row({
        "title": "Validate Test",
        "date": "2024-01-01",
        "description": "Test row",
        "image_filename": "test.jpg",
        "search_phrase_count": 1,
        "contains_money": True,
    })
    h.save()

    assert _EXCEL_TEST_PATH.exists(), f"Arquivo Excel nao foi criado em {_EXCEL_TEST_PATH}"
    size = _EXCEL_TEST_PATH.stat().st_size
    assert size > 0, "Arquivo Excel esta vazio"

@test("ExcelHandler: arquivo de teste removido apos validacao")
def test_excel_cleanup():
    if _EXCEL_TEST_PATH.exists():
        _EXCEL_TEST_PATH.unlink()
    assert not _EXCEL_TEST_PATH.exists(), "Arquivo de teste nao foi removido"


# ===========================================================================
# 4. ImageDownloader
# ===========================================================================

@test("ImageDownloader: sanitiza nomes com caracteres especiais")
def test_image_sanitize():
    from utils.image_downloader import ImageDownloader
    from config import load_config
    cfg = load_config()
    d = ImageDownloader(cfg)

    cases = [
        ("Hello World!", "Hello_World.jpg"),
        ("A/B testing: results?", "AB_testing_results.jpg"),
        ("   spaces   ", "spaces.jpg"),
        ("", "image.jpg"),
    ]
    for title, expected in cases:
        result = d._sanitize_filename(title, ".jpg")
        assert result == expected, f"'{title}' -> esperado '{expected}', obtido '{result}'"

@test("ImageDownloader: extrai extensao correta da URL")
def test_image_extension():
    from utils.image_downloader import ImageDownloader
    from config import load_config
    cfg = load_config()
    d = ImageDownloader(cfg)

    assert d._get_extension_from_url("https://cdn.nytimes.com/photo.jpg?quality=75") == ".jpg"
    assert d._get_extension_from_url("https://cdn.nytimes.com/photo.png") == ".png"
    assert d._get_extension_from_url("https://cdn.nytimes.com/photo.webp") == ".webp"
    assert d._get_extension_from_url("https://cdn.nytimes.com/no-ext") == ".jpg"

@test("ImageDownloader: retorna string vazia para URL invalida")
def test_image_invalid_url():
    from utils.image_downloader import ImageDownloader
    from config import load_config
    cfg = load_config()
    d = ImageDownloader(cfg)

    assert d.download("", "any title") == ""
    assert d.download(None, "any title") == ""
    assert d.download("not-a-url", "any title") == ""


# ===========================================================================
# 5. Date Range (GetTransactionState._calculate_date_range)
# ===========================================================================

@test("DateRange: months=1 -> inicio do mes atual")
def test_date_months_1():
    from framework.get_transaction import GetTransactionState
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.config.scraper.months = 1
    state = GetTransactionState(ctx)

    start, end = state._calculate_date_range()
    today = date.today()
    assert start == today.replace(day=1), f"start errado: {start}"
    assert end   == today,               f"end errado: {end}"

@test("DateRange: months=0 -> mesmo comportamento que months=1")
def test_date_months_0():
    from framework.get_transaction import GetTransactionState
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.config.scraper.months = 0
    state = GetTransactionState(ctx)

    start, end = state._calculate_date_range()
    today = date.today()
    assert start == today.replace(day=1)

@test("DateRange: months=3 -> inicio de 2 meses atras")
def test_date_months_3():
    from framework.get_transaction import GetTransactionState
    from dateutil.relativedelta import relativedelta
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.config.scraper.months = 3
    state = GetTransactionState(ctx)

    start, end = state._calculate_date_range()
    today    = date.today()
    expected = (today - relativedelta(months=2)).replace(day=1)
    assert start == expected, f"start esperado {expected}, obtido {start}"

@test("DateRange: start_date <= end_date sempre")
def test_date_order():
    from framework.get_transaction import GetTransactionState
    from unittest.mock import MagicMock

    for months in [0, 1, 2, 6, 12]:
        ctx = MagicMock()
        ctx.config.scraper.months = months
        state = GetTransactionState(ctx)
        start, end = state._calculate_date_range()
        assert start <= end, f"months={months}: start {start} > end {end}"


# ===========================================================================
# 6. Exception hierarchy
# ===========================================================================

@test("Exceptions: SystemException e subclasse de ScraperBaseException")
def test_exc_system():
    from framework.exceptions import SystemException, ScraperBaseException
    assert issubclass(SystemException, ScraperBaseException)
    assert issubclass(SystemException, Exception)

@test("Exceptions: BusinessRuleException e subclasse de ScraperBaseException")
def test_exc_business():
    from framework.exceptions import BusinessRuleException, ScraperBaseException
    assert issubclass(BusinessRuleException, ScraperBaseException)

@test("Exceptions: BrowserException e subclasse de SystemException")
def test_exc_browser():
    from framework.exceptions import BrowserException, SystemException
    assert issubclass(BrowserException, SystemException)

@test("Exceptions: ConfigurationException e subclasse de SystemException")
def test_exc_config():
    from framework.exceptions import ConfigurationException, SystemException
    assert issubclass(ConfigurationException, SystemException)

@test("Exceptions: NoTransactionsFound e subclasse de ScraperBaseException")
def test_exc_no_transactions():
    from framework.exceptions import NoTransactionsFound, ScraperBaseException
    assert issubclass(NoTransactionsFound, ScraperBaseException)


# ===========================================================================
# Runner
# ===========================================================================

def run_all():
    tests = [
        # Config
        test_config_loads,
        test_config_search_phrase,
        test_config_months,
        test_config_categories,
        test_config_missing_file,
        # MoneyDetector
        test_money_dollar_sign,
        test_money_usd,
        test_money_word_dollars,
        test_money_written,
        test_money_false_positives,
        test_money_find_all,
        # ExcelHandler
        test_excel_initialize,
        test_excel_append,
        test_excel_save,
        test_excel_cleanup,
        # ImageDownloader
        test_image_sanitize,
        test_image_extension,
        test_image_invalid_url,
        # DateRange
        test_date_months_1,
        test_date_months_0,
        test_date_months_3,
        test_date_order,
        # Exceptions
        test_exc_system,
        test_exc_business,
        test_exc_browser,
        test_exc_config,
        test_exc_no_transactions,
    ]

    print("=" * 60)
    print("NYTimes Scraper -- Suite de Validacao")
    print("=" * 60)

    for t in tests:
        t()

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total  = len(_results)

    print()
    print("=" * 60)
    print(f"Resultado: {passed}/{total} testes passaram", end="")
    if failed:
        print(f"  ({failed} FALHA(S))")
        print()
        print("Falhas:")
        for name, ok, msg in _results:
            if not ok:
                print(f"  - {name}: {msg}")
    else:
        print("  -- TUDO OK")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
   