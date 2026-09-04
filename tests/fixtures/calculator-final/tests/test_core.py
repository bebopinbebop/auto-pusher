import pytest

from calculator.core import add, divide, multiply, subtract


def test_operations() -> None:
    assert add(2, 3) == 5
    assert subtract(5, 3) == 2
    assert multiply(4, 3) == 12
    assert divide(8, 2) == 4


def test_zero_division() -> None:
    with pytest.raises(ValueError):
        divide(1, 0)

