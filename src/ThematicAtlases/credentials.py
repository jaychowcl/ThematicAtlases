class GoogleCredentialPreflight:
    def __init__(
        self,
        project: str | None = None,
        auth_default=None,
        request_factory=None,
    ):
        self._project = project
        self._auth_default = auth_default
        self._request_factory = request_factory
        self._checked_project = None

    def check(self) -> str:
        if self._checked_project is not None:
            return self._checked_project

        try:
            credentials, adc_project = self._default_credentials()()
        except Exception as error:
            raise RuntimeError(
                "Google Application Default Credentials are unavailable. "
                "Run `gcloud auth application-default login` or configure a "
                "service-account credential."
            ) from error

        project = str(self._project or adc_project or "").strip()
        if not project:
            raise RuntimeError(
                "A Google Cloud project is required for LLM calls. Configure "
                "the provider project or an ADC quota project."
            )

        try:
            credentials.refresh(self._request()())
        except Exception as error:
            raise RuntimeError(
                "Google Application Default Credentials could not be refreshed."
            ) from error

        self._checked_project = project
        return project

    def _default_credentials(self):
        if self._auth_default is not None:
            return self._auth_default

        import google.auth

        return google.auth.default

    def _request(self):
        if self._request_factory is not None:
            return self._request_factory

        from google.auth.transport.requests import Request

        return Request
