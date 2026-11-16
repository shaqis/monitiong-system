import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.deps import require_admin
from app.db.models import User
from app.notifications.transports import EmailTransportError

logger = logging.getLogger(__name__)

router = APIRouter()


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
