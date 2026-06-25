"""
Personal Finance Analyzer — CLI entry point.

Usage:
    python -m app.main --input data/input/
    python -m app.main --input data/input/ --recategorize
    python -m app.main --recategorize            # re-apply rules without importing new files
"""
import argparse
import sys
from pathlib import Path

from app.db.connection import get_connection
from app.ingest.loader import load_directory
from app.categorize.engine import categorize_all, recategorize_all
from app.reports.generator import generate


def parse_args():
    parser = argparse.ArgumentParser(description="Analisador de finanças pessoais")
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=None,
        help="Pasta com ficheiros a importar (CSV, OFX, XLSX)",
    )
    parser.add_argument(
        "--recategorize",
        action="store_true",
        help="Re-aplica as regras a TODAS as transações (útil após editar rules.json)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Não gerar relatório HTML no final",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.input and not args.recategorize:
        print("Indica --input <pasta> ou --recategorize. Usa --help para ajuda.")
        sys.exit(1)

    conn = get_connection()

    # 1. Ingestão
    if args.input:
        input_dir = args.input
        if not input_dir.exists():
            print(f"Erro: pasta não encontrada: {input_dir}")
            sys.exit(1)
        print(f"\n=== Ingestão: {input_dir} ===")
        total = load_directory(input_dir, conn)
        print(f"Total importado: {total} transações\n")

    # 2. Categorização
    print("=== Categorização ===")
    if args.recategorize:
        updated = recategorize_all(conn)
        print(f"Re-categorizadas: {updated} transações")
    else:
        updated = categorize_all(conn)
        print(f"Categorizadas: {updated} transações novas")

    # 3. Relatório
    if not args.no_report:
        print("\n=== Relatório ===")
        report_path = generate(conn)
        print(f"Relatório gerado: {report_path}")

    conn.close()
    print("\nConcluído.")


if __name__ == "__main__":
    main()
