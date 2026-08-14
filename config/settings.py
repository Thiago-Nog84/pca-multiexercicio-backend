"""
Django settings — PCA Multiexercício (MPPI)
Sistema de Gestão do Plano de Contratações Anuais — multiexercício
Órgão: Ministério Público do Estado do Piauí — CLC / Assessoria de Compras
"""

from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="django-insecure-change-me")
DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # lookups __unaccent (busca insensível a acento)
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    # Django extras
    "django.contrib.humanize",
    # Apps MPPI
    "apps.core",
    "apps.pca",
    "apps.planejamento",
    "apps.cotacao",
    "apps.licitacao",
    "apps.srp",
    "apps.contratos",
    "apps.juridico",
    "apps.pncp",
    "apps.notificacoes",
    "apps.siafe",
    "apps.tcepi",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.notificacoes",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="postgres"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT", default="6543"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

# Autenticação via templates Django
# Usa o login do admin enquanto não existe página de login própria
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/pca/"
LOGOUT_REDIRECT_URL = "/admin/login/"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Uploads manuais (ex: PDF de instrumento contratual quando não há link automático).
# Servidos via view autenticada (contratos:instrumento_pdf), não expostos publicamente.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# Em desenvolvimento libera todas as origens; em produção usa a lista do .env
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = config(
        "CORS_ALLOWED_ORIGINS",
        default="http://localhost:8081,http://localhost:5173",
        cast=Csv(),
    )

LIMITE_DISPENSA_BENS_SERVICOS = config(
    "LIMITE_DISPENSA_BENS_SERVICOS", default=50_000, cast=int
)
LIMITE_DISPENSA_OBRAS = config("LIMITE_DISPENSA_OBRAS", default=100_000, cast=int)

# ------------------------------------------------------------------
# Comprasnet Contratos API (contratos.comprasnet.gov.br)
# Credenciais do usuário SISG/Comprasnet com acesso à UG 926092.
# Necessárias apenas para endpoints v1 autenticados (empenhos, etc.).
# Deixe em branco para usar somente os endpoints públicos.
# ------------------------------------------------------------------
COMPRASNET_CONTRATOS_CPF = config("COMPRASNET_CONTRATOS_CPF", default="")
COMPRASNET_CONTRATOS_SENHA = config("COMPRASNET_CONTRATOS_SENHA", default="")

# ------------------------------------------------------------------
# SIAFE-PI — Sistema Integrado de Administração Financeira do Piauí
# API: https://tesouro.sefaz.pi.gov.br/siafe-api/swagger-ui.html
# ------------------------------------------------------------------
SIAFE_BASE_URL = config("SIAFE_BASE_URL", default="https://tesouro.sefaz.pi.gov.br/siafe-api")
SIAFE_USUARIO = config("SIAFE_USUARIO", default="")
SIAFE_SENHA = config("SIAFE_SENHA", default="")
# TTL do token em cache (segundos). Token SIAFE expira em ~60 min; usamos 50 min por segurança.
SIAFE_TOKEN_TTL_SECONDS = config("SIAFE_TOKEN_TTL_SECONDS", default=3000, cast=int)

# ------------------------------------------------------------------
# TCE-PI — Portal da Cidadania (Tribunal de Contas do Estado do Piauí)
# API pública, sem autenticação. Docs: https://sistemas.tce.pi.gov.br/api/portaldacidadania/docs/
# ------------------------------------------------------------------
TCEPI_BASE_URL = config("TCEPI_BASE_URL", default="https://sistemas.tce.pi.gov.br/api/portaldacidadania")
