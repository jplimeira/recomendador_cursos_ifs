@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python backend/manage.py migrate --run-syncdb
echo Crie um gestor com: python backend/manage.py createsuperuser
python backend/manage.py runserver
pause
