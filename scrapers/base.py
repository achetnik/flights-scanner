from abc import ABC, abstractmethod
from typing import List
from models import JobConfig, FlightResult


class BaseScraper(ABC):
    airline_name: str  # subclasses MUST define this as a concrete class attribute

    def __init__(self):
        # Enforce that concrete subclasses define airline_name as an actual attribute
        # (not just an annotation). Annotations alone do not create attributes,
        # so hasattr returns False when only BaseScraper's annotation is present.
        if not type(self).__dict__.get("airline_name") and not any(
            "airline_name" in c.__dict__
            for c in type(self).__mro__
            if c is not BaseScraper and c is not object
        ):
            raise TypeError(
                f"{type(self).__name__} must define 'airline_name' as a class attribute"
            )

    @abstractmethod
    async def search(
        self,
        origin: str,
        destination: str,
        job: JobConfig,
    ) -> List[FlightResult]:
        """Search for flights. Return list of found flights (may be empty)."""
        ...
