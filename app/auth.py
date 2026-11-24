"""Authentication. Credentials never leave this module: encrypted PII, scrypt hashes, opaque cookies."""
import base64
import hashlib
import hmac
import re
import secrets
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from . import schema as s
from .structures import HashSet

COOKIE = 'bachescan_auth'
SUCCESS = {'message': 'Todo se ejecutó correctamente.'}
FAILURE = 'No se pudo completar la operación. Revisa los requisitos e inténtalo de nuevo.'


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=5, max_length=180)
    password: str = Field(min_length=12, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('invalid')
        return value


class Registration(Credentials):
    displayName: str = Field(min_length=2, max_length=80)
    confirmPassword: str = Field(min_length=12, max_length=128)

    @field_validator('displayName')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if len(value) < 2 or any(ord(c) < 32 for c in value):
            raise ValueError('invalid')
        return value


class Vault:
    """Symmetric encryption (Fernet) for personal data plus keyed lookups (HMAC) for searching it."""

    def __init__(self, key):
        if not key:
            raise RuntimeError('Configura DATA_ENCRYPTION_KEY antes de iniciar el servicio.')
        self.fernet = Fernet(key.encode())
        self.lookup_key = hashlib.sha256(base64.urlsafe_b64decode(key) + b'bachescan-lookup-v1').digest()

    def encrypt(self, value):
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value):
        return self.fernet.decrypt(value.encode()).decode()

    def lookup(self, value):
        return hmac.new(self.lookup_key, value.encode(), hashlib.sha256).hexdigest()


class PasswordHasher:
    """Salted scrypt hashes in the format ``scrypt$N$r$p$salt$digest``."""
    PREFIX = 'scrypt$16384$8$1$'

    @staticmethod
    def hash(password, salt=None):
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return PasswordHasher.PREFIX + salt.hex() + '$' + digest.hex()

    @staticmethod
    def matches(password, stored):
        try:
            _, n, r, p, salt, digest = stored.split('$')
            if (n, r, p) != ('16384', '8', '1'):
                return False
            candidate = PasswordHasher.hash(password, bytes.fromhex(salt)).split('$')[-1]
            return hmac.compare_digest(candidate, digest)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_strong(password):
        return bool(re.search(r'[a-z]', password) and re.search(r'[A-Z]', password)
                    and re.search(r'[0-9]', password) and re.search(r'[^a-zA-Z0-9\s]', password))


class Roles:
    """Role names ordered from most to least privileged."""
    ADMIN, OPERATOR, DRIVER = 'Administrador', 'Operario', 'Conductor'
    ALL = (ADMIN, OPERATOR, DRIVER)
    DEFAULT = DRIVER

    @staticmethod
    def of(conn, user_id):
        """Most privileged role of the user; users without an explicit role are drivers."""
        names = HashSet(conn.execute(select(s.roles.c.name).select_from(s.user_roles.join(s.roles))
                                     .where(s.user_roles.c.user_id == user_id)).scalars())
        for name in Roles.ALL:
            if name in names:
                return name
        return Roles.DEFAULT

    @staticmethod
    def assign(conn, user_id, role):
        if role not in Roles.ALL:
            raise HTTPException(422, 'Rol desconocido.')
        role_id = conn.execute(select(s.roles.c.id).where(s.roles.c.name == role)).scalar_one_or_none()
        if role_id is None:
            role_id = conn.execute(s.roles.insert().values(name=role).returning(s.roles.c.id)).scalar_one()
        conn.execute(delete(s.user_roles).where(s.user_roles.c.user_id == user_id))
        conn.execute(s.user_roles.insert().values(user_id=user_id, role_id=role_id))


class AuditLog:
    """Internal per-session trail. It never stores passwords, tokens or e-mail addresses."""

    @staticmethod
    def record(conn, session_id, action, entity_id=None, details=None):
        # entity_id is mandatory in the schema: without a concrete entity the event points to the session.
        conn.execute(s.audit_events.insert().values(session_id=session_id, action=action[:180],
                                                    entity_id=entity_id or session_id, details=details or {}))


