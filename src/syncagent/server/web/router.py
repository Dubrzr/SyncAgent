"""Web UI routes for SyncAgent dashboard.

Provides a modern web interface for:
- Admin setup wizard
- Login/authentication
- File browser
- Machine management
- Invitation management
- Trash management
"""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import argon2
from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from syncagent.server.database import Database

# Password hasher
ph = argon2.PasswordHasher()

# Templates directory
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


def utcnow_naive() -> datetime:
    """Get current UTC time as naive datetime (for SQLite compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)


def get_db(request: Request) -> Database:
    """Get database from app state."""
    db: Database = request.app.state.db
    return db


# CSRF token management
def generate_csrf_token() -> str:
    """Generate a secure CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(session_token: str, csrf_token: str) -> bool:
    """Verify CSRF token matches expected value.

    For simplicity, we use HMAC of session token as CSRF token base.
    """
    import hashlib
    import hmac

    expected = hmac.new(
        session_token.encode(),
        b"csrf",
        hashlib.sha256
    ).hexdigest()[:32]

    return hmac.compare_digest(csrf_token, expected)


def get_csrf_token(session_token: str) -> str:
    """Get CSRF token for a session."""
    import hashlib
    import hmac

    return hmac.new(
        session_token.encode(),
        b"csrf",
        hashlib.sha256
    ).hexdigest()[:32]


# Authentication dependency
async def get_current_admin(
    request: Request,
    session: Annotated[str | None, Cookie()] = None,
) -> tuple[str, str]:
    """Get current admin from session cookie.

    Returns:
        Tuple of (admin_username, session_token)

    Raises:
        HTTPException: If not authenticated
    """
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db = get_db(request)
    session_obj = db.validate_session(session)

    if not session_obj:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    admin = db.get_admin()
    if not admin:
        raise HTTPException(status_code=401, detail="No admin configured")

    return (admin.username, session)


async def optional_admin(
    request: Request,
    session: Annotated[str | None, Cookie()] = None,
) -> tuple[str, str] | None:
    """Get current admin if authenticated, None otherwise."""
    if not session:
        return None

    db = get_db(request)
    session_obj = db.validate_session(session)

    if not session_obj:
        return None

    admin = db.get_admin()
    if not admin:
        return None

    return (admin.username, session)


# Router
router = APIRouter()


# ---------------------------------------------------------------------------
# Setup Wizard
# ---------------------------------------------------------------------------

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request) -> Response:
    """Show setup wizard if no admin exists."""
    db = get_db(request)

    if not db.needs_setup():
        return RedirectResponse(url="/login", status_code=302)

    csrf_token = generate_csrf_token()
    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "csrf_token": csrf_token}
    )


@router.post("/setup", response_class=HTMLResponse)
async def setup_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
) -> Response:
    """Process setup wizard submission."""
    db = get_db(request)

    if not db.needs_setup():
        return RedirectResponse(url="/login", status_code=302)

    # Validate input
    error = None
    if len(username) < 3:
        error = "Username must be at least 3 characters"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    elif password != confirm_password:
        error = "Passwords do not match"

    if error:
        csrf_token = generate_csrf_token()
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "csrf_token": csrf_token, "error": error}
        )

    # Create admin
    password_hash = ph.hash(password)
    db.create_admin(username, password_hash)

    # Create session and redirect
    raw_token, _ = db.create_session()
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session",
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


# ---------------------------------------------------------------------------
# Login/Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    """Show login page."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    csrf_token = generate_csrf_token()
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "csrf_token": csrf_token}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    """Process login submission."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    # Verify credentials
    admin = db.get_admin()
    error = None

    if not admin or admin.username != username:
        error = "Invalid username or password"
    else:
        try:
            ph.verify(admin.password_hash, password)
        except argon2.exceptions.VerifyMismatchError:
            error = "Invalid username or password"

    if error:
        csrf_token = generate_csrf_token()
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "csrf_token": csrf_token, "error": error}
        )

    # Create session
    raw_token, _ = db.create_session()
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session",
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.post("/logout")
async def logout(
    response: Response,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Logout and clear session."""
    redirect = RedirectResponse(url="/login", status_code=302)
    redirect.delete_cookie("session")
    return redirect


