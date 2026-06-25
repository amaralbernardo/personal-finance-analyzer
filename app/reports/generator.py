"""Renders the HTML report from aggregated data."""
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.analysis.aggregator import summary

TEMPLATE_DIR = Path(__file__).parent
REPORTS_DIR  = Path(__file__).parents[2] / "reports"


def generate(conn: sqlite3.Connection, output_dir: Path = REPORTS_DIR) -> Path:
    """
    Build the HTML report and write it to output_dir.
    Returns the path of the generated file.
    """
    data = summary(conn)
    now  = datetime.now()

    env      = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("template.html")

    html = template.render(
        data=data,
        generated_at=now.strftime("%d/%m/%Y %H:%M"),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"report_{now.strftime('%Y%m%d_%H%M%S')}.html"
    out_path.write_text(html, encoding="utf-8")

    return out_path
