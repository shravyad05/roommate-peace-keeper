"""Unit test for Telegram bot configuration and initial setup."""

import pytest
from app.bot import create_bot_application


def test_create_bot_application_missing_token():
    """Verify ValueError is raised if token is absent."""
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        create_bot_application(token="")


def test_create_bot_application_valid_shape():
    """Verify Application builds cleanly with token shape."""
    dummy_token = "123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ123456789"
    app = create_bot_application(token=dummy_token)
    assert app is not None
    assert app.bot.token == dummy_token
