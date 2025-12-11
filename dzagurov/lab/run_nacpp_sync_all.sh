#!/bin/bash
cd /dzagurov/public_html
source /venv/bin/activate

python3 manage.py nacpp_sync_all \
  --create-missing-services \
  --panel-prices=/dzagurov/public_html/dzagurov/data/0148.csv \
  >> /dzagurov/nacpp_sync_all.log 2>&1
