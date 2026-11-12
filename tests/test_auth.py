import pytest

from app.data.db import create_db_engine, init_db, make_session_factory
from app.security.permissions import PermissionDeniedError
from app.security.session_context import get_current_user, set_current_user
from app.services.audit import recent_audit_log
from app.services.auth import (
    DuplicateUsernameError,
    InvalidCredentialsError,
    InvalidRoleError,
    authenticate,
    change_password,
    change_role,
    create_user,
    has_any_user,
    list_users,
    set_user_active,
)


@pytest.fixture()
def session():
    engine = create_db_engine(db_path=":memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture(autouse=True)
def reset_current_user():
    previous = get_current_user()
    set_current_user(None)
    yield
    set_current_user(previous)


def create_admin(session):
    """Create the first admin through the permitted bootstrap path."""
    admin = create_user(session, "admin", "correct horse battery staple", role="admin")
    session.commit()
    set_current_user(admin)
    return admin


def test_has_any_user_false_then_true(session):
    assert has_any_user(session) is False
    create_admin(session)
    assert has_any_user(session) is True


def test_first_account_must_be_admin(session):
    with pytest.raises(PermissionDeniedError):
        create_user(session, "worker", "password123", role="operator")

    assert has_any_user(session) is False


def test_password_is_never_stored_in_plaintext(session):
    user = create_admin(session)
    assert "correct horse battery staple" not in user.password_hash
    assert user.password_hash != "correct horse battery staple"


def test_authenticate_succeeds_with_correct_password(session):
    admin = create_admin(session)
    alice = create_user(session, "alice", "hunter2", role="operator")
    session.commit()

    # Simulate a login while another user is still in the context.
    set_current_user(admin)

    user = authenticate(session, "alice", "hunter2")

    assert user.username == "alice"

    entries = recent_audit_log(session)
    success = next(
        (log, actor)
        for log, actor in entries
        if log.action == "login_success"
    )

    log, actor = success
    assert log.user_id == alice.id
    assert actor is not None
    assert actor.username == "alice"


def test_authenticate_fails_with_wrong_password(session):
    create_admin(session)
    create_user(session, "alice", "hunter2", role="operator")
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "alice", "wrong-password")


def test_authenticate_fails_for_deactivated_user(session):
    create_admin(session)
    user = create_user(session, "bob", "password123", role="viewer")
    session.commit()

    set_user_active(session, user.id, False)
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "bob", "password123")


def test_create_user_rejects_duplicate_username(session):
    create_admin(session)

    with pytest.raises(DuplicateUsernameError):
        create_user(session, "admin", "pw2", role="manager")


def test_create_user_rejects_invalid_role(session):
    with pytest.raises(InvalidRoleError):
        create_user(session, "admin", "pw1", role="superuser")


def test_change_role_and_password(session):
    create_admin(session)
    user = create_user(session, "carol", "oldpassword", role="viewer")
    session.commit()

    change_role(session, user.id, "manager")
    change_password(session, user.id, "newpassword")
    session.commit()

    assert authenticate(session, "carol", "newpassword").role == "manager"

    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "carol", "oldpassword")


def test_list_users_returns_created_users(session):
    create_admin(session)
    create_user(session, "zeta", "pw", role="viewer")
    create_user(session, "alpha", "pw", role="viewer")
    session.commit()

    names = [u.username for u in list_users(session)]
    assert names == ["admin", "alpha", "zeta"]


@pytest.mark.parametrize("role", ["operator", "manager", "viewer", None])
def test_user_management_rejects_non_admin(session, role):
    create_admin(session)
    target = create_user(session, "target", "target-password", role="viewer")

    if role is None:
        set_current_user(None)
    else:
        actor = create_user(session, f"actor_{role}", "actor-password", role=role)
        session.commit()
        set_current_user(actor)

    with pytest.raises(PermissionDeniedError):
        create_user(session, "unauthorized", "password123", role="operator")

    with pytest.raises(PermissionDeniedError):
        list_users(session)

    with pytest.raises(PermissionDeniedError):
        set_user_active(session, target.id, False)

    with pytest.raises(PermissionDeniedError):
        change_role(session, target.id, "manager")

    with pytest.raises(PermissionDeniedError):
        change_password(session, target.id, "new-password")


def test_login_attempts_are_audited(session):
    admin = create_admin(session)

    # A real login attempt starts without an authenticated user.
    set_current_user(None)

    with pytest.raises(InvalidCredentialsError):
        authenticate(session, "admin", "wrong-password")

    authenticate(session, "admin", "correct horse battery staple")
    set_current_user(admin)

    entries = recent_audit_log(session)

    failed = next(
        log for log, _ in entries if log.action == "login_failed"
    )
    successful = next(
        log for log, _ in entries if log.action == "login_success"
    )

    assert failed.user_id is None
    assert successful.user_id == admin.id


def test_admin_cannot_deactivate_own_account(session):
    admin = create_admin(session)

    with pytest.raises(PermissionDeniedError):
        set_user_active(session, admin.id, False)

    assert admin.is_active is True


def test_admin_cannot_change_own_role(session):
    admin = create_admin(session)

    with pytest.raises(PermissionDeniedError):
        change_role(session, admin.id, "manager")

    assert admin.role == "admin"
