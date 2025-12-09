"""Tests for Web UI routes."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from syncagent.server.database import Database
from syncagent.server.web import router as web_router, ph


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """Create a temporary database."""
    return Database(tmp_path / "test.db")


@pytest.fixture
def app(tmp_db: Database) -> FastAPI:
    """Create a FastAPI app with web router."""
    app = FastAPI()
    app.state.db = tmp_db
    app.include_router(web_router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client that maintains cookies."""
    return TestClient(app, cookies={})


class TestSetupWizard:
    """Tests for setup wizard."""

    def test_setup_page_shows_when_no_admin(self, client: TestClient) -> None:
        """Should show setup page when no admin exists."""
        response = client.get("/setup")
        assert response.status_code == 200
        assert "Setup" in response.text or "admin" in response.text.lower()

    def test_setup_redirects_when_admin_exists(
        self, client: TestClient, tmp_db: Database
    ) -> None:
        """Should redirect to login when admin exists."""
        password_hash = ph.hash("password123")
        tmp_db.create_admin("admin", password_hash)

        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_setup_creates_admin(self, client: TestClient, tmp_db: Database) -> None:
        """Should create admin and redirect."""
        response = client.post(
            "/setup",
            data={
                "username": "admin",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        assert "session" in response.cookies

        # Admin should exist
        admin = tmp_db.get_admin()
        assert admin is not None
        assert admin.username == "admin"

    def test_setup_validates_password_length(self, client: TestClient) -> None:
        """Should reject short passwords."""
        response = client.post(
            "/setup",
            data={
                "username": "admin",
                "password": "short",
                "confirm_password": "short",
            },
        )
        assert response.status_code == 200
        assert "at least 8 characters" in response.text

    def test_setup_validates_password_match(self, client: TestClient) -> None:
        """Should reject mismatched passwords."""
        response = client.post(
            "/setup",
            data={
                "username": "admin",
                "password": "password123",
                "confirm_password": "different123",
            },
        )
        assert response.status_code == 200
        assert "Passwords do not match" in response.text


class TestLogin:
    """Tests for login functionality."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, tmp_db: Database) -> None:
        """Create admin user for login tests."""
        password_hash = ph.hash("password123")
        tmp_db.create_admin("admin", password_hash)

    def test_login_page_shows(self, client: TestClient) -> None:
        """Should show login page."""
        response = client.get("/login")
        assert response.status_code == 200
        assert "Sign in" in response.text

    def test_login_redirects_to_setup_when_no_admin(
        self, client: TestClient, tmp_db: Database
    ) -> None:
        """Should redirect to setup when no admin exists."""
        # Delete admin
        with tmp_db._session() as session:
            from syncagent.server.models import Admin

            admin = session.get(Admin, 1)
            if admin:
                session.delete(admin)
                session.commit()

        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/setup"

    def test_login_success(self, client: TestClient) -> None:
        """Should login and set session cookie."""
        response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        assert "session" in response.cookies

    def test_login_wrong_password(self, client: TestClient) -> None:
        """Should show error for wrong password."""
        response = client.post(
            "/login",
            data={"username": "admin", "password": "wrongpassword"},
        )
        assert response.status_code == 200
        assert "Invalid username or password" in response.text

    def test_login_wrong_username(self, client: TestClient) -> None:
        """Should show error for wrong username."""
        response = client.post(
            "/login",
            data={"username": "wronguser", "password": "password123"},
        )
        assert response.status_code == 200
        assert "Invalid username or password" in response.text


class TestAuthenticatedRoutes:
    """Tests for routes requiring authentication."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, tmp_db: Database) -> None:
        """Create admin user."""
        password_hash = ph.hash("password123")
        tmp_db.create_admin("admin", password_hash)

    def test_files_page_requires_auth(self, client: TestClient) -> None:
        """Should redirect to login without auth."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_files_page_shows_when_authenticated(
        self, client: TestClient
    ) -> None:
        """Should show files page when authenticated."""
        # Login and get the session cookie
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")
        assert session_cookie is not None

        # Use the session cookie
        response = client.get("/", cookies={"session": session_cookie})
        assert response.status_code == 200
        assert "Files" in response.text

    def test_machines_page_shows_when_authenticated(
        self, client: TestClient
    ) -> None:
        """Should show machines page when authenticated."""
        # Login
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        response = client.get("/machines", cookies={"session": session_cookie})
        assert response.status_code == 200
        assert "Machines" in response.text

    def test_invitations_page_shows_when_authenticated(
        self, client: TestClient
    ) -> None:
        """Should show invitations page when authenticated."""
        # Login
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        response = client.get("/invitations", cookies={"session": session_cookie})
        assert response.status_code == 200
        assert "Invitations" in response.text

    def test_trash_page_shows_when_authenticated(
        self, client: TestClient
    ) -> None:
        """Should show trash page when authenticated."""
        # Login
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        response = client.get("/trash", cookies={"session": session_cookie})
        assert response.status_code == 200
        assert "Trash" in response.text


class TestInvitations:
    """Tests for invitation management."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, tmp_db: Database) -> None:
        """Create admin user."""
        password_hash = ph.hash("password123")
        tmp_db.create_admin("admin", password_hash)

    def test_create_invitation(
        self, client: TestClient, tmp_db: Database
    ) -> None:
        """Should create a new invitation."""
        # Login
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        response = client.post("/invitations", cookies={"session": session_cookie})
        assert response.status_code == 200
        assert "Invitation Created" in response.text
        assert "INV-" in response.text

        # Check database
        invitations = tmp_db.list_invitations()
        assert len(invitations) == 1

    def test_delete_invitation(
        self, client: TestClient, tmp_db: Database
    ) -> None:
        """Should delete an invitation."""
        # Login
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        # Create invitation
        raw_token, inv = tmp_db.create_invitation()
        inv_id = inv.id

        response = client.post(
            f"/invitations/{inv_id}/delete",
            cookies={"session": session_cookie},
            follow_redirects=False,
        )
        assert response.status_code == 302

        # Check database
        invitations = tmp_db.list_invitations()
        assert len(invitations) == 0


class TestLogout:
    """Tests for logout functionality."""

    @pytest.fixture(autouse=True)
    def setup_admin(self, tmp_db: Database) -> None:
        """Create admin user."""
        password_hash = ph.hash("password123")
        tmp_db.create_admin("admin", password_hash)

    def test_logout_clears_session(self, client: TestClient) -> None:
        """Should clear session cookie on logout."""
        # Login first
        login_response = client.post(
            "/login",
            data={"username": "admin", "password": "password123"},
            follow_redirects=False,
        )
        session_cookie = login_response.cookies.get("session")

        # Logout
        response = client.post(
            "/logout",
            cookies={"session": session_cookie},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

        # Session should be cleared - accessing protected route should redirect
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"
