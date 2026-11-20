from dataclasses import dataclass
from typing import Any, Literal, get_args

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import NotificationSettings
from app.notifications.config import (
    BrevoConfig,
    MailgunConfig,
    MailtrapConfig,
    NotificationConfig,
    ProviderConfig,
    SmtpConfig,
    _provider_from_env,
    config_from_env,
)
from app.notifications.secrets import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.notifications.transports import NotificationConfigError, build_transport
from app.schemas.notification import (
    NotificationProviderValue,
    NotificationSettingsSource,
    NotificationSettingsUpdate,
)

SINGLETON_ID = 1
DEFAULT_FROM_NAME = "Uptime Monitor"
DEFAULT_SMTP_PORT = 587
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAILGUN_API_URL = "https://api.mailgun.net/v3"
DECRYPTION_FAILURE = (
    "The saved notification secrets cannot be decrypted with the current JWT_SECRET. "
    "Enter the secret again and save."
)

SecretStatus = Literal["unset", "set", "unreadable"]

_VALID_PROVIDERS: tuple[NotificationProviderValue, ...] = get_args(NotificationProviderValue)


@dataclass(frozen=True, slots=True)
class _ProviderSecretSpec:
    provider: NotificationProviderValue
    input_field: str
    column_name: str


_PROVIDER_SECRET_SPECS: tuple[_ProviderSecretSpec, ...] = (
    _ProviderSecretSpec("smtp", "smtp_password", "smtp_password_encrypted"),
    _ProviderSecretSpec("brevo", "brevo_api_key", "brevo_api_key_encrypted"),
    _ProviderSecretSpec("mailgun", "mailgun_api_key", "mailgun_api_key_encrypted"),
    _ProviderSecretSpec("mailtrap", "mailtrap_api_token", "mailtrap_api_token_encrypted"),
)


@dataclass(frozen=True, slots=True)
class NotificationSettingsSnapshot:
    """Redacted view of effective notification settings without plaintext secrets."""

    enabled: bool
    provider: NotificationProviderValue
    configured: bool
    source: NotificationSettingsSource
    from_address: str | None
    from_name: str
    recipients: tuple[str, ...]
    timeout_seconds: float
    smtp_host: str | None
    smtp_port: int
    smtp_starttls: bool
    smtp_ssl: bool
    smtp_username: str | None
    smtp_password_state: SecretStatus
    brevo_api_key_state: SecretStatus
    mailgun_domain: str | None
    mailgun_api_url: str | None
    mailgun_api_key_state: SecretStatus
    mailtrap_api_token_state: SecretStatus
    provider_credentials_set: bool
    unreadable_secrets: tuple[NotificationProviderValue, ...]


def _normalize_provider(value: str) -> NotificationProviderValue:
    for provider in _VALID_PROVIDERS:
        if value == provider:
            return provider
    return "smtp"


def _probe_secret(token: str | None, settings: Settings) -> SecretStatus:
    if token is None:
        return "unset"
    try:
        decrypt_secret(token, jwt_secret=settings.jwt_secret)
    except SecretDecryptionError:
        return "unreadable"
    return "set"


def _transport_ready(provider_config: ProviderConfig, timeout_seconds: float) -> bool:
    try:
        build_transport(provider_config, timeout_seconds)
    except NotificationConfigError:
        return False
    return True


def _decrypt(token: str, settings: Settings, *, field: str | None = None) -> str:
    try:
        return decrypt_secret(token, jwt_secret=settings.jwt_secret)
    except SecretDecryptionError:
        raise NotificationConfigError(DECRYPTION_FAILURE, field=field) from None


def _stored_secret(
    token: str | None,
    settings: Settings,
    *,
    field: str | None = None,
) -> str | None:
    return _decrypt(token, settings, field=field) if token is not None else None


def _provider_from_row(row: NotificationSettings, settings: Settings) -> ProviderConfig:
    if row.provider == "smtp":
        return SmtpConfig(
            host=row.smtp_host,
            port=row.smtp_port,
            username=row.smtp_username,
            password=_stored_secret(row.smtp_password_encrypted, settings),
            start_tls=row.smtp_starttls,
            use_tls=row.smtp_ssl,
        )
    if row.provider == "brevo":
        return BrevoConfig(api_key=_stored_secret(row.brevo_api_key_encrypted, settings))
    if row.provider == "mailgun":
        return MailgunConfig(
            api_key=_stored_secret(row.mailgun_api_key_encrypted, settings),
            domain=row.mailgun_domain,
            api_url=row.mailgun_api_url or DEFAULT_MAILGUN_API_URL,
        )
    if row.provider == "mailtrap":
        return MailtrapConfig(api_token=_stored_secret(row.mailtrap_api_token_encrypted, settings))
    raise NotificationConfigError("The saved notification provider is not supported")


