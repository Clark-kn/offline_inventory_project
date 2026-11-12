from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import AuditLog
from app.security.permissions import require_admin
from app.security.session_context import current_user_id


def log_action(
    session: Session,
    action: str,
    details: str | None = None,
    actor_user_id: int | None = None,
) -> AuditLog:
    user_id = actor_user_id if actor_user_id is not None else current_user_id()
    entry = AuditLog(user_id=user_id, action=action, details=details)
    session.add(entry)
    session.flush()
    return entry


def recent_audit_log(session: Session, limit: int = 100):
    require_admin()
    from app.data.models import User

    stmt = (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    return session.execute(stmt).all()
