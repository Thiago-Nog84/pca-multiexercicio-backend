"""
Settings para execução de testes unitários.
Usa SQLite em memória para independência do PostgreSQL.

Uso:
    python manage.py test --settings=config.settings_test apps.srp.tests
"""

from .settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Desliga migrações para testes mais rápidos
class DisableMigrations:
    def __contains__(self, item):
        return True
    def __getitem__(self, item):
        return None

MIGRATION_MODULES = DisableMigrations()

# Silencia logs desnecessários nos testes
LOGGING = {}

# Senha mais simples para testes
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

ROOT_URLCONF = "config.urls_test"
