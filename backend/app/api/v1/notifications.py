import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.config import Settings, get_settings
from app.core.deps import require_admin
from app.db.models import User
from app.notifications.transports import EmailTransportError
from app.schemas.notification import NotificationSettingsResponse

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    request: Request,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> NotificationSettingsResponse:
    return NotificationSettingsResponse(
        enabled=settings.email_notifications_enabled,
        provider=settings.email_provider,
        configured=getattr(request.app.state, "notifier", None) is not None,
        from_address=(
            str(settings.email_from_address) if settings.email_from_address is not None else None
        ),
        from_name=settings.email_from_name.strip() or "Uptime Monitor",
        recipients=[str(recipient) for recipient in settings.notification_recipients],
        timeout_seconds=settings.notification_timeout_seconds,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_starttls=settings.smtp_starttls,
        smtp_ssl=settings.smtp_ssl,
        smtp_username_set=settings.smtp_username is not None,
        mailgun_domain=settings.mailgun_domain,
        provider_credentials_set=_provider_credentials_set(settings),
    )


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
    except EmailTransportError as exc:
        logger.warning("Test email failed", extra={"provider": exc.provider})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The email provider rejected the test message",
        ) from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)
