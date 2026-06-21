import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from app.db.connection import get_connection
from app.server import app


@pytest.fixture
def client(tmp_path):
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    db_path = tmp_path / "test.db"

    with patch("app.server.get_connection", side_effect=lambda: get_connection(db_path)):
        with app.test_client() as c:
            yield c


@pytest.fixture
def seeded_client(tmp_path):
    """Client with admin and viewer pre-created in the test DB."""
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    db_path = tmp_path / "test.db"

    conn = get_connection(db_path)
    conn.executemany(
        "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
        [
            ("admin@test.com", generate_password_hash("admin123"), "admin"),
            ("viewer@test.com", generate_password_hash("viewer123"), "viewer"),
        ],
    )
    conn.commit()
    conn.close()

    with patch("app.server.get_connection", side_effect=lambda: get_connection(db_path)):
        with app.test_client() as c:
            yield c


# ── login ──────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_login_page_loads(self, client):
        assert client.get("/login").status_code == 200

    def test_first_time_setup_shown(self, client):
        html = client.get("/login").data.decode("utf-8")
        assert "primeiro" in html.lower() or "configurar" in html.lower()

    def test_correct_credentials_redirect(self, seeded_client):
        r = seeded_client.post(
            "/login",
            data={"email": "admin@test.com", "password": "admin123"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.location.endswith("/")

    def test_wrong_password_shows_error(self, seeded_client):
        r = seeded_client.post(
            "/login",
            data={"email": "admin@test.com", "password": "wrong"},
        )
        assert r.status_code == 200
        assert "incorretos" in r.data.decode("utf-8")

    def test_unknown_email_shows_error(self, seeded_client):
        r = seeded_client.post(
            "/login",
            data={"email": "unknown@test.com", "password": "admin123"},
        )
        assert "incorretos" in r.data.decode("utf-8")

    def test_logout_redirects_to_login(self, seeded_client):
        seeded_client.post("/login", data={"email": "admin@test.com", "password": "admin123"})
        r = seeded_client.get("/logout", follow_redirects=False)
        assert r.status_code == 302
        assert "login" in r.location


# ── access control ─────────────────────────────────────────────────────────────

class TestAccessControl:
    def test_unauthenticated_root_redirects_to_login(self, seeded_client):
        r = seeded_client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "login" in r.location

    def test_unauthenticated_verify_redirects(self, seeded_client):
        r = seeded_client.get("/verify", follow_redirects=False)
        assert r.status_code == 302

    def test_admin_accesses_dashboard(self, seeded_client):
        seeded_client.post("/login", data={"email": "admin@test.com", "password": "admin123"})
        assert seeded_client.get("/").status_code == 200

    def test_admin_accesses_categories(self, seeded_client):
        seeded_client.post("/login", data={"email": "admin@test.com", "password": "admin123"})
        assert seeded_client.get("/categories").status_code == 200

    def test_admin_accesses_users(self, seeded_client):
        seeded_client.post("/login", data={"email": "admin@test.com", "password": "admin123"})
        assert seeded_client.get("/users").status_code == 200

    def test_viewer_cannot_access_categories(self, seeded_client):
        seeded_client.post("/login", data={"email": "viewer@test.com", "password": "viewer123"})
        assert seeded_client.get("/categories").status_code == 403

    def test_viewer_cannot_access_users(self, seeded_client):
        seeded_client.post("/login", data={"email": "viewer@test.com", "password": "viewer123"})
        assert seeded_client.get("/users").status_code == 403

    def test_viewer_cannot_access_verify(self, seeded_client):
        seeded_client.post("/login", data={"email": "viewer@test.com", "password": "viewer123"})
        assert seeded_client.get("/verify").status_code == 403
