"""An object-model value built from what a person wrote. A rule the wire
type does not repeat, such as a trigger's or a gate's, refuses the request
whole as `ValidationFailed`, naming where and why and never the value, so
a malformed body is a 422 and never a crash, and a secret in it is never
echoed."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from acme.om.exceptions import ValidationFailed


def built[M: BaseModel](model: type[M], data: Mapping[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in each['loc']) or 'body'}: {each['msg']}"
            for each in error.errors(include_input=False, include_url=False)
        )
        raise ValidationFailed(reasons) from None