class SessionGuard:
    """FastAPI dependencies that resolve the session cookie into ``{id, user_id, role}``."""
    ACTIVITY_WRITE_INTERVAL_MS = 15_000

    @staticmethod
    def current(request: Request):
        token = request.cookies.get(COOKIE, '')
        if not token or len(token) > 100:
            raise HTTPException(401, 'Inicia sesión para continuar.')
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = s.Clock.now()
        with request.app.state.engine.connect() as conn:
            row = conn.execute(select(s.sessions.c.id, s.sessions.c.last_seen_at, s.devices.c.user_id)
                .select_from(s.sessions.join(s.devices).join(s.users, s.users.c.id == s.devices.c.user_id))
                .where(s.sessions.c.token_hash == digest, s.sessions.c.expires_at > now,
                       s.devices.c.user_id.is_not(None), s.users.c.active.is_(True))).mappings().first()
            if not row:
                raise HTTPException(401, 'Inicia sesión para continuar.')
            role = Roles.of(conn, row['user_id'])
            # Session activity measures its duration; at most one write every 15 seconds.
            if not row['last_seen_at'] or now - row['last_seen_at'] > SessionGuard.ACTIVITY_WRITE_INTERVAL_MS:
                conn.execute(update(s.sessions).where(s.sessions.c.id == row['id']).values(last_seen_at=now))
                conn.commit()
        return {'id': row['id'], 'user_id': row['user_id'], 'role': role}

    @staticmethod
    def admin(session=Depends(current.__func__)):
        if session['role'] != Roles.ADMIN:
            raise HTTPException(403, 'Esta sección es solo para administradores.')
        return session

    @staticmethod
    def session_id(session=Depends(current.__func__)):
        return session['id']


class LoginRateLimiter:
    """Shared limit of attempts per IP and per account over 10 minutes (stored as HMACs only)."""
    WINDOW_MS, MAX_PER_IP, MAX_PER_ACCOUNT = 600_000, 30, 10

    @staticmethod
    def _keys(request, email):
        vault = request.app.state.vault
        ip = vault.lookup('ip:' + (request.client.host if request.client else 'unknown'))
        return ip, vault.lookup('account:' + email)

    @classmethod
    def check(cls, request, email, record=True):
        ip, account = cls._keys(request, email)
        now = s.Clock.now()
        # The limit lives in the database so it is shared between replicas.
        with request.app.state.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771014)'))
            conn.execute(delete(s.auth_attempts).where(s.auth_attempts.c.created_at < now - cls.WINDOW_MS))
            count_ip = conn.execute(select(func.count()).select_from(s.auth_attempts)
                                   .where(s.auth_attempts.c.ip_hash == ip)).scalar_one()
            count_account = conn.execute(select(func.count()).select_from(s.auth_attempts)
                                        .where(s.auth_attempts.c.account_hash == account)).scalar_one()
            if count_ip >= cls.MAX_PER_IP or count_account >= cls.MAX_PER_ACCOUNT:
                raise HTTPException(429, 'No se pudo completar la operación. Inténtalo más tarde.')
            if record:
                conn.execute(s.auth_attempts.insert().values(ip_hash=ip, account_hash=account))

    @classmethod
    def record_failure(cls, request, email):
        ip, account = cls._keys(request, email)
        with request.app.state.engine.begin() as conn:
            conn.execute(s.auth_attempts.insert().values(ip_hash=ip, account_hash=account))


class DemoAccounts:
    """Administrator, operator and driver demo accounts, created or refreshed on start-up."""

    @staticmethod
    def list(settings):
        return [
            {'role': Roles.ADMIN, 'label': 'Administrador', 'description': 'Ve y gestiona todos los datos',
             'email': settings.demo_admin_email, 'password': settings.demo_admin_password, 'displayName': 'Administración BacheScan'},
            {'role': Roles.OPERATOR, 'label': 'Operario', 'description': 'Revisa reportes y recorridos',
             'email': settings.demo_operator_email, 'password': settings.demo_operator_password, 'displayName': 'Operario de vías'},
            {'role': Roles.DRIVER, 'label': 'Conductor', 'description': 'Escanea en moto o carro',
             'email': settings.demo_driver_email, 'password': settings.demo_driver_password, 'displayName': 'Conductor de prueba'},
        ]

    @staticmethod
    def seed(engine, vault, settings):
        if not settings.demo_accounts:
            return
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771016)'))
            for account in DemoAccounts.list(settings):
                email = account['email'].strip().lower()
                lookup = vault.lookup('email:' + email)
                user = conn.execute(select(s.users.c.id, s.users.c.password_hash)
                                    .where(s.users.c.email_lookup == lookup)).mappings().first()
                if user is None:
                    user_id = conn.execute(s.users.insert().values(email=vault.encrypt(email), email_lookup=lookup,
                        display_name=vault.encrypt(account['displayName']), password_hash=PasswordHasher.hash(account['password']))
                        .returning(s.users.c.id)).scalar_one()
                else:
                    user_id = user['id']
                    values = {'active': True}
                    if not PasswordHasher.matches(account['password'], user['password_hash']):
                        values['password_hash'] = PasswordHasher.hash(account['password'])
                    conn.execute(update(s.users).where(s.users.c.id == user_id).values(**values))
                Roles.assign(conn, user_id, account['role'])


