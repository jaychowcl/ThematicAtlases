import pytest

from ThematicAtlases.credentials import GoogleCredentialPreflight


def test_google_credential_preflight_resolves_project_and_refreshes_credentials() -> None:
    class Credentials:
        def __init__(self):
            self.refreshed = False

        def refresh(self, request):
            self.refreshed = True

    credentials = Credentials()
    checker = GoogleCredentialPreflight(
        project="configured-project",
        auth_default=lambda: (credentials, "adc-project"),
        request_factory=lambda: object(),
    )

    assert checker.check() == "configured-project"
    assert credentials.refreshed is True
    assert checker.check() == "configured-project"


def test_google_credential_preflight_requires_project() -> None:
    with pytest.raises(RuntimeError, match="Google Cloud project"):
        GoogleCredentialPreflight(
            auth_default=lambda: (object(), None),
            request_factory=lambda: object(),
        ).check()


def test_google_credential_preflight_wraps_adc_errors() -> None:
    def fail():
        raise ValueError("missing ADC")

    with pytest.raises(RuntimeError, match="Application Default Credentials"):
        GoogleCredentialPreflight(auth_default=fail).check()
