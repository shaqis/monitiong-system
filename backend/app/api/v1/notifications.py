import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import require_admin
from app.db.models import User
from app.db.session import get_db
from app.notifications.settings_store import (
    NotificationSettingsSnapshot,
    load_notification_settings_snapshot,
    save_notification_config,
)
from app.notifications.transports import EmailTransportError, NotificationConfigError
from app.schemas.notification import (
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_response(snapshot: NotificationSettingsSnapshot) -> NotificationSettingsResponse:
    return NotificationSettingsResponse(
        enabled=snapshot.enabled,
        provider=snapshot.provider,
        configured=snapshot.configured,
        source=snapshot.source,
        from_address=snapshot.from_address,
        from_name=snapshot.from_name,
        recipients=list(snapshot.recipients),
        timeout_seconds=snapshot.timeout_seconds,
        smtp_host=snapshot.smtp_host,
        smtp_port=snapshot.smtp_port,
        smtp_starttls=snapshot.smtp_starttls,
        smtp_ssl=snapshot.smtp_ssl,
        smtp_username=snapshot.smtp_username,
        smtp_password_set=snapshot.smtp_password_state == "set",
        brevo_api_key_set=snapshot.brevo_api_key_state == "set",
        mailgun_domain=snapshot.mailgun_domain,
        mailgun_api_url=snapshot.mailgun_api_url,
        mailgun_api_key_set=snapshot.mailgun_api_key_state == "set",
        mailtrap_api_token_set=snapshot.mailtrap_api_token_state == "set",
        provider_credentials_set=snapshot.provider_credentials_set,
        unreadable_secrets=list(snapshot.unreadable_secrets),
    )


def _unprocessable_config_error(exc: NotificationConfigError) -> HTTPException:
    detail: str | list[dict[str, object]] = (
        [{"loc": ["body", exc.field], "msg": str(exc), "type": "value_error"}]
        if exc.field is not None
        else str(exc)
    )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
    )


@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsResponse:
    snapshot = await load_notification_settings_snapshot(db, settings)
    return _to_response(snapshot)


@router.patch("/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsResponse:
    try:
        await save_notification_config(db, settings, payload)
    except NotificationConfigError as exc:
        raise _unprocessable_config_error(exc) from None
    snapshot = await load_notification_settings_snapshot(db, settings)
    return _to_response(snapshot)


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
