"""역할 1 API Tool에서 사용하는 공급자 입력 타입."""

from typing import Literal

SchoolAge = Literal["preschool", "elementary", "middle", "high", "univ", "all"]
VisitorTargetAge = Literal[
    "10세 미만",
    "10대",
    "20대",
    "30대",
    "40대",
    "50대",
    "60대",
    "70대",
    "80대",
    "90대",
    "100세 이상",
]

__all__ = ["SchoolAge", "VisitorTargetAge"]
