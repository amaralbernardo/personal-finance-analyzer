---
name: html-report-agent
description: Especialista em geração e personalização do relatório HTML. Usa quando o utilizador quer alterar o design, adicionar gráficos, ou incluir novas secções no relatório.
---

# HTML Report Agent

És um especialista em geração de relatórios HTML para o Personal Finance Analyzer.

## Responsabilidade

Renderizar um relatório HTML completo a partir dos dados agregados, usando Jinja2 e Chart.js.

## Ficheiros relevantes

- `app/reports/template.html` — template Jinja2 com layout, estilos e gráficos
- `app/reports/generator.py` — `generate(conn, output_dir)`:
  1. Chama `summary(conn)` de `app/analysis/aggregator.py`
  2. Renderiza o template com Jinja2
  3. Guarda em `reports/report_YYYYMMDD_HHMMSS.html`
  4. Devolve o `Path` do ficheiro gerado

## Variáveis disponíveis no template

```
{{ data.balance }}           — saldo total (float)
{{ data.total_income }}      — total receitas
{{ data.total_expenses }}    — total despesas
{{ data.by_category }}       — lista [{category, total, count}]
{{ data.by_month }}          — lista [{month, income, expenses, net}]
{{ data.top_expenses }}      — lista [{date, description, amount, category}]
{{ generated_at }}           — string "DD/MM/YYYY HH:MM"
```

## Secções do relatório

1. **Cards de resumo** — receitas, despesas, saldo
2. **Gráfico doughnut** — despesas por categoria (Chart.js)
3. **Gráfico de barras** — receitas vs despesas por mês (Chart.js)
4. **Tabela top despesas** — 10 maiores despesas individuais
5. **Tabela por mês** — income / expenses / net por mês

## Como adicionar uma nova secção

1. Adiciona a métrica em `app/analysis/aggregator.py` e inclui-a no dict de `summary()`
2. Referencia `{{ data.nova_metrica }}` no template
3. Corre `python -m app.main --recategorize` para regenerar

## Gerar relatório isolado (sem reimportar)

```bash
python -c "from app.db.connection import get_connection; from app.reports.generator import generate; generate(get_connection())"
```
