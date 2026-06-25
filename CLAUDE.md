# Personal Finance Analyzer

Pipeline local para ingestão, categorização e análise de extratos bancários, com geração de relatório HTML.

## Arquitetura

```
data/input/          ← coloca aqui os extratos (CSV, OFX, XLSX)
data/processed/      ← ficheiros movidos após ingestão
data/finance.db      ← base de dados SQLite (gerada automaticamente)
reports/             ← relatórios HTML gerados
app/
  ingest/            ← parsers e normalização de ficheiros
  categorize/        ← engine de regras keyword→categoria
  db/                ← schema e conexão SQLite
  analysis/          ← agregações e métricas
  reports/           ← geração de HTML com Jinja2
  main.py            ← orquestrador CLI
```

## Como correr

```bash
pip install -r requirements.txt
python app/main.py --input data/input/
```

O relatório é guardado em `reports/report_YYYYMMDD.html`.

## Formato dos ficheiros de input

### CSV
Qualquer CSV exportado de banco. O parser deteta automaticamente o separador (`,` ou `;`) e tenta mapear colunas por nome. Colunas reconhecidas:

| Campo        | Nomes aceites                                      |
|--------------|----------------------------------------------------|
| Data         | `data`, `date`, `Data Mov.`, `Data Valor`          |
| Descrição    | `descricao`, `description`, `Descrição`, `Movimento` |
| Valor        | `valor`, `amount`, `Montante`, `Débito`, `Crédito` |

### OFX / QFX
Formato padrão exportado pela maioria dos bancos. Sem configuração necessária.

### XLSX
Excel exportado manualmente. Usa as mesmas regras de mapeamento de colunas que o CSV.

## Categorização

Edita `app/categorize/rules.json` para configurar as tuas categorias:

```json
{
  "Alimentação": ["continente", "pingo doce", "lidl", "aldi", "mercadona"],
  "Transportes": ["uber", "bolt", "cp ", "metro", "galp", "bp "],
  "Saúde": ["farmacia", "farmácia", "clinica", "médico"],
  "Habitação": ["agua", "luz", "gás", "condomínio", "renda"]
}
```

Transações sem match ficam com categoria `"Outros"`.

## Testes

```bash
pytest tests/
```
