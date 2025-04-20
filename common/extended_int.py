from __future__ import annotations

from functools import total_ordering
from typing import Any, Literal, SupportsInt


@total_ordering
class ExtendedInt:
    """Represents an integer that can also be positive or negative infinity.

    .. note::
       This class only implements the minimum behaviors needed in our application.
       It can be enhanced in the future to support more operations or use cases.
    """

    def __init__(self, value: int | Literal["inf", "-inf"]) -> None:
        self._value = value

    @classmethod
    def from_optional_int(
        self,
        value: int | None,
        none_as: Literal["inf", "-inf"],
    ) -> ExtendedInt:
        return ExtendedInt(value if value is not None else none_as)

    def __int__(self) -> int:
        if not isinstance(self._value, int):
            raise ValueError(f"Cannot convert {self._value} to simple integer.")

        return self._value

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, ExtendedInt):
            return NotImplemented

        if self._value == other._value:
            return False

        if isinstance(self._value, int) and isinstance(other._value, int):
            return self._value < other._value

        if self._value == "inf" or other._value == "-inf":
            return False

        return True

    def __eq__(self, other: object) -> bool:
        match other:
            case ExtendedInt():
                return self._value == other._value
            case SupportsInt():
                return self._value == int(other)
            case "inf" | "-inf":
                return self._value == other
            case _:
                return NotImplemented

    def __add__(self, value: int) -> ExtendedInt:
        match self._value:
            case int():
                return ExtendedInt(self._value + value)
            case _:
                return ExtendedInt(self._value)

    def __sub__(self, value: int) -> ExtendedInt:
        return self + (-value)

    def __repr__(self) -> str:
        return repr(self._value)

    def __str__(self) -> str:
        return str(self._value)

    def to_optional_int(self) -> int | None:
        return self._value if isinstance(self._value, int) else None
