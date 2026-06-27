"""Flask web server for the Personal Finance Analyzer."""
import os
import sys
import json
import time
from collections import defaultdict
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, send_file, abort
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user, login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

from app.db.connection import get_connection
from app.ingest.loader import load_directory
from app.ingest.normalizer import _parse_date, _parse_amount
from app.categorize.engine import categorize_all, recategorize_all, load_categories, RULES_PATH
from app.reports.generator import generate
from app.email import send_welcome_email

INPUT_DIR     = Path(__file__).parents[1] / "data" / "input"
MAPPINGS_PATH = Path(__file__).parents[1] / "data" / "user_mappings.json"
REPORTS_DIR   = Path(__file__).parents[1] / "reports"

_SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not _SECRET_KEY:
    if os.environ.get("FLASK_ENV") == "production":
        print("ERRO: define a variável de ambiente SECRET_KEY antes de correr em produção.", file=sys.stderr)
        sys.exit(1)
    _SECRET_KEY = "dev-secret-change-in-production"

app = Flask(__name__, template_folder="templates")
app.secret_key = _SECRET_KEY

login_manager = LoginManager(app)
login_manager.login_view = "login"


@app.before_request
def enforce_password_change():
    if current_user.is_authenticated and current_user.must_change_password:
        if request.endpoint not in ("change_password", "logout", "static"):
            return redirect(url_for("change_password"))

# ── rate limiting ─────────────────────────────────────────────────────────────
_login_attempts: dict = defaultdict(list)
_MAX_ATTEMPTS = 5
_LOCKOUT_WINDOW = 900  # 15 minutes


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_WINDOW]
    return len(_login_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.time())


# ── auth helpers ──────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, email, role, active, must_change_password=0):
        self.id = id
        self.email = email
        self.role = role
        self.active = active
        self.must_change_password = bool(must_change_password)

    @property
    def is_active(self):
        return bool(self.active)

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email, role, active, must_change_password FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["email"], row["role"], row["active"], row["must_change_password"])
    return None


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _first_time_setup():
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()["n"]
    conn.close()
    return n == 0


# ── generic helpers ───────────────────────────────────────────────────────────

def _last_report():
    if not REPORTS_DIR.exists():
        return None
    reports = sorted(REPORTS_DIR.glob("report_*.html"))
    return reports[-1] if reports else None


def _pending_counts(conn):
    unverified = conn.execute(
        "SELECT COUNT(*) as n FROM transactions WHERE verified = 0"
    ).fetchone()["n"]
    skipped = conn.execute(
        "SELECT COUNT(*) as n FROM skipped_rows"
    ).fetchone()["n"]
    return unverified, skipped


def _load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_rules(rules: dict) -> None:
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


# ── auth routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    is_setup = _first_time_setup()

    if request.method == "POST":
        ip = request.remote_addr or "unknown"

        if _is_rate_limited(ip):
            return render_template("login.html", is_setup=is_setup,
                                   error="Demasiadas tentativas. Tenta novamente em 15 minutos.")

        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if is_setup:
            if not email or not password:
                return render_template("login.html", is_setup=True,
                                       error="Preenche o email e a password.")
            conn = get_connection()
            conn.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'admin')",
                (email, generate_password_hash(password)),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, email, role, active FROM users WHERE email = ?", (email,)
            ).fetchone()
            conn.close()
            login_user(User(row["id"], row["email"], row["role"], row["active"]))
            return redirect(url_for("index"))

        conn = get_connection()
        row = conn.execute(
            "SELECT id, email, password_hash, role, active FROM users "
            "WHERE email = ? AND active = 1",
            (email,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row["password_hash"], password):
            _login_attempts[ip].clear()
            login_user(User(row["id"], row["email"], row["role"], row["active"]))
            return redirect(url_for("index"))

        _record_failed_attempt(ip)
        return render_template("login.html", is_setup=False,
                               error="Email ou password incorretos.")

    return render_template("login.html", is_setup=is_setup)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    success = None
    if request.method == "POST":
        current  = request.form.get("current_password", "")
        new_pw   = request.form.get("new_password", "")
        confirm  = request.form.get("confirm_password", "")

        conn = get_connection()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (current_user.id,)
        ).fetchone()

        if not row or not check_password_hash(row["password_hash"], current):
            error = "A password atual está incorreta."
        elif len(new_pw) < 8:
            error = "A nova password deve ter pelo menos 8 caracteres."
        elif new_pw != confirm:
            error = "As passwords não coincidem."
        else:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (generate_password_hash(new_pw), current_user.id),
            )
            conn.commit()
            success = "Password alterada com sucesso."
        conn.close()

    return render_template("change_password.html", error=error, success=success)


