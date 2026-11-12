from app.security.session_context import get_current_user


class PermissionDeniedError(Exception):
    """Raised when the logged-in user lacks permission for an operation."""


def current_role() -> str | None:
    user = get_current_user()
    return user.role if user is not None else None


def require_authenticated() -> object:
    user = get_current_user()
    if user is None:
        raise PermissionDeniedError("You must be logged in to perform this action.")
    return user


def require_admin() -> object:
    user = require_authenticated()
    if user.role != "admin":
        raise PermissionDeniedError("Only an administrator can perform this action.")
    return user


def require_management_access() -> object:
    """Require an administrator or manager for master-data management."""
    user = require_authenticated()
    if user.role not in {"admin", "manager"}:
        raise PermissionDeniedError(
            "Only administrators and managers can manage reference data, "
            "suppliers, or customers."
        )
    return user


def require_operational_access() -> object:
    """Allow admin, manager and operator; restrict viewers to dashboard/products."""
    user = require_authenticated()
    if user.role not in {"admin", "manager", "operator"}:
        raise PermissionDeniedError(
            "Your account has view-only access to the dashboard and product list."
        )
    return user


def require_transaction_access() -> object:
    user = require_authenticated()
    if user.role not in {"admin", "manager", "operator"}:
        raise PermissionDeniedError("Your account cannot perform inventory transactions.")
    return user
