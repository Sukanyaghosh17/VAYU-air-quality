#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate
# --force-reseed: wipes and re-seeds demo readings with corrected IST diurnal baseline
# (fixes the flat AQI-48 bug from the UTC-hour seeding error)
python manage.py bootstrap_demo --force-reseed

