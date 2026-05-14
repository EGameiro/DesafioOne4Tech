# NYTimes News Scraper — Desafio Técnico One4Tech

Automação de extração de notícias do [New York Times](https://www.nytimes.com) seguindo a arquitetura **REFramework** (Robotic Enterprise Framework). O scraper busca artigos por frase de pesquisa, filtra por categoria e período, baixa imagens e exporta os resultados em Excel.

---

## Funcionalidades

- Busca de notícias no NYTimes por frase, categoria e número de meses
- Download automático das imagens dos artigos
- Contagem de ocorrências da frase de busca em cada artigo
- Detecção de menções a valores monetários (vários formatos)
- Exportação em Excel formatado (`.xlsx`) com zebra striping e cabeçalho destacado
- Arquitetura REFramework com retry automático e 3 tiers de exceção
- Suporte a Docker + WSL2
- **Filtro de relevância**: descarta automaticamente artigos que não contêm a frase de busca no título ou descrição
- **Limpeza automática**: remove imagens e Excel da execução anterior ao iniciar
- **Compatível com a estrutura HTML atual do NYTimes (2025+)**

---

## Estrutura do Projeto

```
nytimes-scraper/
├── config/
│   ├── config.yaml          # Configuração principal (edite aqui)
│   └── config_loader.py     # Carregamento e validação (Pydantic v2)
├── framework/
│   ├── exceptions.py        # Hierarquia de exceções REFramework
│   ├── initialization.py    # Estado: inicializa browser e contexto
│   ├── get_transaction.py   # Estado: coleta todos os artigos do NYTimes
│   ├── process_transaction.py # Estado: processa cada artigo individualmente
│   └── end_process.py       # Estado: salva Excel e fecha o browser
├── utils/
│   ├── nytimes_scraper.py   # Playwright: navegação, extração, paginação
│   ├── excel_handler.py     # openpyxl: criação e formatação do Excel
│   ├── image_downloader.py  # requests: download e sanitização de imagens
│   └── money_detector.py    # Regex: detecção de valores monetários
├── output/                  # Gerado em runtime (Excel + imagens)
│   └── images/
├── logs/                    # Gerado em runtime
├── main.py                  # Entry point — state machine REFramework
├── validate.py              # Suite de testes sem browser (27 testes)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Pré-requisitos

### Execução via Docker (recomendado)
- Docker Desktop ≥ 4.x com WSL2 habilitado, **ou**
- Docker Engine instalado no Ubuntu/WSL2

### Execução local
- Python 3.12+
- `pip install -r requirements.txt`
- `playwright install chromium`

---

## Configuração

Edite `config/config.yaml` antes de executar:

```yaml
scraper:
  search_phrase: "artificial intelligence"   # Frase de busca obrigatória
  categories:                                # Lista de seções (vazio = todas)
    - "Technology"
  months: 2                                  # 0 ou 1 = mês atual; 2 = atual + anterior; etc.

output:
  excel_folder: "output"
  excel_filename: "news_results.xlsx"
  images_folder: "output/images"

browser:
  headless: true       # false para ver o browser durante a execução
  timeout_ms: 30000
  viewport_width: 1366
  viewport_height: 768
  slow_mo_ms: 0

framework:
  max_retries: 3
  retry_delay_seconds: 5
  log_level: "INFO"
```

### Seções disponíveis no NYTimes

As seções aceitas no parâmetro `categories` são:

| Seção | Seção |
|-------|-------|
| `Arts` | `Opinion` |
| `Business` | `Podcasts` |
| `Magazine` | `Science` |
| `Style` | `Technology` |
| `U.S.` | `World` |

> **Nota:** Deixe `categories: []` para buscar em todas as seções sem filtro.

### Filtro de relevância

O scraper descarta automaticamente artigos onde a frase de busca não aparece no título nem na descrição. Isso evita coletar conteúdo irrelevante que o algoritmo do NYTimes possa retornar como fallback. Se nenhum artigo relevante for encontrado no período, nenhuma planilha é gerada.

### Parâmetro `months`

| Valor | Período coletado |
|-------|-----------------|
| `0` ou `1` | Apenas o mês atual (do dia 1 até hoje) |
| `2` | Mês atual + mês anterior |
| `3` | Mês atual + 2 meses anteriores |
| `N` | Mês atual + N-1 meses anteriores |

---

## Execução via Docker (WSL2)

> ⚠️ **Limitação conhecida:** O New York Times utiliza proteção anti-bot avançada (PerimeterX/HUMAN Security) que detecta e bloqueia browsers headless rodando em containers Docker. Isso ocorre porque o ambiente headless possui fingerprint diferente de um browser real (sem GPU, sem tela física, contexto limpo). **Recomenda-se a execução local** para garantir o funcionamento correto do scraper.
>
> O Docker funciona normalmente para rodar a suite de testes (`validate.py`), que não depende de browser.

### Suite de validação via Docker (funciona normalmente)

```bash
docker compose run --rm scraper python validate.py
```

### Execução do scraper via Docker (sujeita a bloqueio do NYTimes)

```bash
# 1ª execução (build da imagem)
docker compose up --build

# Execuções seguintes
docker compose up
```

---

## Execução Local (recomendado)

```bash
# Instalar dependências
pip install -r requirements.txt
playwright install chromium

# Executar
python main.py

# Validar sem browser
python validate.py

# Validar sem executar o scraper completo
python main.py --validate
```

---

## Saídas

Após a execução, os arquivos estarão em `output/`:

```
output/
├── news_results.xlsx        # Planilha com todos os artigos
└── images/
    ├── AI_Reshapes_the_Newsroom.jpg
    ├── ...
```

### Colunas do Excel

| Coluna | Descrição |
|--------|-----------|
| `title` | Título do artigo |
| `date` | Data de publicação (YYYY-MM-DD) |
| `description` | Subtítulo / resumo do artigo |
| `image_filename` | Nome do arquivo de imagem baixado |
| `search_phrase_count` | Nº de ocorrências da frase de busca (título + descrição) |
| `contains_money` | `True` se há menção a valor monetário |

### Formatos de dinheiro detectados

- `$11,100` / `$11.100,50`
- `US$ 111.111,11` / `USD 1,000`
- `11 dollars` / `11 dólares`
- `five million dollars` / `billion dollars`

---

## Arquitetura REFramework

```
Initialization
    │
    ▼
Get Transaction ──(sem artigos)──► End Process
    │
    │ (próximo artigo)
    ▼
Process Transaction
    │
    ├── BusinessRuleException → descarta artigo (sem retry)
    ├── SystemException       → aborta processo
    └── Exception             → retry (até max_retries vezes)
    │
    ▼
Get Transaction  (próximo artigo)
    ...
    │
    ▼
End Process (salva Excel, fecha browser, imprime resumo)
```

---

## Suite de Testes

```bash
python validate.py
```

27 testes cobrindo: Config Loader, MoneyDetector, ExcelHandler, ImageDownloader, Date Range e hierarquia de exceções — todos executados **sem browser**.

---

## Logs

Os logs são gravados em `logs/scraper.log` e também exibidos no terminal. O nível padrão é `INFO`; mude para `DEBUG` em `config.yaml` para ver detalhes de cada artigo.

---

## Notas Técnicas

### Compatibilidade com o NYTimes (2025+)

O scraper foi atualizado para a estrutura HTML atual do NYTimes, que mudou em 2025:

- Lista de resultados: `div[data-testid='search-results']` (antes era `ol`)
- Itens: `div[data-testid='search-bodega-result']` (antes era `li`)
- Título: `div[data-tpl='h'] a` (antes era `h4`)
- Descrição: `div[data-tpl='bo']` (antes era `p[class*='summary']`)
- Filtro de seção: `button#search-sections` (antes era `button[data-testid='search-multiselect-button']`)
- Dropdown de seções: `ul[data-testid='facet-filter-list']`

Todos os seletores possuem fallbacks para compatibilidade com versões anteriores do layout.

---

## Autor

Eduardo Gameiro — [egameiro@gmail.com](mailto:egameiro@gmail.com)
