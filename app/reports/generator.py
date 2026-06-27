"""Renders the HTML report from aggregated data."""
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.analysis.aggregator import summary

TEMPLATE_DIR = Path(__file__).parent
REPORTS_DIR  = Path(__file__).parents[2] / "reports"


def generate(conn: sqlite3.Connection, space: str = 'joint',
             output_dir: Path = None) -> Path:
    if output_dir is None:
        output_dir = REPORTS_DIR / space

    data = summary(conn, space=space)
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