def build_notification_config(
    row: NotificationSettings,
    settings: Settings,
) -> NotificationConfig:
    return NotificationConfig(
        enabled=row.enabled,
        provider=_provider_from_row(row, settings),
        sender_email=row.from_address,
        sender_name=row.from_name,
        recipients=tuple(row.recipients),
        timeout_seconds=row.timeout_seconds,
    )


async def get_notification_settings_row(
    session: AsyncSession,
) -> NotificationSettings | None:
    return await session.get(NotificationSettings, SINGLETON_ID)


async def load_notification_config(
    session: AsyncSession,
    settings: Settings,
) -> NotificationConfig | None:
    row = await get_notification_settings_row(session)
    if row is None:
        return config_from_env(settings)
    return build_notification_config(row, settings)


def _snapshot_from_env(settings: Settings) -> NotificationSettingsSnapshot:
    env_config = config_from_env(settings)
    provider_cfg = env_config.provider if env_config else _provider_from_env(settings)
    credentials_ok = _transport_ready(provider_cfg, settings.notification_timeout_seconds)
    configured = env_config is not None and credentials_ok
    from_address = (
        env_config.sender_email
        if env_config
        else (str(settings.email_from_address) if settings.email_from_address else None)
    )
    return NotificationSettingsSnapshot(
        enabled=env_config.enabled if env_config else settings.email_notifications_enabled,
        provider=settings.email_provider,
        configured=configured,
        source="environment",
        from_address=from_address,
        from_name=(
            env_config.sender_name
            if env_config
            else (settings.email_from_name.strip() or DEFAULT_FROM_NAME)
        ),
        recipients=(
            env_config.recipients
            if env_config
            else tuple(str(recipient) for recipient in settings.notification_recipients)
        ),
        timeout_seconds=(
            env_config.timeout_seconds if env_config else settings.notification_timeout_seconds
        ),
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_starttls=settings.smtp_starttls,
        smtp_ssl=settings.smtp_ssl,
        smtp_username=settings.smtp_username,
        smtp_password_state="set" if settings.smtp_password is not None else "unset",
        brevo_api_key_state="set" if settings.brevo_api_key is not None else "unset",
        mailgun_domain=settings.mailgun_domain,
        mailgun_api_url=settings.mailgun_api_url,
        mailgun_api_key_state="set" if settings.mailgun_api_key is not None else "unset",
        mailtrap_api_token_state="set" if settings.mailtrap_api_token is not None else "unset",
        provider_credentials_set=credentials_ok,
        unreadable_secrets=(),
    )


def _snapshot_from_row(
    row: NotificationSettings,
    settings: Settings,
) -> NotificationSettingsSnapshot:
    provider = _normalize_provider(row.provider)
    secret_states: dict[str, SecretStatus] = {}
    unreadable: list[NotificationProviderValue] = []
    for spec in _PROVIDER_SECRET_SPECS:
        status = _probe_secret(getattr(row, spec.column_name), settings)
        secret_states[spec.input_field] = status
        if status == "unreadable":
            unreadable.append(spec.provider)

    try:
        config = build_notification_config(row, settings)
    except (NotificationConfigError, SecretDecryptionError):
        configured = False
    else:
        configured = _transport_ready(config.provider, config.timeout_seconds)

    return NotificationSettingsSnapshot(
        enabled=row.enabled,
        provider=provider,
        configured=configured,
        source="database",
        from_address=row.from_address,
        from_name=row.from_name,
        recipients=tuple(row.recipients),
        timeout_seconds=row.timeout_seconds,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_starttls=row.smtp_starttls,
        smtp_ssl=row.smtp_ssl,
        smtp_username=row.smtp_username,
        smtp_password_state=secret_states["smtp_password"],
        brevo_api_key_state=secret_states["brevo_api_key"],
        mailgun_domain=row.mailgun_domain,
        mailgun_api_url=row.mailgun_api_url,
        mailgun_api_key_state=secret_states["mailgun_api_key"],
        mailtrap_api_token_state=secret_states["mailtrap_api_token"],
        provider_credentials_set=configured,
        unreadable_secrets=tuple(unreadable),
    )


async def load_notification_settings_snapshot(
    session: AsyncSession,
    settings: Settings,
) -> NotificationSettingsSnapshot:
    """Load redacted settings without failing when stored secrets fail decryption."""
    row = await get_notification_settings_row(session)
    if row is None:
        return _snapshot_from_env(settings)
    return _snapshot_from_row(row, settings)


