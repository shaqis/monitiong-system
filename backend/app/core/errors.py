from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

SENSITIVE_ERROR_KEYS = frozenset({"ctx", "input"})


def public_errors(error: ValidationError | RequestValidationError) -> list[dict[str, Any]]:
    """Validation errors without the submitted value or validator context.

    Pydantic copies the raw input into ``input``, so a rejected password would
    otherwise appear in the 422 body and in anything that records response
    bodies. ``ctx`` can hold the validator exception, which repeats the value.
    """
    return [
        {key: value for key, value in item.items() if key not in SENSITIVE_ERROR_KEYS}
        for item in error.errors()
    ]
