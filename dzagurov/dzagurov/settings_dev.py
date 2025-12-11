# dzagurov/settings_dev.py

from .settings import *  # подтягиваем все боевые настройки

DEBUG = True

# SQLite для локальной разработки
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.dev.sqlite3",
    }
}

# Чтобы письма не уходили в реальный SMTP
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
