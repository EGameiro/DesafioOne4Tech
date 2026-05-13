"""
utils/money_detector.py
------------------------
Detecta mencoes a valores monetarios em textos.

Formatos suportados (conforme especificacao do desafio):
  - $11,1
  - US$ 111.111,11
  - 11 dollars
  - 11 dolares
"""

import re
import logging
from typing import List

logger = logging.getLogger("nytimes_scraper.money_detector")

# ---------------------------------------------------------------------------
# Padroes Regex compilados
# ---------------------------------------------------------------------------

# Padrao 1: Simbolo $ ou R$ seguido de valor numerico
_PATTERN_DOLLAR_SIGN = re.compile(
    r'(?:R\$|\$)\s*[\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?',
    re.IGNORECASE,
)

# Padrao 2: Prefixo US$ / USD seguido de valor numerico
_PATTERN_USD_PREFIX = re.compile(
    r'US\$?\s*[\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?'
    r'|USD\s*[\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?',
    re.IGNORECASE,
)

# Padrao 3: Numero seguido de "dollar(s)" ou "dolar(es)"
_PATTERN_WORD_DOLLAR = re.compile(
    r'[\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s+(?:dollars?|d[o\xf3]lares?)',
    re.IGNORECASE,
)

# Padrao 4: Valor por extenso + "dollars"
_PATTERN_WRITTEN_AMOUNT = re.compile(
    r'(?:\d+\s+)?'
    r'(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|'
    r'thirty|forty|fifty|sixty|seventy|eighty|ninety|'
    r'hundred|thousand|million|billion|trillion)'
    r'(?:\s+(?:and\s+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|'
    r'hundred|thousand|million|billion|trillion))*'
    r'\s+dollars?',
    re.IGNORECASE,
)

_MONEY_PATTERNS: List[re.Pattern] = [
    _PATTERN_DOLLAR_SIGN,
    _PATTERN_USD_PREFIX,
    _PATTERN_WORD_DOLLAR,
    _PATTERN_WRITTEN_AMOUNT,
]


class MoneyDetector:
    """
    Detecta mencoes a valores monetarios em textos.

    Uso:
        detector = MoneyDetector()
        result = detector.contains_money("Bitcoin fell below $30,000 today.")
        # result -> True
    """

    def contains_money(self, text: str) -> bool:
        """
        Verifica se o texto contem alguma mencao a valor monetario.

        Args:
            text: String a ser analisada (titulo + descricao, geralmente).

        Returns:
            True se encontrado, False caso contrario.
        """
        if not text:
            return False

        for pattern in _MONEY_PATTERNS:
            if pattern.search(text):
                logger.debug(f"Valor monetario detectado.")
                return True

        return False

    def find_all(self, text: str) -> List[str]:
        """
        Retorna todas as mencoes monetarias encontradas no texto.

        Args:
            text: String a ser analisada.

        Returns:
            Lista com todas as correspondencias encontradas.
        """
        if not text:
            return []

        matches = []
        for pattern in _MONEY_PATTERNS:
            found = pattern.findall(text)
            matches.extend(found)

        return matches


if __name__ == "__main__":
    detector = MoneyDetector()

    test_cases = [
        ("Stocks fell after Fed raised rates", False),
        ("Bitcoin dropped to $30,000", True),
        ("Deal worth US$ 111.111,11 announced", True),
        ("Company raised 5 million dollars", True),
        ("Price is 50 dolares per share", True),
        ("Economy grew 2.3% last quarter", False),
        ("The $ sign alone is not money", False),
        ("USD500 deal closed today", True),
        ("She earned 1 dollar for the task", True),
        ("Cost: $11,1 per unit", True),
        ("Revenue reached two billion dollars", True),
        ("R$1.500,00 investidos", True),
    ]

    print("=== Testes do MoneyDetector ===\n")
    passed = 0
    for text, expected in test_cases:
        result = detector.contains_money(text)
        status = "OK" if result == expected else "FALHOU"
        if result == expected:
            passed += 1
        print(f"  {status} [{str(expected):5}] -> '{text}'")
        if result != expected:
            print(f"          Obtido: {result}")

    print(f"\nResultado: {passed}/{len(test_cases)} testes passaram.")
