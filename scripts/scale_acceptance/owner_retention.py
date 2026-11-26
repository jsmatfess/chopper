"""Keep the original owner alive when cleanup cannot be proved."""
import time
from typing import Callable, NoReturn


def retain_owner(report: Callable[[], object]) -> NoReturn:
    try:
        report()
    except BaseException:
        pass
    # Returning or unwinding would release the original reservation.
    while True:
        try:
            time.sleep(1)
        except BaseException:
            pass
