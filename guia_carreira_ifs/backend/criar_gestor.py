"""Cria ou atualiza o gestor local de demonstração após executar migrate."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from django.contrib.auth import get_user_model

User = get_user_model()
user, created = User.objects.get_or_create(username='gestorifs', defaults={'is_staff': True, 'is_superuser': True})
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password('ifs123@')
user.save()
print('Conta gestorifs configurada com acesso de gestor.' )
