from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import NotificationSettings
from app.notifications.config import (
    BrevoConfig,
    NotificationConfig,
    ProviderConfig,
    SmtpConfig,
    config_from_env,
)
from app.notifications.secrets import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.notifications.transports import NotificationConfigError, build_transport
from app.schemas.notification import NotificationSettingsUpdate

SINGLETON_ID = 1
DEFAULT_FROM_NAME = "Uptime Monitor"
DEFAULT_SMTP_PORT = 587
DEFAULT_TIMEOUT_SECONDS = 10.0
DECRYPTION_FAILURE = (
    "The saved notification secrets cannot be decrypted with the current JWT_SECRET. "
    "Enter the secret again and save."
)


def _decrypt(token: str, settings: Settings) -> str:
    try:
        return decrypt_secret(token, jwt_secret=settings.jwt_secret)
    except SecretDecryptionError:
        raise NotificationConfigError(DECRYPTION_FAILURE) from None


def _provider_from_row(row: NotificationSettings, settings: Settings) -> ProviderConfig:
    if row.provider == "smtp":
        password = (
            _decrypt(row.smtp_password_encrypted, settings)
            if row.smtp_password_encrypted is not None
            else None
        )
        return SmtpConfig(
            host=row.smtp_host,
            port=row.smtp_port,
            username=row.smtp_username,
            password=password,
            start_tls=row.smtp_starttls,
            use_tls=row.smtp_ssl,
        )
    if row.provider == "brevo":
        api_key = (
            _decrypt(row.brevo_api_key_encrypted, settings)
            if row.brevo_api_key_encrypted is not None
            else None
        )
        return BrevoConfig(api_key=api_key)
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


def _env_seed(settings: Settings) -> dict[str, Any]:
    """Starting values for the first save, derived from the environment."""
    config = config_from_env(settings)
    provider = config.provider if config is not None else None
    smtp = provider if isinstance(provider, SmtpConfig) else None
    return {
        "enabled": config.enabled if config is not None else False,
        "provider": (
            config.provider_name
            if config is not None and isinstance(provider, (SmtpConfig, BrevoConfig))
            else "smtp"
        ),
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
    }


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
    username_provided = "smtp_username" in provided
    if username_provided:
        username = provided["smtp_username"]
        values["smtp_username"] = str(username).strip() if username is not None else None
    if "smtp_password" in provided and provided["smtp_password"] is not None:
        smtp_password_encrypted = encrypt_secret(
            str(provided["smtp_password"]), jwt_secret=settings.jwt_secret
        )
    if username_provided and values["smtp_username"] is None:
        smtp_password_encrypted = None
    if "brevo_api_key" in provided and provided["brevo_api_key"] is not None:
        brevo_api_key_encrypted = encrypt_secret(
            str(provided["brevo_api_key"]), jwt_secret=settings.jwt_secret
        )

    sender_email = values["from_address"]
    if not sender_email:
        raise NotificationConfigError("A sender address is required to save notification settings")
    recipients = tuple(values["recipients"])
    if not recipients:
        raise NotificationConfigError("At least one notification recipient is required")

    if values["provider"] == "smtp":
        password = None
        if smtp_password_encrypted is not None:
            password = (
                str(provided["smtp_password"])
                if provided.get("smtp_password") is not None
                else _decrypt(smtp_password_encrypted, settings)
            )
        provider: ProviderConfig = SmtpConfig(
            host=values["smtp_host"],
            port=values["smtp_port"],
            username=values["smtp_username"],
            password=password,
            start_tls=values["smtp_starttls"],
            use_tls=values["smtp_ssl"],
        )
    else:
        api_key = (
            str(provided["brevo_api_key"])
            if provided.get("brevo_api_key") is not None
            else (
                _decrypt(brevo_api_key_encrypted, settings)
                if brevo_api_key_encrypted is not None
                else None
            )
        )
        provider = BrevoConfig(api_key=api_key)

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
    }
    statement = pg_insert(NotificationSettings).values(**stored)
    statement = statement.on_conflict_do_update(
        index_elements=[NotificationSettings.id],
        set_={**stored, "updated_at": func.now()},
    )
    await session.execute(statement)
    await session.commit()
    return config