def _env_seed(settings: Settings) -> dict[str, Any]:
    """Starting values for the first save, derived from the environment."""
    config = config_from_env(settings)
    provider = config.provider if config is not None else None
    smtp = provider if isinstance(provider, SmtpConfig) else None
    return {
        "enabled": config.enabled if config is not None else False,
        "provider": config.provider_name if config is not None else "smtp",
        "from_address": config.sender_email if config is not None else None,
        "from_name": config.sender_name if config is not None else DEFAULT_FROM_NAME,
        "recipients": list(config.recipients) if config is not None else [],
        "timeout_seconds": (
            config.timeout_seconds if config is not None else DEFAULT_TIMEOUT_SECONDS
        ),
        "smtp_host": smtp.host if smtp is not None else None,
        "smtp_port": smtp.port if smtp is not None else DEFAULT_SMTP_PORT,
        "smtp_starttls": smtp.start_tls if smtp is not None else True,
        "smtp_ssl": smtp.use_tls if smtp is not None else False,
        "smtp_username": smtp.username if smtp is not None else None,
        "mailgun_domain": settings.mailgun_domain,
        "mailgun_api_url": settings.mailgun_api_url,
    }


def _row_seed(row: NotificationSettings) -> dict[str, Any]:
    return {
        "enabled": row.enabled,
        "provider": row.provider,
        "from_address": row.from_address,
        "from_name": row.from_name,
        "recipients": list(row.recipients),
        "timeout_seconds": row.timeout_seconds,
        "smtp_host": row.smtp_host,
        "smtp_port": row.smtp_port,
        "smtp_starttls": row.smtp_starttls,
        "smtp_ssl": row.smtp_ssl,
        "smtp_username": row.smtp_username,
        "mailgun_domain": row.mailgun_domain,
        "mailgun_api_url": row.mailgun_api_url,
    }


def _provider_from_update(
    values: dict[str, Any],
    provided: dict[str, Any],
    settings: Settings,
    *,
    smtp_password_encrypted: str | None,
    brevo_api_key_encrypted: str | None,
    mailgun_api_key_encrypted: str | None,
    mailtrap_api_token_encrypted: str | None,
) -> ProviderConfig:
    provider = values["provider"]
    if provider == "smtp":
        password = None
        if smtp_password_encrypted is not None:
            password = (
                str(provided["smtp_password"])
                if provided.get("smtp_password") is not None
                else _decrypt(smtp_password_encrypted, settings, field="smtp_password")
            )
        return SmtpConfig(
            host=values["smtp_host"],
            port=values["smtp_port"],
            username=values["smtp_username"],
            password=password,
            start_tls=values["smtp_starttls"],
            use_tls=values["smtp_ssl"],
        )
    if provider == "brevo":
        api_key = (
            str(provided["brevo_api_key"])
            if provided.get("brevo_api_key") is not None
            else _stored_secret(brevo_api_key_encrypted, settings, field="brevo_api_key")
        )
        return BrevoConfig(api_key=api_key)
    if provider == "mailgun":
        api_key = (
            str(provided["mailgun_api_key"])
            if provided.get("mailgun_api_key") is not None
            else _stored_secret(mailgun_api_key_encrypted, settings, field="mailgun_api_key")
        )
        return MailgunConfig(
            api_key=api_key,
            domain=values["mailgun_domain"],
            api_url=values["mailgun_api_url"] or DEFAULT_MAILGUN_API_URL,
        )
    if provider == "mailtrap":
        api_token = (
            str(provided["mailtrap_api_token"])
            if provided.get("mailtrap_api_token") is not None
            else _stored_secret(mailtrap_api_token_encrypted, settings, field="mailtrap_api_token")
        )
        return MailtrapConfig(api_token=api_token)
    raise NotificationConfigError("The saved notification provider is not supported")