# ---------------------------------------------------------------------------
# Dashboard / Files
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def files_page(
    request: Request,
    admin: Annotated[tuple[str, str] | None, Depends(optional_admin)],
) -> Response:
    """Show files page (main dashboard)."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    if not admin:
        return RedirectResponse(url="/login", status_code=302)

    admin_username, session_token = admin

    # Get all active files
    files = db.list_files()

    return templates.TemplateResponse(
        "files.html",
        {
            "request": request,
            "csrf_token": get_csrf_token(session_token),
            "admin_username": admin_username,
            "active_tab": "files",
            "files": files,
        }
    )


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

@router.get("/machines", response_class=HTMLResponse)
async def machines_page(
    request: Request,
    admin: Annotated[tuple[str, str] | None, Depends(optional_admin)],
) -> Response:
    """Show machines page."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    if not admin:
        return RedirectResponse(url="/login", status_code=302)

    admin_username, session_token = admin

    # Get all machines
    machines = db.list_machines()
    now = utcnow_naive()

    return templates.TemplateResponse(
        "machines.html",
        {
            "request": request,
            "csrf_token": get_csrf_token(session_token),
            "admin_username": admin_username,
            "active_tab": "machines",
            "machines": machines,
            "now": now,
        }
    )


@router.post("/machines/{machine_id}/delete")
async def delete_machine(
    request: Request,
    machine_id: int,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Delete a machine."""
    db = get_db(request)
    db.delete_machine(machine_id)
    return RedirectResponse(url="/machines", status_code=302)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.get("/invitations", response_class=HTMLResponse)
async def invitations_page(
    request: Request,
    admin: Annotated[tuple[str, str] | None, Depends(optional_admin)],
) -> Response:
    """Show invitations page."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    if not admin:
        return RedirectResponse(url="/login", status_code=302)

    admin_username, session_token = admin

    # Get all invitations
    invitations = db.list_invitations()
    now = utcnow_naive()

    return templates.TemplateResponse(
        "invitations.html",
        {
            "request": request,
            "csrf_token": get_csrf_token(session_token),
            "admin_username": admin_username,
            "active_tab": "invitations",
            "invitations": invitations,
            "now": now,
            "new_invitation": None,
        }
    )


@router.post("/invitations", response_class=HTMLResponse)
async def create_invitation(
    request: Request,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> Response:
    """Create a new invitation."""
    db = get_db(request)
    admin_username, session_token = admin

    # Create invitation
    raw_token, _ = db.create_invitation()

    # Get all invitations
    invitations = db.list_invitations()
    now = utcnow_naive()

    return templates.TemplateResponse(
        "invitations.html",
        {
            "request": request,
            "csrf_token": get_csrf_token(session_token),
            "admin_username": admin_username,
            "active_tab": "invitations",
            "invitations": invitations,
            "now": now,
            "new_invitation": raw_token,
        }
    )


@router.post("/invitations/{invitation_id}/delete")
async def delete_invitation(
    request: Request,
    invitation_id: int,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Delete an invitation."""
    db = get_db(request)
    db.delete_invitation(invitation_id)
    return RedirectResponse(url="/invitations", status_code=302)


# ---------------------------------------------------------------------------
# Trash
# ---------------------------------------------------------------------------

@router.get("/trash", response_class=HTMLResponse)
async def trash_page(
    request: Request,
    admin: Annotated[tuple[str, str] | None, Depends(optional_admin)],
) -> Response:
    """Show trash page."""
    db = get_db(request)

    if db.needs_setup():
        return RedirectResponse(url="/setup", status_code=302)

    if not admin:
        return RedirectResponse(url="/login", status_code=302)

    admin_username, session_token = admin

    # Get deleted files
    deleted_files = db.list_deleted_files()
    now = utcnow_naive()

    return templates.TemplateResponse(
        "trash.html",
        {
            "request": request,
            "csrf_token": get_csrf_token(session_token),
            "admin_username": admin_username,
            "active_tab": "trash",
            "deleted_files": deleted_files,
            "now": now,
            "timedelta": timedelta,
        }
    )


@router.post("/trash/{file_id}/restore")
async def restore_file(
    request: Request,
    file_id: int,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Restore a file from trash."""
    db = get_db(request)
    db.restore_file(file_id)
    return RedirectResponse(url="/trash", status_code=302)


@router.post("/trash/{file_id}/delete")
async def permanently_delete_file(
    request: Request,
    file_id: int,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Permanently delete a file."""
    db = get_db(request)
    db.permanently_delete_file(file_id)
    return RedirectResponse(url="/trash", status_code=302)


@router.post("/trash/empty")
async def empty_trash(
    request: Request,
    admin: Annotated[tuple[str, str], Depends(get_current_admin)],
) -> RedirectResponse:
    """Empty the trash (permanently delete all deleted files)."""
    db = get_db(request)
    db.empty_trash()
    return RedirectResponse(url="/trash", status_code=302)
