"""The platform's API settings are a section of their own: `ApiSettings`
takes them in and declares none of them itself, and a live-read key shorter
than 32 characters refuses the process's start."""

import inspect

import pytest
from pydantic import ValidationError

from acme.services.api.platform.settings import PlatformApiSettings
from acme.services.api.settings import ApiSettings


def test_the_api_settings_declare_none_of_the_section() -> None:
    section = set(PlatformApiSettings.model_fields)
    assert section <= set(ApiSettings.model_fields)
    assert not section & set(inspect.get_annotations(ApiSettings))


def test_a_short_live_read_key_refuses_the_start() -> None:
    with pytest.raises(ValidationError, match="shorter than 32 characters"):
        ApiSettings.model_validate({"_env_file": None, "live_read_key": "k" * 31})


def test_a_long_enough_live_read_key_is_kept() -> None:
    settings = ApiSettings.model_validate({"_env_file": None, "live_read_key": "k" * 32})
    assert settings.live_read_key is not None
    assert settings.live_read_key.get_secret_value() == "k" * 32
