"""Errors raised by the market-data seam."""


class MarketDataError(Exception):
    """Base class for expected market-data failures."""


class SectorsAuthError(MarketDataError):
    """The Sectors API rejected authentication or no key was configured."""


class SectorsSchemaError(MarketDataError):
    """A Sectors response did not match the expected schema."""


class SectorsRequestError(MarketDataError):
    """A Sectors request failed for a non-authentication reason."""