class AuthController:
    """Routes under /api/auth: register, login, logout, session status and demo accounts."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/auth')
        self.router.add_api_route('/register', self.register, methods=['POST'], status_code=201)
        self.router.add_api_route('/login', self.login, methods=['POST'])
        self.router.add_api_route('/session', self.session_status, methods=['GET'])
        self.router.add_api_route('/demo', self.demo, methods=['GET'])
        self.router.add_api_route('/logout', self.logout, methods=['POST'])

    def register(self, payload: Registration, request: Request):
        LoginRateLimiter.check(request, payload.email)
        if payload.password != payload.confirmPassword or not PasswordHasher.is_strong(payload.password):
            raise HTTPException(400, FAILURE)
        vault = request.app.state.vault
        hashed = PasswordHasher.hash(payload.password)
        try:
            with request.app.state.engine.begin() as conn:
                user_id = conn.execute(s.users.insert().values(email=vault.encrypt(payload.email),
                    email_lookup=vault.lookup('email:' + payload.email),
                    display_name=vault.encrypt(payload.displayName), password_hash=hashed)
                    .returning(s.users.c.id)).scalar_one()
                Roles.assign(conn, user_id, Roles.DEFAULT)
        except IntegrityError:
            raise HTTPException(400, FAILURE) from None
        return SUCCESS

    def login(self, payload: Credentials, request: Request, response: Response):
        # Only failed attempts count towards the limit, so shared demo accounts are never locked.
        LoginRateLimiter.check(request, payload.email, record=False)
        vault = request.app.state.vault
        with request.app.state.engine.connect() as conn:
            user = conn.execute(select(s.users.c.id, s.users.c.password_hash, s.users.c.active)
                                .where(s.users.c.email_lookup == vault.lookup('email:' + payload.email))).mappings().first()
        # Equal-cost password check even for an unknown account.
        stored = user['password_hash'] if user else request.app.state.dummy_password_hash
        valid = PasswordHasher.matches(payload.password, stored)
        if not user or not valid or not user['active']:
            LoginRateLimiter.record_failure(request, payload.email)
            raise HTTPException(401, FAILURE)
        token = secrets.token_urlsafe(32)
        settings = request.app.state.settings
        expires = s.Clock.now() + settings.session_hours * 3600_000
        with request.app.state.engine.begin() as conn:
            device = conn.execute(s.devices.insert().values(user_id=user['id'], platform='mobile-pwa')
                                  .returning(s.devices.c.id)).scalar_one()
            session_id = conn.execute(s.sessions.insert().values(device_id=device, last_seen_at=s.Clock.now(),
                token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires)
                .returning(s.sessions.c.id)).scalar_one()
            AuditLog.record(conn, session_id, 'auth.login', details={'platform': 'mobile-pwa'})
        response.set_cookie(COOKIE, token, httponly=True, secure=settings.secure_cookies,
                            samesite='lax', max_age=settings.session_hours * 3600, path='/api')
        return SUCCESS

    def session_status(self, session=Depends(SessionGuard.current)):
        return {'authenticated': True, 'role': session['role'], **SUCCESS}

    def demo(self, request: Request):
        settings = request.app.state.settings
        if not settings.demo_accounts:
            return {'enabled': False, 'accounts': []}
        return {'enabled': True, 'accounts': [{key: value for key, value in account.items() if key != 'displayName'}
                                              for account in DemoAccounts.list(settings)]}

    def logout(self, request: Request, response: Response):
        token = request.cookies.get(COOKIE, '')
        if token:
            with request.app.state.engine.begin() as conn:
                # Reports and trips reference the session: revoke it without deleting the row.
                session_id = conn.execute(update(s.sessions).where(
                    s.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(), s.sessions.c.ended_at.is_(None))
                    .values(expires_at=0, ended_at=s.Clock.now()).returning(s.sessions.c.id)).scalar_one_or_none()
                if session_id:
                    AuditLog.record(conn, session_id, 'auth.logout')
        settings = request.app.state.settings
        response.delete_cookie(COOKIE, path='/api', secure=settings.secure_cookies, httponly=True, samesite='lax')
        return SUCCESS
