from __future__ import annotations

import pytest
from pydantic import ValidationError

from kim_sectors.config import SectorsConfig


def test_empty_api_key_is_rejected():
    with pytest.raises(ValidationError):
        SectorsConfig(sectors_api_key="")


def test_config_string_redacts_api_key():
    config = SectorsConfig(sectors_api_key="test-dummy-key-123")
    assert "test-dummy-key-123" not in str(config)
    assert "test-dummy-key-123" not in repr(config)
