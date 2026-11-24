"""Safe demonstration mode.

The demo credentials are public (``GET /api/auth/demo``), so anybody can sign in
as the demo administrator. Without this policy a visitor could read the e-mail
addresses and trip places of real people, promote accounts or deactivate them.

With ``DEMO_READ_ONLY=true`` (default):
* demo sessions cannot change shared data: roles, account access, pothole
  statuses and duplicate merges answer 403;
* when a demo administrator lists real accounts, e-mails and trip places of
  non-demo users are masked.
Demo accounts can still scan, report potholes and record their own trips.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .auth import DemoAccounts, SessionGuard
from . import schema as s

READ_ONLY_MESSAGE = 'Las cuentas de demostración son de solo lectura en esta sección. Inicia sesión con una cuenta propia.'
HIDDEN = 'Oculto en la demostración'


class DemoPolicy:
    def __init__(self, engine, vault, settings):
        self.settings = settings
        self.user_ids: frozenset[str] = frozenset()
        if settings.demo_accounts:
            lookups = [vault.lookup('email:' + account['email'].strip().lower()) for account in DemoAccounts.list(settings)]
            with engine.connect() as conn:
                self.user_ids = frozenset(conn.execute(select(s.users.c.id).where(s.users.c.email_lookup.in_(lookups))).scalars())

    @property
    def read_only(self) -> bool:
        return bool(self.settings.demo_read_only)

    def is_demo(self, user_id: str | None) -> bool:
        return user_id in self.user_ids

    def restricts(self, session: dict) -> bool:
        """True when this session must not change shared data or see real people's details."""
        return self.read_only and self.is_demo(session.get('user_id'))

    @staticmethod
    def mask_email(email: str) -> str:
        """'samuel@gmail.com' -> 's•••@g•••.com'; keeps the shape without revealing the address."""
        local, _, domain = (email or '').partition('@')
        host, dot, suffix = domain.rpartition('.')
        if not local or not host:
            return '•••'
        return f'{local[0]}•••@{host[0]}•••{dot}{suffix}'


def demo_policy(request: Request) -> DemoPolicy:
    return request.app.state.demo_policy


def forbid_demo_writes(request: Request, session=Depends(SessionGuard.current)):
    """Dependency for endpoints that change data shared with other people."""
    if demo_policy(request).restricts(session):
        raise HTTPException(403, READ_ONLY_MESSAGE)
    return session