async def save_notification_config(
    session: AsyncSession,
    settings: Settings,
    update: NotificationSettingsUpdate,
) -> NotificationConfig:
    row = await get_notification_settings_row(session)
    values = _row_seed(row) if row is not None else _env_seed(settings)
    provided = update.model_dump(exclude_unset=True)

    smtp_password_encrypted = row.smtp_password_encrypted if row is not None else None
    brevo_api_key_encrypted = row.brevo_api_key_encrypted if row is not None else None
    mailgun_api_key_encrypted = row.mailgun_api_key_encrypted if row is not None else None
    mailtrap_api_token_encrypted = row.mailtrap_api_token_encrypted if row is not None else None
    if row is None:
        env_config = config_from_env(settings)
        env_provider = env_config.provider if env_config is not None else None
        if isinstance(env_provider, SmtpConfig) and env_provider.password is not None:
            smtp_password_encrypted = encrypt_secret(
                env_provider.password, jwt_secret=settings.jwt_secret
            )
        if isinstance(env_provider, BrevoConfig) and env_provider.api_key is not None:
            brevo_api_key_encrypted = encrypt_secret(
                env_provider.api_key, jwt_secret=settings.jwt_secret
            )
        if isinstance(env_provider, MailgunConfig) and env_provider.api_key is not None:
            mailgun_api_key_encrypted = encrypt_secret(
                env_provider.api_key, jwt_secret=settings.jwt_secret
            )
        if isinstance(env_provider, MailtrapConfig) and env_provider.api_token is not None:
            mailtrap_api_token_encrypted = encrypt_secret(
                env_provider.api_token, jwt_secret=settings.jwt_secret
            )

    if "enabled" in provided:
        values["enabled"] = bool(provided["enabled"])
    if "provider" in provided:
        values["provider"] = provided["provider"]
    if "from_address" in provided:
        address = provided["from_address"]
        values["from_address"] = str(address) if address is not None else None
    if "from_name" in provided:
        values["from_name"] = str(provided["from_name"] or "").strip() or DEFAULT_FROM_NAME
    if "recipients" in provided:
        values["recipients"] = [str(recipient) for recipient in provided["recipients"] or []]
    if "timeout_seconds" in provided:
        values["timeout_seconds"] = float(provided["timeout_seconds"])
    if "smtp_host" in provided:
        host = provided["smtp_host"]
        values["smtp_host"] = str(host).strip() if host is not None else None
    if "smtp_port" in provided:
        values["smtp_port"] = int(provided["smtp_port"])
    if "smtp_starttls" in provided:
        values["smtp_starttls"] = bool(provided["smtp_starttls"])
    if "smtp_ssl" in provided:
        values["smtp_ssl"] = bool(provided["smtp_ssl"])
    if "smtp_username" in provided:
        username = provided["smtp_username"]
        values["smtp_username"] = str(username).strip() if username is not None else None
    if "smtp_password" in provided and provided["smtp_password"] is not None:
        smtp_password_encrypted = encrypt_secret(
            str(provided["smtp_password"]), jwt_secret=settings.jwt_secret
        )
    if values["smtp_username"] is None and provided.get("smtp_password") is None:
        smtp_password_encrypted = None
    if "brevo_api_key" in provided and provided["brevo_api_key"] is not None:
        brevo_api_key_encrypted = encrypt_secret(
            str(provided["brevo_api_key"]), jwt_secret=settings.jwt_secret
        )
    if "mailgun_api_key" in provided and provided["mailgun_api_key"] is not None:
        mailgun_api_key_encrypted = encrypt_secret(
            str(provided["mailgun_api_key"]), jwt_secret=settings.jwt_secret
        )
    if "mailgun_domain" in provided:
        domain = provided["mailgun_domain"]
        values["mailgun_domain"] = str(domain).strip() if domain is not None else None
    if "mailgun_api_url" in provided:
        api_url = provided["mailgun_api_url"]
        values["mailgun_api_url"] = str(api_url).strip() if api_url is not None else None
    if "mailtrap_api_token" in provided and provided["mailtrap_api_token"] is not None:
        mailtrap_api_token_encrypted = encrypt_secret(
            str(provided["mailtrap_api_token"]), jwt_secret=settings.jwt_secret
        )

    sender_email = values["from_address"]
    if not sender_email:
        raise NotificationConfigError("A sender address is required to save notification settings")
    recipients = tuple(values["recipients"])
    if not recipients:
        raise NotificationConfigError("At least one notification recipient is required")

    provider = _provider_from_update(
        values,
        provided,
        settings,
        smtp_password_encrypted=smtp_password_encrypted,
        brevo_api_key_encrypted=brevo_api_key_encrypted,
        mailgun_api_key_encrypted=mailgun_api_key_encrypted,
        mailtrap_api_token_encrypted=mailtrap_api_token_encrypted,
    )

    config = NotificationConfig(
        enabled=values["enabled"],
        provider=provider,
        sender_email=sender_email,
        sender_name=values["from_name"],
        recipients=recipients,
        timeout_seconds=values["timeout_seconds"],
    )
    build_transport(config.provider, config.timeout_seconds)

    stored: dict[str, Any] = {
        **values,
        "id": SINGLETON_ID,
        "smtp_password_encrypted": smtp_password_encrypted,
        "brevo_api_key_encrypted": brevo_api_key_encrypted,
        "mailgun_api_key_encrypted": mailgun_api_key_encrypted,
        "mailtrap_api_token_encrypted": mailtrap_api_token_encrypted,
    }
    statement = pg_insert(NotificationSettings).values(**stored)
    statement = statement.on_conflict_do_update(
        index_elements=[NotificationSettings.id],
        set_={**stored, "updated_at": func.now()},
    )
    await session.execute(statement)
    await session.commit()
    return config
