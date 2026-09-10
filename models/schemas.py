from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    success: bool
    source: str
    data: dict[str, Any] | list[Any]
    error_code: str | None = None
    error_message: str | None = None
    is_mock: bool = False