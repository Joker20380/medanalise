from django.conf import settings

WEBP_STATIC_ROOT = getattr(settings, "WEBP_STATIC_ROOT", settings.STATIC_ROOT)
WEBP_MEDIA_ROOT  = getattr(settings, "WEBP_MEDIA_ROOT", settings.MEDIA_ROOT)
WEBP_QUALITY     = getattr(settings, "WEBP_QUALITY", 75)
