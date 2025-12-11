# lab/nacpp_client.py
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple, Union

import requests
from requests.adapters import HTTPAdapter, Retry
from defusedxml.ElementTree import fromstring
from xml.etree.ElementTree import Element  # для аннотаций
from django.conf import settings


class NacppError(Exception):
    """Базовая ошибка клиента NACPP."""


class NacppClient:
    """
    Клиент к шлюзу NACPP (kdldzagurov.ru / nacpp.info-совместимые инсталляции).

    Ключевые свойства поведения:
      - Авторизация через /login.php; успешной считаем по факту наличия cookies
        (даже если после редиректа сервер отдаёт 404 — такое на практике бывает).
      - Обязательный «пинг» каталога panelscategories для валидации сессии.
      - Каталоги/заявки/результаты возвращаем как XML Element (defusedxml.fromstring).
      - Прайс: умеем авто-обнаруживать эндпоинты (несколько названий каталога/act)
        и парсить как XML/JSON/простую HTML-таблицу.

    Настройки читаются из settings.py (или .env, если его подгружаешь):
      NACPP_BASE или NACPP_BASE_URL (база)
      NACPP_LOGIN, NACPP_PASSWORD
      NACPP_HTTP_TIMEOUT (сек), NACPP_RETRIES, NACPP_RETRY_BACKOFF
      *опционально* NACPP_LOGIN_PATH (/login.php), NACPP_LOGIN_FIELD (login),
      NACPP_PASSWORD_FIELD (password), NACPP_REQUIRE_CSRF (False)
    """

    # ------------ ctor / auth ------------

    def __init__(
        self,
        login: str | None = None,
        password: str | None = None,
        base: str | None = None,
        timeout: int = 25,
        retries: int = 3,
        backoff: float = 1.5,
        login_path: str | None = None,
        login_field: str | None = None,
        password_field: str | None = None,
        require_csrf: bool | None = None,
        debug: bool = False,
    ) -> None:
        self.base = (
            base
            or getattr(settings, "NACPP_BASE", None)
            or getattr(settings, "NACPP_BASE_URL", None)
            or "https://kdldzagurov.ru"
        ).rstrip("/")

        self.login_path = login_path or getattr(settings, "NACPP_LOGIN_PATH", "/login.php")
        self.login_field = login_field or getattr(settings, "NACPP_LOGIN_FIELD", "login")
        self.password_field = password_field or getattr(settings, "NACPP_PASSWORD_FIELD", "password")
        self.require_csrf = bool(require_csrf if require_csrf is not None else getattr(settings, "NACPP_REQUIRE_CSRF", False))

        self.login_ = login or getattr(settings, "NACPP_LOGIN", "")
        self.password_ = password or getattr(settings, "NACPP_PASSWORD", "")
        self.timeout = int(getattr(settings, "NACPP_HTTP_TIMEOUT", timeout))
        self.debug = debug

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "dzagurov-nacpp/compat/1.2"})

        r = Retry(
            total=int(getattr(settings, "NACPP_RETRIES", retries)),
            backoff_factor=float(getattr(settings, "NACPP_RETRY_BACKOFF", backoff)),
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
        )
        self.s.mount("https://", HTTPAdapter(max_retries=r))
        self.s.mount("http://", HTTPAdapter(max_retries=r))

        self.login()

    def login(self) -> None:
        if not self.login_ or not self.password_:
            raise NacppError("NACPP creds are empty (login/password).")

        url = f"{self.base}{self.login_path}"
        payload = {self.login_field: self.login_, self.password_field: self.password_}

        # Если форма с CSRF — подтянем hidden-поля
        if self.require_csrf:
            resp0 = self.s.get(url, timeout=self.timeout)
            resp0.raise_for_status()
            hidden = dict(
                re.findall(
                    r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
                    resp0.text,
                    re.I,
                )
            )
            payload.update(hidden)

        r = self.s.post(url, data=payload, timeout=self.timeout, allow_redirects=True)

        # Не падаем на 404/HTML — успех по факту наличия cookies
        if not self.s.cookies:
            try:
                r.raise_for_status()
            except requests.HTTPError as e:
                body = (r.text or "")[:500]
                raise NacppError(f"Login failed ({r.status_code}) at {url}. Body[:500]={body!r}") from e

        # Пинг каталога — подтверждаем, что сессия рабочая
        ping = self.s.get(
            f"{self.base}/plugins/index.php",
            params={"act": "get-catalog", "catalog": "panelscategories"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        if ping.status_code in (401, 403) or "login" in ping.url.lower():
            raise requests.HTTPError(f"Login ping failed: {ping.status_code} at {ping.url}")

    def logout(self) -> None:
        try:
            self.s.get(f"{self.base}/logout.php", timeout=self.timeout)
        except Exception:
            pass

    # ------------ helpers ------------

    @staticmethod
    def _looks_like_xml(text: str) -> bool:
        return (text or "").lstrip().startswith("<")

    @staticmethod
    def _looks_like_json(text: str) -> bool:
        t = (text or "").lstrip()
        return t.startswith("{") or t.startswith("[")

    def _get_xml(self, path: str, params: Dict[str, Any]) -> Element:
        r = self.s.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return fromstring(r.text)

    def _post_xml(self, path: str, params: Dict[str, Any], xml_body: str) -> Element:
        r = self.s.post(
            f"{self.base}{path}",
            params=params,
            data=xml_body,
            headers={"Content-Type": "application/xml"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return fromstring(r.text)

    # ------------ catalogs ------------

    def get_catalog(self, catalog: str, **params: Any) -> Element:
        q = {"act": "get-catalog", "catalog": catalog, **params}
        return self._get_xml("/plugins/index.php", q)

    def get_biomaterials(self, barcodeinfo: bool = False) -> Element:
        p = {"barcodeinfo": ""} if barcodeinfo else {}
        return self.get_catalog("bio", **p)

    def get_container_types(self) -> Element:
        return self.get_catalog("containertypes")

    # 🔹 панели: умеем запрашивать вместе с категориями (panel[@category])
    def get_panels(self, include_categories: bool = False) -> Element:
        if include_categories:
            return self.get_catalog("panels", categories="1")
        return self.get_catalog("panels")

    # 🔹 дерево категорий панелей
    def get_panel_categories(self) -> Element:
        return self.get_catalog("panelscategories")

    # алиас для обратной совместимости
    def get_categories(self) -> Element:
        return self.get_panel_categories()

    def get_tests_requirements(self) -> Element:
        return self.get_catalog("testsrequirements")

    def get_linked_panels(self) -> Element:
        return self.get_catalog("linkedpanels")

    # ------------ orders / results / reports ------------

    def get_pending(self) -> Element:
        return self._get_xml("/plugins/index.php", {"act": "pending"})

    def get_orders_by_period(self, date_start: str, date_end: str, extended: bool = True) -> Element:
        act = "request-ordersinfo" if extended else "request-orders"
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f"<request><date_start>{date_start}</date_start><date_end>{date_end}</date_end></request>"
        )
        return self._post_xml("/plugins/index.php", {"act": act}, body)

    def get_results_for_order(self, orderno: str) -> Element:
        return self._get_xml("/plugins/index.php", {"act": "get-result", "orderno": orderno})

    def get_report_pdf_bundle(
        self, orderno: str, panels_csv: str | None = None, with_logo: bool = True
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"action": "saveallreports", "id": orderno}
        if with_logo:
            params["logo"] = ""
        if panels_csv:
            params["panels"] = panels_csv
        r = self.s.get(f"{self.base}/print.php", params=params, timeout=self.timeout)
        r.raise_for_status()
        # разные инсталляции могут вернуть JSON или HTML с JSON внутри;
        # попробуем честно распарсить JSON, либо вытащим через регэксп.
        try:
            return r.json()
        except ValueError:
            m = re.search(r"\{.*\}", r.text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            raise NacppError("Unexpected format from print.php (not JSON).")

    # ------------ price discovery / parsing ------------

    def discover_price_endpoints(self) -> List[Tuple[Dict[str, Any], str]]:
        """
        Перебирает известные варианты маршрутов и параметров.
        Возвращает список (params, response_text) только для ненулевых ответов.
        """
        routes = [
            {"act": "get-catalog", "catalog": "price"},
            {"act": "get-catalog", "catalog": "services"},
            {"act": "get-catalog", "catalog": "panelsprice"},
            {"act": "get-catalog", "catalog": "pricecatalog"},
            {"act": "get-catalog", "catalog": "pricelist"},
            {"act": "price"},
            {"act": "services"},
        ]
        extras = [
            {"tariff": "1"},
            {"tariff": "default"},
            {"clinic": "1"},
            {"contract": "1"},
            {"org": "1"},
            {"pricegroup": "1"},
            {"group": "1"},
        ]
        found: List[Tuple[Dict[str, Any], str]] = []

        # без доп. параметров
        for p in routes:
            r = self.s.get(f"{self.base}/plugins/index.php", params=p, timeout=self.timeout, allow_redirects=True)
            if r.status_code == 200 and (r.text or "").strip():
                found.append((p, r.text))

        # с доп. параметрами
        for p in routes:
            for e in extras:
                q = {**p, **e}
                r = self.s.get(f"{self.base}/plugins/index.php", params=q, timeout=self.timeout, allow_redirects=True)
                if r.status_code == 200 and (r.text or "").strip():
                    found.append((q, r.text))
        return found

    def parse_price_payload(self, text: str) -> List[Dict[str, Any]]:
        """
        Универсальный парсер прайса:
          - JSON: dict/list, ключ prices опционален
          - XML: <prices><price>...</price></prices>
          - HTML: грубый разбор <table>/<tr><td>... + <li>...</li
        Возвращает список словарей [{code, name, cost, currency, duration, comment}]
        """
        t = (text or "").strip()
        if not t:
            return []

        # JSON?
        if t[:1] in "[{":
            try:
                data = json.loads(t)
                items = data.get("prices", data) if isinstance(data, dict) else data
                out: List[Dict[str, Any]] = []
                for it in items:
                    out.append(
                        {
                            "code": str(it.get("code") or "").strip(),
                            "name": (it.get("name") or "").strip(),
                            "cost": it.get("cost"),
                            "currency": (it.get("currency") or "RUB").strip()[:8],
                            "duration": (it.get("duration") or "").strip(),
                            "comment": (it.get("comment") or "").strip(),
                        }
                    )
                return out
            except Exception:
                pass

        # XML?
        if t.startswith("<"):
            try:
                root = fromstring(t)
                items: List[Dict[str, Any]] = []
                for p in root.findall(".//price"):
                    items.append(
                        {
                            "code": (p.findtext("code") or "").strip(),
                            "name": (p.findtext("name") or "").strip(),
                            "cost": (p.findtext("cost") or "").strip(),
                            "currency": (p.findtext("currency") or "RUB").strip()[:8],
                            "duration": (p.findtext("duration") or "").strip(),
                            "comment": (p.findtext("comment") or "").strip(),
                        }
                    )
                if items:
                    return items
            except Exception:
                pass

        # HTML (fallback): таблицы
        items: List[Dict[str, Any]] = []
        row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
        cell_re = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
        money_re = re.compile(r"([\d\s]+[.,]\d{2}|\d+)(?:\s*(?:р|руб|rub|₽))?", re.I)

        rows = row_re.findall(t)
        for row in rows:
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cell_re.findall(row)]
            if len(cells) < 2:
                continue
            code = cells[0].strip()
            name = cells[1].strip()
            price_txt = ""
            for c in cells[1:4]:
                m = money_re.search(c)
                if m:
                    price_txt = m.group(1)
                    break
            if code and name:
                items.append(
                    {
                        "code": code,
                        "name": name,
                        "cost": price_txt,
                        "currency": "RUB",
                        "duration": "",
                        "comment": "",
                    }
                )

        # HTML (fallback): списки
        if not items:
            li_re = re.compile(r"<li[^>]*>(.*?)</li>", re.I | re.S)
            for li in li_re.findall(t):
                plain = re.sub(r"<[^>]+>", " ", li)
                parts = [p.strip() for p in plain.split("—") if p.strip()]
                if len(parts) >= 2:
                    code = parts[0]
                    name = parts[1]
                    price_txt = ""
                    for p in parts[1:]:
                        m = money_re.search(p)
                        if m:
                            price_txt = m.group(1)
                            break
                    items.append(
                        {
                            "code": code,
                            "name": name,
                            "cost": price_txt,
                            "currency": "RUB",
                            "duration": "",
                            "comment": "",
                        }
                    )

        return items

    # Упрощённый «получить прайс любой ценой» (вернёт либо Element, либо dict/list, либо кинет ошибку)
    def get_prices_any(self) -> Union[Element, Dict[str, Any], List[Any]]:
        candidates = [
            {"act": "get-catalog", "catalog": "price"},
            {"act": "get-catalog", "catalog": "services"},
            {"act": "get-catalog", "catalog": "panelsprice"},
            {"act": "get-catalog", "catalog": "pricecatalog"},
            {"act": "get-catalog", "catalog": "pricelist"},
            {"act": "price"},
            {"act": "services"},
        ]
        last_diag = ""
        for params in candidates:
            r = self.s.get(f"{self.base}/plugins/index.php", params=params, timeout=self.timeout, allow_redirects=True)
            ct = (r.headers.get("content-type") or "").lower()
            body = r.text or ""
            if r.status_code != 200 or not body.strip():
                last_diag = f"{params} -> status={r.status_code} len={len(body)} ct={ct}"
                continue
            if "json" in ct or self._looks_like_json(body):
                try:
                    return json.loads(body)
                except Exception:
                    last_diag = f"{params} -> JSON parse failed; head={body[:120]!r}"
                    continue
            if self._looks_like_xml(body):
                try:
                    return fromstring(body)
                except Exception:
                    last_diag = f"{params} -> XML parse failed; head={body[:120]!r}"
                    continue
            last_diag = f"{params} -> unknown format ct={ct}; head={body[:120]!r}"

        raise NacppError(f"Price catalog not found via known routes. Last: {last_diag}")
