"""Credentials never leave this module: encrypted PII, scrypt hashes, opaque cookies."""
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


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + salt.hex() + '$' + digest.hex()


def password_matches(password, stored):
    try:
        _, n, r, p, salt, digest = stored.split('$')
        if (n, r, p) != ('16384', '8', '1'):
            return False
        candidate = password_hash(password, bytes.fromhex(salt)).split('$')[-1]
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


ROLES = ('Administrador', 'Operario', 'Conductor')
DEFAULT_ROLE = 'Conductor'


def role_of(conn, user_id):
    """Rol con más privilegios del usuario; sin asignación explícita es Conductor."""
    names = set(conn.execute(select(s.roles.c.name).select_from(s.user_roles.join(s.roles))
                             .where(s.user_roles.c.user_id == user_id)).scalars())
    return next((name for name in ROLES if name in names), DEFAULT_ROLE)


def set_role(conn, user_id, role):
    if role not in ROLES:
        raise HTTPException(422, 'Rol desconocido.')
    role_id = conn.execute(select(s.roles.c.id).where(s.roles.c.name == role)).scalar_one_or_none()
    if role_id is None:
        role_id = conn.execute(s.roles.insert().values(name=role).returning(s.roles.c.id)).scalar_one()
    conn.execute(delete(s.user_roles).where(s.user_roles.c.user_id == user_id))
    conn.execute(s.user_roles.insert().values(user_id=user_id, role_id=role_id))


def audit(conn, session_id, action, entity_id=None, details=None):
    """Huella interna por sesión. Nunca guarda contraseñas, tokens ni correos."""
    # entity_id es obligatorio en el esquema: sin entidad concreta, la huella apunta a la propia sesión.
    conn.execute(s.audit_events.insert().values(session_id=session_id, action=action[:180],
                                                entity_id=entity_id or session_id, details=details or {}))


def current_session(request: Request):
    token = request.cookies.get(COOKIE, '')
    if not token or len(token) > 100:
        raise HTTPException(401, 'Inicia sesión para continuar.')
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = s.now()
    with request.app.state.engine.connect() as conn:
        row = conn.execute(select(s.sessions.c.id, s.sessions.c.last_seen_at, s.devices.c.user_id)
            .select_from(s.sessions.join(s.devices).join(s.users, s.users.c.id == s.devices.c.user_id))
            .where(s.sessions.c.token_hash == digest, s.sessions.c.expires_at > now,
                   s.devices.c.user_id.is_not(None), s.users.c.active.is_(True))).mappings().first()
        if not row:
            raise HTTPException(401, 'Inicia sesión para continuar.')
        role = role_of(conn, row['user_id'])
        # Actividad de la sesión para medir su duración; como máximo una escritura cada 15 segundos.
        if not row['last_seen_at'] or now - row['last_seen_at'] > 15_000:
            conn.execute(update(s.sessions).where(s.sessions.c.id == row['id']).values(last_seen_at=now))
            conn.commit()
    return {'id': row['id'], 'user_id': row['user_id'], 'role': role}


def require_admin(session=Depends(current_session)):
    if session['role'] != 'Administrador':
        raise HTTPException(403, 'Esta sección es solo para administradores.')
    return session


def scan_owner(session=Depends(current_session)):
    return session['id']


def limit_attempt(request, email, record=True):
    vault = request.app.state.vault
    ip = vault.lookup('ip:' + (request.client.host if request.client else 'unknown'))
    account = vault.lookup('account:' + email)
    now = s.now()
    # Database limit shared between replicas; never store raw IPs or emails.
    with request.app.state.engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(771014)'))
        conn.execute(delete(s.auth_attempts).where(s.auth_attempts.c.created_at < now - 600_000))
        count_ip = conn.execute(select(func.count()).select_from(s.auth_attempts)
                               .where(s.auth_attempts.c.ip_hash == ip)).scalar_one()
        count_account = conn.execute(select(func.count()).select_from(s.auth_attempts)
                                    .where(s.auth_attempts.c.account_hash == account)).scalar_one()
        if count_ip >= 30 or count_account >= 10:
            raise HTTPException(429, 'No se pudo completar la operación. Inténtalo más tarde.')
        if record:
            conn.execute(s.auth_attempts.insert().values(ip_hash=ip, account_hash=account))


def record_failed_attempt(request, email):
    vault = request.app.state.vault
    with request.app.state.engine.begin() as conn:
        conn.execute(s.auth_attempts.insert().values(
            ip_hash=vault.lookup('ip:' + (request.client.host if request.client else 'unknown')),
            account_hash=vault.lookup('account:' + email)))


def demo_accounts(settings):
    return [
        {'role': 'Administrador', 'label': 'Administrador', 'description': 'Ve y gestiona todos los datos',
         'email': settings.demo_admin_email, 'password': settings.demo_admin_password, 'displayName': 'Administración BacheScan'},
        {'role': 'Operario', 'label': 'Operario', 'description': 'Revisa reportes y recorridos',
         'email': settings.demo_operator_email, 'password': settings.demo_operator_password, 'displayName': 'Operario de vías'},
        {'role': 'Conductor', 'label': 'Conductor', 'description': 'Escanea en moto o carro',
         'email': settings.demo_driver_email, 'password': settings.demo_driver_password, 'displayName': 'Conductor de prueba'},
    ]


