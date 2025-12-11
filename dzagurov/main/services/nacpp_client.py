import requests
from django.conf import settings


class NacppClient:
    def __init__(self, login: str, password: str, base: str | None = None, timeout: int = 25):
        self.base = base or getattr(settings, "NACPP_BASE", "https://kdldzagurov.ru")
        self.s = requests.Session()
        self.login_ = login
        self.password_ = password
        self.timeout = timeout

    def login(self):
        url = f"{self.base}/login.php"
        r = self.s.post(
            url,
            data={"login": self.login_, "password": self.password_},
            timeout=self.timeout,
            allow_redirects=True,
        )

        # Не падаем на 404 после редиректа — это норма для их инсталляций
        # Считаем логин успешным, если получили cookie (сессия поднята)
        if not self.s.cookies:
            r.raise_for_status()

        # Проверочный пинг — чтобы убедиться, что сессия рабочая
        ping = self.s.get(
            f"{self.base}/plugins/index.php",
            params={"act": "get-catalog", "catalog": "panelscategories"},
            timeout=self.timeout,
        )

        # Если 401/403 или редирект на логин — авторизация не удалась
        if ping.status_code in (401, 403) or "login" in ping.url.lower():
            raise requests.HTTPError(f"Login ping failed: {ping.status_code} at {ping.url}")

    def logout(self):
        try:
            self.s.get(f"{self.base}/logout.php", timeout=self.timeout)
        except Exception:
            pass

    def get_catalog(self, catalog: str, **params):
        q = {"act": "get-catalog", "catalog": catalog, **params}
        r = self.s.get(f"{self.base}/plugins/index.php", params=q, timeout=self.timeout)
        r.raise_for_status()
        return r.text  # XML