# ── main routes ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    if current_user.role == "viewer":
        last = _last_report()
        if last:
            return redirect(url_for("report", filename=last.name))
        return ("<p style='font-family:sans-serif;padding:40px;color:#666'>"
                "Ainda não existe relatório disponível.</p>"), 200

    conn = get_connection()
    unverified, skipped = _pending_counts(conn)
    conn.close()
    return render_template(
        "index.html",
        unverified=unverified,
        skipped=skipped,
        last_report=_last_report(),
    )


@app.route("/run", methods=["POST"])
@admin_required
def run():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    load_directory(INPUT_DIR, conn)
    categorize_all(conn)
    unverified, skipped = _pending_counts(conn)
    conn.close()
    if unverified > 0 or skipped > 0:
        return redirect(url_for("verify"))
    conn2 = get_connection()
    report_path = generate(conn2)
    conn2.close()
    return redirect(url_for("report", filename=report_path.name))


# ── verify routes ─────────────────────────────────────────────────────────────

@app.route("/verify", methods=["GET", "POST"])
@admin_required
def verify():
    if request.method == "POST":
        conn = get_connection()
        mappings = {}
        if MAPPINGS_PATH.exists():
            with open(MAPPINGS_PATH, encoding="utf-8") as f:
                mappings = json.load(f)

        for key, category in request.form.items():
            if not key.startswith("cat_"):
                continue
            txn_id = int(key[4:])
            row = conn.execute(
                "SELECT description FROM transactions WHERE id = ?", (txn_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE transactions SET category = ?, verified = 1 WHERE id = ?",
                    (category, txn_id),
                )
                mappings[row["description"]] = category

        MAPPINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MAPPINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(mappings, f, ensure_ascii=False, indent=2)

        skipped_ids_raw = request.form.get("skipped_ids", "")
        if skipped_ids_raw:
            skipped_ids = [int(x) for x in skipped_ids_raw.split(",") if x.strip()]
            for sid in skipped_ids:
                include = request.form.get(f"skip_include_{sid}") == "on"
                if include:
                    date_val   = request.form.get(f"skip_date_{sid}", "").strip()
                    desc_val   = request.form.get(f"skip_desc_{sid}", "").strip()
                    amount_val = request.form.get(f"skip_amount_{sid}", "").strip()
                    cat_val    = request.form.get(f"skip_cat_{sid}", "Outros")
                    src_row = conn.execute(
                        "SELECT source_file FROM skipped_rows WHERE id = ?", (sid,)
                    ).fetchone()
                    src = src_row["source_file"] if src_row else "manual"
                    try:
                        date_clean   = _parse_date(date_val)
                        amount_clean = _parse_amount(amount_val)
                        if desc_val:
                            conn.execute(
                                """INSERT INTO transactions
                                   (date, description, amount, category, source_file, verified)
                                   VALUES (?,?,?,?,?,1)""",
                                (date_clean, desc_val, amount_clean, cat_val, src),
                            )
                            mappings[desc_val] = cat_val
                    except (ValueError, Exception):
                        pass
                conn.execute("DELETE FROM skipped_rows WHERE id = ?", (sid,))

            with open(MAPPINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(mappings, f, ensure_ascii=False, indent=2)

        conn.commit()
        report_path = generate(conn)
        conn.close()
        return redirect(url_for("report", filename=report_path.name))

    conn = get_connection()
    transactions = conn.execute(
        "SELECT id, date, description, amount, category "
        "FROM transactions WHERE verified = 0 ORDER BY date"
    ).fetchall()
    skipped_rows = conn.execute(
        "SELECT id, source_file, date_raw, description_raw, amount_raw, reason "
        "FROM skipped_rows ORDER BY imported_at"
    ).fetchall()
    conn.close()

    if not transactions and not skipped_rows:
        return redirect(url_for("index"))

    return render_template(
        "verify.html",
        transactions=transactions,
        skipped_rows=skipped_rows,
        categories=load_categories(),
    )


# ── categories routes ─────────────────────────────────────────────────────────

@app.route("/categories")
@admin_required
def categories():
    return render_template("categories.html", rules=_load_rules())


@app.route("/categories/add", methods=["POST"])
@admin_required
def categories_add():
    name    = request.form.get("name", "").strip()
    keyword = request.form.get("keyword", "").strip().lower()
    if name and keyword:
        rules = _load_rules()
        if name not in rules:
            rules[name] = [keyword]
            _save_rules(rules)
    return redirect(url_for("categories"))


@app.route("/categories/delete", methods=["POST"])
@admin_required
def categories_delete():
    name = request.form.get("name", "").strip()
    if name:
        rules = _load_rules()
        rules.pop(name, None)
        _save_rules(rules)
    return redirect(url_for("categories"))


@app.route("/categories/add-keyword", methods=["POST"])
@admin_required
def categories_add_keyword():
    name    = request.form.get("name", "").strip()
    keyword = request.form.get("keyword", "").strip().lower()
    if name and keyword:
        rules = _load_rules()
        if name in rules and keyword not in rules[name]:
            rules[name].append(keyword)
            _save_rules(rules)
    return redirect(url_for("categories"))


@app.route("/categories/remove-keyword", methods=["POST"])
@admin_required
def categories_remove_keyword():
    name    = request.form.get("name", "").strip()
    keyword = request.form.get("keyword", "").strip()
    if name and keyword:
        rules = _load_rules()
        if name in rules:
            rules[name] = [kw for kw in rules[name] if kw != keyword]
            _save_rules(rules)
    return redirect(url_for("categories"))


@app.route("/categories/recategorize", methods=["POST"])
@admin_required
def categories_recategorize():
    conn = get_connection()
    recategorize_all(conn)
    conn.close()
    return redirect(url_for("categories"))


# ── users routes ──────────────────────────────────────────────────────────────

@app.route("/users")
@admin_required
def users():
    conn = get_connection()
    all_users = conn.execute(
        "SELECT id, email, role, active, created_at FROM users ORDER BY created_at"
    ).fetchall()
    conn.close()
    return render_template("users.html", users=all_users)


@app.route("/users/add", methods=["POST"])
@admin_required
def users_add():
    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    role     = request.form.get("role", "viewer")
    if email and password:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, role, must_change_password) VALUES (?, ?, ?, 1)",
                (email, generate_password_hash(password), role),
            )
            conn.commit()
            app_url = os.environ.get("APP_URL", request.host_url.rstrip("/"))
            send_welcome_email(email, password, role, app_url)
        except Exception:
            pass  # email already exists
        conn.close()
    return redirect(url_for("users"))


@app.route("/users/toggle", methods=["POST"])
@admin_required
def users_toggle():
    user_id = request.form.get("id")
    if user_id and int(user_id) != current_user.id:
        conn = get_connection()
        row = conn.execute("SELECT active FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            conn.execute("UPDATE users SET active = ? WHERE id = ?",
                         (0 if row["active"] else 1, user_id))
            conn.commit()
        conn.close()
    return redirect(url_for("users"))


@app.route("/users/delete", methods=["POST"])
@admin_required
def users_delete():
    user_id = request.form.get("id")
    if user_id and int(user_id) != current_user.id:
        conn = get_connection()
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
    return redirect(url_for("users"))


# ── report route ──────────────────────────────────────────────────────────────

@app.route("/report/<filename>")
@login_required
def report(filename):
    return send_file(REPORTS_DIR / filename)


if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug, port=5000)