def seed_demo_accounts(engine, vault, settings):
    """Crea o actualiza las cuentas demo con su rol y contraseña configurados."""
    if not settings.demo_accounts:
        return
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(771016)'))
        for account in demo_accounts(settings):
            email = account['email'].strip().lower()
            lookup = vault.lookup('email:' + email)
            user = conn.execute(select(s.users.c.id, s.users.c.password_hash)
                                .where(s.users.c.email_lookup == lookup)).mappings().first()
            if user is None:
                user_id = conn.execute(s.users.insert().values(email=vault.encrypt(email), email_lookup=lookup,
                    display_name=vault.encrypt(account['displayName']), password_hash=password_hash(account['password']))
                    .returning(s.users.c.id)).scalar_one()
            else:
                user_id = user['id']
                values = {'active': True}
                if not password_matches(account['password'], user['password_hash']):
                    values['password_hash'] = password_hash(account['password'])
                conn.execute(update(s.users).where(s.users.c.id == user_id).values(**values))
            set_role(conn, user_id, account['role'])


router = APIRouter(prefix='/api/auth')


@router.post('/register', status_code=201)
def register(payload: Registration, request: Request):
    limit_attempt(request, payload.email)
    if payload.password != payload.confirmPassword or not (
        re.search(r'[a-z]', payload.password) and re.search(r'[A-Z]', payload.password)
        and re.search(r'[0-9]', payload.password) and re.search(r'[^a-zA-Z0-9\s]', payload.password)
    ):
        raise HTTPException(400, FAILURE)
    vault = request.app.state.vault
    hashed = password_hash(payload.password)
    try:
        with request.app.state.engine.begin() as conn:
            user_id = conn.execute(s.users.insert().values(email=vault.encrypt(payload.email),
                email_lookup=vault.lookup('email:' + payload.email),
                display_name=vault.encrypt(payload.displayName), password_hash=hashed)
                .returning(s.users.c.id)).scalar_one()
            set_role(conn, user_id, DEFAULT_ROLE)
    except IntegrityError:
        raise HTTPException(400, FAILURE) from None
    return SUCCESS


@router.post('/login')
def login(payload: Credentials, request: Request, response: Response):
    # Solo los intentos fallidos consumen el límite: las cuentas demo compartidas no se bloquean.
    limit_attempt(request, payload.email, record=False)
    vault = request.app.state.vault
    with request.app.state.engine.connect() as conn:
        user = conn.execute(select(s.users.c.id, s.users.c.password_hash, s.users.c.active)
                            .where(s.users.c.email_lookup == vault.lookup('email:' + payload.email))).mappings().first()
    # Equal-cost password check even for an unknown account.
    stored = user['password_hash'] if user else request.app.state.dummy_password_hash
    valid = password_matches(payload.password, stored)
    if not user or not valid or not user['active']:
        record_failed_attempt(request, payload.email)
        raise HTTPException(401, FAILURE)
    token = secrets.token_urlsafe(32)
    expires = s.now() + request.app.state.settings.session_hours * 3600_000
    with request.app.state.engine.begin() as conn:
        device = conn.execute(s.devices.insert().values(user_id=user['id'], platform='mobile-pwa')
                              .returning(s.devices.c.id)).scalar_one()
        session_id = conn.execute(s.sessions.insert().values(device_id=device, last_seen_at=s.now(),
            token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires)
            .returning(s.sessions.c.id)).scalar_one()
        audit(conn, session_id, 'auth.login', details={'platform': 'mobile-pwa'})
    response.set_cookie(COOKIE, token, httponly=True, secure=request.app.state.settings.secure_cookies,
                        samesite='lax', max_age=request.app.state.settings.session_hours * 3600, path='/api')
    return SUCCESS


@router.get('/session')
def session_status(session=Depends(current_session)):
    return {'authenticated': True, 'role': session['role'], **SUCCESS}


@router.get('/demo')
def demo(request: Request):
    settings = request.app.state.settings
    if not settings.demo_accounts:
        return {'enabled': False, 'accounts': []}
    return {'enabled': True, 'accounts': [{key: value for key, value in account.items() if key != 'displayName'}
                                          for account in demo_accounts(settings)]}


@router.post('/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, '')
    if token:
        with request.app.state.engine.begin() as conn:
            # Reports and journeys reference the session: revoke without deleting their parent row.
            session_id = conn.execute(update(s.sessions).where(
                s.sessions.c.token_hash == hashlib.sha256(token.encode()).hexdigest(), s.sessions.c.ended_at.is_(None))
                .values(expires_at=0, ended_at=s.now()).returning(s.sessions.c.id)).scalar_one_or_none()
            if session_id:
                audit(conn, session_id, 'auth.logout')
    response.delete_cookie(COOKIE, path='/api', secure=request.app.state.settings.secure_cookies,
                           httponly=True, samesite='lax')
    return SUCCESS
