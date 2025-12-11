# dzagurov/utils/__init__.py
from django.conf import settings

# Попробуем взять дефолты из самого django_webp, чтобы не гадать о полном списке
try:
    from django_webp import utils as _dw  # дефолты пакета, если есть
except Exception:
    class _Dummy:  # на всякий случай, чтоб getattr не падал
        pass
    _dw = _Dummy()

def _fallback(name, default):
    """
    1) settings.NAME
    2) django_webp.utils.NAME (если есть)
    3) default
    """
    return getattr(settings, name, getattr(_dw, name, default))

# Базовые пути/качество
WEBP_STATIC_ROOT = _fallback("WEBP_STATIC_ROOT", getattr(settings, "STATIC_ROOT", None))
WEBP_MEDIA_ROOT  = _fallback("WEBP_MEDIA_ROOT",  getattr(settings, "MEDIA_ROOT",  None))
WEBP_QUALITY     = _fallback("WEBP_QUALITY",     80)

# Отладка
WEBP_DEBUG       = _fallback("WEBP_DEBUG", getattr(settings, "DEBUG", False))

# Проверка внешних URL-ов (в некоторых версиях пакета присутствует)
WEBP_CHECK_URLS  = _fallback("WEBP_CHECK_URLS", False)

# Используем ли WhiteNoise (некоторые ревизии пакета это спрашивают)
def _using_whitenoise():
    try:
        mws = [m.lower() for m in getattr(settings, "MIDDLEWARE", [])]
        # стандартный middleware
        if any("whitenoise.middleware.whitenoisemiddleware" in m for m in mws):
            return True
        # иногда проверяют app/nostatic
        apps = [a.lower() for a in getattr(settings, "INSTALLED_APPS", [])]
        if any("whitenoise" in a for a in apps):
            return True
    except Exception:
        pass
    # если вдруг у django_webp.utils уже есть это поле — используем его
    return getattr(_dw, "USING_WHITENOISE", False)

USING_WHITENOISE = _fallback("USING_WHITENOISE", _using_whitenoise())

# (опционально) на всякий случай экспорт URL-параметров, если где-то спросят
WEBP_STATIC_URL = _fallback("WEBP_STATIC_URL", getattr(settings, "STATIC_URL", "/static/"))
WEBP_MEDIA_URL  = _fallback("WEBP_MEDIA_URL",  getattr(settings, "MEDIA_URL",  "/media/"))

__all__ = [
    "WEBP_STATIC_ROOT",
    "WEBP_MEDIA_ROOT",
    "WEBP_QUALITY",
    "WEBP_DEBUG",
    "WEBP_CHECK_URLS",
    "USING_WHITENOISE",
    "WEBP_STATIC_URL",
    "WEBP_MEDIA_URL",
]
