"""Flask web server for the Personal Finance Analyzer."""
import os
import sys
import json
import time
from collections import defaultdict
from datetime import date as _today_date, datetime as _dt
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, send_file, abort
from werkzeug.utils import secure_filename
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

BASE_DIR      = Path(__file__).parents[1]
INPUT_DIR     = BASE_DIR / "data" / "input"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
MAPPINGS_PATH = BASE_DIR / "data" / "user_mappings.json"
REPORTS_DIR   = BASE_DIR / "reports"

_ALLOWED_EXTENSIONS = {".csv", ".ofx", ".qfx", ".xlsx", ".xls", ".pdf"}

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
_MAX_ATTEMPTS   = 5
_LOCKOUT_WINDOW = 900


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOCKOUT_WINDOW]
    return len(_login_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.time())


# ── auth helpers ──────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, email, role, active, must_change_password=0):
        self.id    = id
        self.email = email
        self.role  = role
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


# ── space helpers ─────────────────────────────────────────────────────────────

def _ind_space(user_id) -> str:
    return str(user_id)


def _pending_counts(conn, space: str):
    unverified = conn.execute(
        "SELECT COUNT(*) as n FROM transactions WHERE verified = 0 AND space = ?", (space,)
    ).fetchone()["n"]
    skipped = conn.execute(
        "SELECT COUNT(*) as n FROM skipped_rows WHERE space = ?", (space,)
    ).fetchone()["n"]
    return unverified, skipped


def _last_report(space: str):
    report_dir = REPORTS_DIR / space
    if not report_dir.exists():
        return None
    reports = sorted(report_dir.glob("report_*.html"))
    return reports[-1] if reports else None


def _list_reports(space: str) -> list:
    report_dir = REPORTS_DIR / space
    if not report_dir.exists():
        return []
    files = sorted(report_dir.glob("report_*.html"), reverse=True)
    result = []
    for f in files:
        try:
            parts = f.stem.split("_")
            label = _dt.strptime(f"{parts[1]}_{parts[2]}", "%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M")
        except Exception:
            label = f.name
        result.append({"name": f.name, "label": label, "size_kb": round(f.stat().st_size / 1024, 1)})
    return result


def _delete_reports_handler(space: str):
    report_dir = REPORTS_DIR / space
    if not report_dir.exists():
        return
    action = request.form.get("action")
    if action == "keep_latest":
        files = sorted(report_dir.glob("report_*.html"))
        to_delete = files[:-1]
    else:
        filenames = request.form.getlist("filenames")
        to_delete = [report_dir / secure_filename(f) for f in filenames]
    for f in to_delete:
        if f.exists() and f.parent.resolve() == report_dir.resolve():
            f.unlink()


def _has_data(conn, space: str) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) as n FROM transactions WHERE space = ?", (space,)
    ).fetchone()["n"]
    return n > 0


def _has_patrimony(conn, space: str) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) as n FROM patrimony WHERE space = ?", (space,)
    ).fetchone()["n"]
    return n > 0


def _get_patrimony(conn, space: str) -> list:
    return conn.execute(
        """
        SELECT p.id, p.label, p.amount AS initial_amount, p.category, p.reference_date,
               p.amount + COALESCE(SUM(
                   CASE WHEN t.date >= p.reference_date THEN t.amount ELSE 0 END
               ), 0) AS current_value
        FROM patrimony p
        LEFT JOIN transactions t ON t.patrimony_label = p.category AND t.space = p.space
        WHERE p.space = ?
        GROUP BY p.id
        ORDER BY p.category, p.label
        """, (space,)
    ).fetchall()


def _save_uploaded_files(files, dest_dir: Path) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            continue
        f.save(dest_dir / secure_filename(f.filename))
        saved += 1
    return saved


