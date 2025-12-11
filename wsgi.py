import os
import sys

try:
  sys.path.remove('/usr/lib/python3/dist-packages')
except:
  pass

sys.path.append('/home/j/joker2038/dzagurov/public_html/dzagurov/')
sys.path.append('/home/j/joker2038/dzagurov/public_html/venv/lib/python3.10/site-packages/')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dzagurov.settings')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
