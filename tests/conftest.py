import pytest


@pytest.fixture(autouse=True)
def _no_dev_mail_backend(monkeypatch):
    # A developer's .env may turn real account email on (PAW_MAIL_BACKEND=smtp),
    # which makes every login wait on an emailed code. Tests that want email
    # set it themselves.
    monkeypatch.delenv("PAW_MAIL_BACKEND", raising=False)