def _process_verify_form(conn, req, space: str):
    mappings = {}
    if MAPPINGS_PATH.exists():
        with open(MAPPINGS_PATH, encoding="utf-8") as f:
            mappings = json.load(f)

    patrimony_map = {}
    for key, val in req.form.items():
        if key.startswith("patrimony_"):
            try:
                txn_id = int(key[10:])
                patrimony_map[txn_id] = val if val else None
            except ValueError:
                pass

    for key, category in req.form.items():
        if not key.startswith("cat_"):
            continue
        txn_id = int(key[4:])
        row = conn.execute(
            "SELECT description FROM transactions WHERE id = ? AND space = ?", (txn_id, space)
        ).fetchone()
        if row:
            if req.form.get(f"include_{txn_id}") != "on":
                conn.execute("DELETE FROM transactions WHERE id = ? AND space = ?", (txn_id, space))
            else:
                pat_label = patrimony_map.get(txn_id)
                notes     = req.form.get(f"notes_{txn_id}", "").strip() or None
                conn.execute(
                    "UPDATE transactions SET category = ?, verified = 1, patrimony_label = ?, notes = ? WHERE id = ? AND space = ?",
                    (category, pat_label, notes, txn_id, space),
                )
            if category != "Outros":
                mappings[row["description"]] = category

    skipped_ids_raw = req.form.get("skipped_ids", "")
    if skipped_ids_raw:
        skipped_ids = [int(x) for x in skipped_ids_raw.split(",") if x.strip()]
        for sid in skipped_ids:
            include = req.form.get(f"skip_include_{sid}") == "on"
            if include:
                date_val   = req.form.get(f"skip_date_{sid}", "").strip()
                desc_val   = req.form.get(f"skip_desc_{sid}", "").strip()
                amount_val = req.form.get(f"skip_amount_{sid}", "").strip()
                cat_val    = req.form.get(f"skip_cat_{sid}", "Outros")
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
                               (date, description, amount, category, source_file, verified, space)
                               VALUES (?,?,?,?,?,1,?)""",
                            (date_clean, desc_val, amount_clean, cat_val, src, space),
                        )
                        mappings[desc_val] = cat_val
                except (ValueError, Exception):
                    pass
            conn.execute("DELETE FROM skipped_rows WHERE id = ? AND space = ?", (sid, space))

    MAPPINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MAPPINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False, indent=2)


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
                "SELECT id, email, role, active, must_change_password FROM users WHERE email = ?",
                (email,)
            ).fetchone()
            conn.close()
            login_user(User(row["id"], row["email"], row["role"], row["active"],
                            row["must_change_password"]))
            return redirect(url_for("index"))

        conn = get_connection()
        row = conn.execute(
            "SELECT id, email, password_hash, role, active, must_change_password FROM users "
            "WHERE email = ? AND active = 1",
            (email,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row["password_hash"], password):
            _login_attempts[ip].clear()
            login_user(User(row["id"], row["email"], row["role"], row["active"],
                            row["must_change_password"]))
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


# ── landing ───────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    joint_space = 'joint'
    ind_space   = _ind_space(current_user.id)

    conn = get_connection()
    joint_has_data      = _has_data(conn, joint_space)
    joint_has_patrimony = _has_patrimony(conn, joint_space)
    ind_has_data        = _has_data(conn, ind_space)
    ind_has_patrimony   = _has_patrimony(conn, ind_space)
    joint_unverified, joint_skipped = _pending_counts(conn, joint_space)
    ind_unverified,   ind_skipped   = _pending_counts(conn, ind_space)
    conn.close()

    return render_template(
        "index.html",
        joint_has_data=joint_has_data,
        joint_has_patrimony=joint_has_patrimony,
        joint_unverified=joint_unverified,
        joint_skipped=joint_skipped,
        joint_last_report=_last_report(joint_space),
        ind_has_data=ind_has_data,
        ind_has_patrimony=ind_has_patrimony,
        ind_unverified=ind_unverified,
        ind_skipped=ind_skipped,
        ind_last_report=_last_report(ind_space),
    )


# ── joint space ───────────────────────────────────────────────────────────────

@app.route("/joint")
@login_required
def joint():
    space = 'joint'
    conn  = get_connection()
    patrimony           = _get_patrimony(conn, space)
    unverified, skipped = _pending_counts(conn, space)
    total = conn.execute("SELECT COUNT(*) FROM transactions WHERE space = ?", (space,)).fetchone()[0]
    conn.close()
    return render_template(
        "joint.html",
        patrimony=patrimony,
        unverified=unverified,
        skipped=skipped,
        total_transactions=total,
        last_report=_last_report(space),
    )


@app.route("/joint/upload", methods=["POST"])
@admin_required
def joint_upload():
    space     = 'joint'
    input_dir = INPUT_DIR / 'joint'
    proc_dir  = PROCESSED_DIR / 'joint'

    files = request.files.getlist("files")
    saved = _save_uploaded_files(files, input_dir)
    if saved == 0:
        return redirect(url_for("joint"))

    conn = get_connection()
    load_directory(input_dir, conn, space=space, processed_dir=proc_dir)
    categorize_all(conn, space=space)
    conn.close()
    return redirect(url_for("joint_verify"))


@app.route("/joint/verify", methods=["GET", "POST"])
@admin_required
def joint_verify():
    space = 'joint'
    if request.method == "POST":
        conn = get_connection()
        _process_verify_form(conn, request, space)
        conn.commit()
        if request.form.get("action") == "report":
            report_path = generate(conn, space=space)
            conn.close()
            return redirect(url_for("joint_report", filename=report_path.name))
        conn.close()
        return redirect(url_for("joint"))

    conn = get_connection()
    transactions = conn.execute(
        "SELECT id, date, description, amount, category, patrimony_label, notes "
        "FROM transactions WHERE space = ? ORDER BY date", (space,)
    ).fetchall()
    skipped_rows = conn.execute(
        "SELECT id, source_file, date_raw, description_raw, amount_raw, reason "
        "FROM skipped_rows WHERE space = ? ORDER BY imported_at", (space,)
    ).fetchall()

    if not transactions and not skipped_rows:
        conn.close()
        return redirect(url_for("joint"))

    patrimony = _get_patrimony(conn, space)
    conn.close()
    return render_template(
        "verify.html",
        transactions=transactions,
        skipped_rows=skipped_rows,
        categories=load_categories(),
        patrimony=patrimony,
        space=space,
        back_url=url_for("joint"),
    )


@app.route("/joint/generate-report", methods=["POST"])
@admin_required
def joint_generate_report():
    conn = get_connection()
    report_path = generate(conn, space='joint')
    conn.close()
    return redirect(url_for("joint_report", filename=report_path.name))


@app.route("/joint/report/<filename>")
@login_required
def joint_report(filename):
    return send_file(REPORTS_DIR / 'joint' / filename)


@app.route("/joint/reports")
@login_required
def joint_reports():
    return render_template("reports_list.html",
                           reports=_list_reports('joint'),
                           report_base_url="/joint/report/",
                           delete_url=url_for("joint_reports_delete"),
                           back_url=url_for("joint"))


@app.route("/joint/reports/delete", methods=["POST"])
@admin_required
def joint_reports_delete():
    _delete_reports_handler('joint')
    return redirect(url_for("joint_reports"))


# ── individual space ──────────────────────────────────────────────────────────

@app.route("/individual")
@login_required
def individual():
    space = _ind_space(current_user.id)
    conn  = get_connection()
    patrimony           = _get_patrimony(conn, space)
    unverified, skipped = _pending_counts(conn, space)
    total = conn.execute("SELECT COUNT(*) FROM transactions WHERE space = ?", (space,)).fetchone()[0]
    conn.close()
    return render_template(
        "individual.html",
        patrimony=patrimony,
        unverified=unverified,
        skipped=skipped,
        total_transactions=total,
        last_report=_last_report(space),
    )


@app.route("/individual/upload", methods=["POST"])
@login_required
def individual_upload():
    space     = _ind_space(current_user.id)
    input_dir = INPUT_DIR / 'individual' / str(current_user.id)
    proc_dir  = PROCESSED_DIR / 'individual' / str(current_user.id)

    files = request.files.getlist("files")
    saved = _save_uploaded_files(files, input_dir)
    if saved == 0:
        return redirect(url_for("individual"))

    conn = get_connection()
    load_directory(input_dir, conn, space=space, processed_dir=proc_dir)
    categorize_all(conn, space=space)
    conn.close()
    return redirect(url_for("individual_verify"))


@app.route("/individual/verify", methods=["GET", "POST"])
@login_required
def individual_verify():
    space = _ind_space(current_user.id)
    if request.method == "POST":
        conn = get_connection()
        _process_verify_form(conn, request, space)
        conn.commit()
        if request.form.get("action") == "report":
            report_path = generate(conn, space=space)
            conn.close()
            return redirect(url_for("individual_report", filename=report_path.name))
        conn.close()
        return redirect(url_for("individual"))

    conn = get_connection()
    transactions = conn.execute(
        "SELECT id, date, description, amount, category, patrimony_label, notes "
        "FROM transactions WHERE space = ? ORDER BY date", (space,)
    ).fetchall()
    skipped_rows = conn.execute(
        "SELECT id, source_file, date_raw, description_raw, amount_raw, reason "
        "FROM skipped_rows WHERE space = ? ORDER BY imported_at", (space,)
    ).fetchall()

    if not transactions and not skipped_rows:
        conn.close()
        return redirect(url_for("individual"))

    patrimony = _get_patrimony(conn, space)
    conn.close()
    return render_template(
        "verify.html",
        transactions=transactions,
        skipped_rows=skipped_rows,
        categories=load_categories(),
        patrimony=patrimony,
        space=space,
        back_url=url_for("individual"),
    )


@app.route("/individual/generate-report", methods=["POST"])
@login_required
def individual_generate_report():
    space = _ind_space(current_user.id)
    conn = get_connection()
    report_path = generate(conn, space=space)
    conn.close()
    return redirect(url_for("individual_report", filename=report_path.name))


@app.route("/individual/report/<filename>")
@login_required
def individual_report(filename):
    space = _ind_space(current_user.id)
    return send_file(REPORTS_DIR / space / filename)


@app.route("/individual/reports")
@login_required
def individual_reports():
    space = _ind_space(current_user.id)
    return render_template("reports_list.html",
                           reports=_list_reports(space),
                           report_base_url="/individual/report/",
                           delete_url=url_for("individual_reports_delete"),
                           back_url=url_for("individual"))


@app.route("/individual/reports/delete", methods=["POST"])
@login_required
def individual_reports_delete():
    space = _ind_space(current_user.id)
    _delete_reports_handler(space)
    return redirect(url_for("individual_reports"))


# ── add transaction ───────────────────────────────────────────────────────────

def _add_transaction_handler(space: str, back_url: str):
    conn = get_connection()
    patrimony = _get_patrimony(conn, space)

    if request.method == "POST":
        date_val   = request.form.get("date", "").strip()
        desc_val   = request.form.get("description", "").strip()
        amount_str = request.form.get("amount", "").strip()
        cat_val    = request.form.get("category", "Outros").strip()
        pat_label  = request.form.get("patrimony_label", "").strip() or None
        notes      = request.form.get("notes", "").strip() or None

        error = None
        try:
            date_clean   = _parse_date(date_val)
            amount_clean = float(amount_str.replace(",", "."))
            if not desc_val:
                raise ValueError("A descrição é obrigatória.")
            conn.execute(
                """INSERT INTO transactions
                   (date, description, amount, category, source_file, verified, space, patrimony_label, notes)
                   VALUES (?,?,?,?,?,1,?,?,?)""",
                (date_clean, desc_val, amount_clean, cat_val, "manual", space, pat_label, notes),
            )
            conn.commit()
            conn.close()
            return redirect(back_url)
        except ValueError as exc:
            error = str(exc)

        conn.close()
        return render_template(
            "add_transaction.html",
            categories=load_categories(),
            patrimony=patrimony,
            space=space,
            back_url=back_url,
            error=error,
            form=request.form,
        )

    conn.close()
    return render_template(
        "add_transaction.html",
        categories=load_categories(),
        patrimony=patrimony,
        space=space,
        back_url=back_url,
        today=_today_date.today().isoformat(),
    )


@app.route("/joint/add-transaction", methods=["GET", "POST"])
@admin_required
def joint_add_transaction():
    return _add_transaction_handler("joint", url_for("joint"))


@app.route("/individual/add-transaction", methods=["GET", "POST"])
@login_required
def individual_add_transaction():
    return _add_transaction_handler(_ind_space(current_user.id), url_for("individual"))


# ── patrimony ─────────────────────────────────────────────────────────────────

@app.route("/patrimony/joint", methods=["GET", "POST"])
@admin_required
def patrimony_joint():
    return _patrimony_handler('joint', url_for("joint"))


@app.route("/patrimony/individual", methods=["GET", "POST"])
@login_required
def patrimony_individual():
    return _patrimony_handler(_ind_space(current_user.id), url_for("individual"))


def _all_patrimony_categories(conn) -> list:
    return conn.execute(
        "SELECT id, name FROM patrimony_categories ORDER BY name"
    ).fetchall()


def _available_categories(conn, space: str) -> list:
    used = {row["category"] for row in conn.execute(
        "SELECT category FROM patrimony WHERE space = ?", (space,)
    ).fetchall()}
    return [r["name"] for r in _all_patrimony_categories(conn) if r["name"] not in used]


def _patrimony_handler(space: str, back_url: str):
    conn = get_connection()
    if request.method == "POST":
        label          = request.form.get("label", "").strip()
        amount         = request.form.get("amount", "").strip()
        category       = request.form.get("category", "").strip()
        reference_date = request.form.get("reference_date", "").strip()
        if label and amount and reference_date and category in _available_categories(conn, space):
            try:
                conn.execute(
                    "INSERT INTO patrimony (space, label, amount, category, reference_date) VALUES (?, ?, ?, ?, ?)",
                    (space, label, float(amount.replace(",", ".")), category, reference_date),
                )
                conn.commit()
            except ValueError:
                pass
        conn.close()
        return redirect(request.url)

    patrimony            = _get_patrimony(conn, space)
    available_categories = _available_categories(conn, space)
    all_categories       = _all_patrimony_categories(conn)
    used_categories      = {row["category"] for row in conn.execute(
        "SELECT DISTINCT category FROM patrimony"
    ).fetchall()}
    conn.close()
    return render_template("setup.html", patrimony=patrimony, space=space, back_url=back_url,
                           available_categories=available_categories,
                           all_categories=all_categories,
                           used_categories=used_categories)


@app.route("/patrimony/edit/<int:entry_id>", methods=["POST"])
@login_required
def patrimony_edit(entry_id):
    conn = get_connection()
    row = conn.execute("SELECT space, category FROM patrimony WHERE id = ?", (entry_id,)).fetchone()
    if row:
        space = row["space"]
        if space == 'joint' and current_user.role != 'admin':
            conn.close()
            abort(403)
        if space != 'joint' and space != _ind_space(current_user.id):
            conn.close()
            abort(403)
        old_category = row["category"]
        new_label = request.form.get("label", "").strip()
        new_category = request.form.get("category", "").strip()
        new_amount = request.form.get("amount", "").strip()
        new_reference_date = request.form.get("reference_date", "").strip()
        if new_label and new_category and new_amount and new_reference_date:
            conn.execute("""
                UPDATE patrimony SET label = ?, category = ?, amount = ?, reference_date = ?
                WHERE id = ?
            """, (new_label, new_category, float(new_amount), new_reference_date, entry_id))
            if new_category != old_category:
                conn.execute("""
                    UPDATE transactions SET patrimony_label = ?
                    WHERE patrimony_label = ? AND space = ?
                """, (new_category, old_category, space))
            conn.commit()
    conn.close()
    back = request.form.get("back_url", url_for("index"))
    return redirect(back)


@app.route("/patrimony/delete/<int:entry_id>", methods=["POST"])
@login_required
def patrimony_delete(entry_id):
    conn = get_connection()
    row = conn.execute("SELECT space FROM patrimony WHERE id = ?", (entry_id,)).fetchone()
    if row:
        space = row["space"]
        if space == 'joint' and current_user.role != 'admin':
            conn.close()
            abort(403)
        if space != 'joint' and space != _ind_space(current_user.id):
            conn.close()
            abort(403)
        conn.execute("DELETE FROM patrimony WHERE id = ?", (entry_id,))
        conn.commit()
    conn.close()
    back = request.form.get("back_url", url_for("index"))
    return redirect(back)


# ── patrimony categories routes ───────────────────────────────────────────────

@app.route("/patrimony/categories/add", methods=["POST"])
@login_required
def patrimony_category_add():
    name = request.form.get("name", "").strip()
    back = request.form.get("back_url", url_for("index"))
    if name:
        conn = get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO patrimony_categories (name) VALUES (?)", (name,))
            conn.commit()
        finally:
            conn.close()
    return redirect(back)


@app.route("/patrimony/categories/delete/<int:cat_id>", methods=["POST"])
@login_required
def patrimony_category_delete(cat_id):
    back = request.form.get("back_url", url_for("index"))
    conn = get_connection()
    row = conn.execute("SELECT name FROM patrimony_categories WHERE id = ?", (cat_id,)).fetchone()
    if row:
        in_use = conn.execute(
            "SELECT 1 FROM patrimony WHERE category = ? LIMIT 1", (row["name"],)
        ).fetchone()
        if not in_use:
            conn.execute("DELETE FROM patrimony_categories WHERE id = ?", (cat_id,))
            conn.commit()
    conn.close()
    return redirect(back)


@app.route("/patrimony/categories/delete-unused", methods=["POST"])
@login_required
def patrimony_categories_delete_unused():
    back = request.form.get("back_url", url_for("index"))
    conn = get_connection()
    conn.execute("""
        DELETE FROM patrimony_categories
        WHERE name NOT IN (SELECT DISTINCT category FROM patrimony)
    """)
    conn.commit()
    conn.close()
    return redirect(back)


# ── transaction categories routes ─────────────────────────────────────────────

def _load_rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_rules(rules: dict) -> None:
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


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
            pass
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


if __name__ == "__main__":
    debug = os.environ.get("FLASK_ENV") != "production"
    app.run(debug=debug, port=5000)
