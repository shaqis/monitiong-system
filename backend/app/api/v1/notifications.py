import logging
from typing import get_args

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import require_admin
from app.db.models import NotificationSettings, User
from app.db.session import get_db
from app.notifications.config import NotificationConfig, config_from_env
from app.notifications.settings_store import (
    build_notification_config,
    get_notification_settings_row,
    save_notification_config,
)
from app.notifications.transports import (
    EmailTransportError,
    NotificationConfigError,
    build_transport,
)
from app.schemas.notification import (
    NotificationProviderValue,
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

NOTIFICATION_PROVIDERS: frozenset[str] = frozenset(get_args(NotificationProviderValue))


def _provider_credentials_set(settings: Settings) -> bool:
    if settings.email_provider == "smtp":
        return (
            settings.smtp_host is not None
            and (settings.smtp_username is None) == (settings.smtp_password is None)
            and not (settings.smtp_starttls and settings.smtp_ssl)
        )
    if settings.email_provider == "brevo":
        return settings.brevo_api_key is not None
    if settings.email_provider == "mailgun":
        return settings.mailgun_api_key is not None and settings.mailgun_domain is not None
    return settings.mailtrap_api_token is not None


def _is_configured(config: NotificationConfig | None) -> bool:
    if config is None:
        return False
    try:
        build_transport(config.provider, config.timeout_seconds)
    except NotificationConfigError:
        return False
    return True


def _settings_response(
    config: NotificationConfig | None,
    settings: Settings,
    row: NotificationSettings | None,
) -> NotificationSettingsResponse:
    configured = _is_configured(config)

    if row is not None:
        provider: NotificationProviderValue = (
            row.provider if row.provider in NOTIFICATION_PROVIDERS else "smtp"
        )
        smtp_host = row.smtp_host
        smtp_port = row.smtp_port
        smtp_starttls = row.smtp_starttls
        smtp_ssl = row.smtp_ssl
        smtp_username = row.smtp_username
        smtp_password_set = row.smtp_password_encrypted is not None
        brevo_api_key_set = row.brevo_api_key_encrypted is not None
        mailgun_domain = row.mailgun_domain
        mailgun_api_url = row.mailgun_api_url
        mailgun_api_key_set = row.mailgun_api_key_encrypted is not None
        mailtrap_api_token_set = row.mailtrap_api_token_encrypted is not None
        provider_credentials_set = configured
    else:
        provider = settings.email_provider
        smtp_host = settings.smtp_host
        smtp_port = settings.smtp_port
        smtp_starttls = settings.smtp_starttls
        smtp_ssl = settings.smtp_ssl
        smtp_username = settings.smtp_username
        smtp_password_set = settings.smtp_password is not None
        brevo_api_key_set = settings.brevo_api_key is not None
        mailgun_domain = settings.mailgun_domain
        mailgun_api_url = settings.mailgun_api_url
        mailgun_api_key_set = settings.mailgun_api_key is not None
        mailtrap_api_token_set = settings.mailtrap_api_token is not None
        provider_credentials_set = _provider_credentials_set(settings)

    if config is not None:
        enabled = config.enabled
        from_address: str | None = config.sender_email
        from_name = config.sender_name
        recipients = list(config.recipients)
        timeout_seconds = config.timeout_seconds
    else:
        enabled = settings.email_notifications_enabled
        from_address = (
            str(settings.email_from_address) if settings.email_from_address is not None else None
        )
        from_name = settings.email_from_name.strip() or "Uptime Monitor"
        recipients = [str(recipient) for recipient in settings.notification_recipients]
        timeout_seconds = settings.notification_timeout_seconds

    return NotificationSettingsResponse(
        enabled=enabled,
        provider=provider,
        configured=configured,
        source="database" if row is not None else "environment",
        from_address=from_address,
        from_name=from_name,
        recipients=recipients,
        timeout_seconds=timeout_seconds,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_starttls=smtp_starttls,
        smtp_ssl=smtp_ssl,
        smtp_username=smtp_username,
        smtp_password_set=smtp_password_set,
        brevo_api_key_set=brevo_api_key_set,
        mailgun_domain=mailgun_domain,
        mailgun_api_url=mailgun_api_url,
        mailgun_api_key_set=mailgun_api_key_set,
        mailtrap_api_token_set=mailtrap_api_token_set,
        provider_credentials_set=provider_credentials_set,
    )


@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsResponse:
    row = await get_notification_settings_row(db)
    try:
        config = (
            build_notification_config(row, settings)
            if row is not None
            else config_from_env(settings)
        )
    except NotificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    return _settings_response(config, settings, row)


@router.patch("/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsResponse:
    try:
        config = await save_notification_config(db, settings, payload)
    except NotificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None
    row = await get_notification_settings_row(db)
    return _settings_response(config, settings, row)


@router.post("/test", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_notification(
    request: Request,
    _: User = Depends(require_admin),
) -> Response:
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications are not configured",
        )

    try:
        await notifier.send_test()
    except NotificationConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications are not configured",
        ) from None
    except EmailTransportError as exc:
        logger.warning("Test email failed", extra={"provider": exc.provider})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The email provider rejected the test message",
        ) from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)
