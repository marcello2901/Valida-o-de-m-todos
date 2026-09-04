"""Configuração do projeto.

Valores sensíveis vêm de variáveis de ambiente. Em desenvolvimento há padrões
que funcionam sem configurar nada; em produção (DEBUG desligado), a aplicação se
recusa a subir se a chave secreta ainda for a de desenvolvimento — assim um
esquecimento de configuração vira erro na hora do deploy, e não uma brecha
silenciosa em produção.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Segurança -------------------------------------------------------------

CHAVE_DESENVOLVIMENTO = "insegura-apenas-para-desenvolvimento-local"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", CHAVE_DESENVOLVIMENTO)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origem.strip()
    for origem in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origem.strip()
]

# O Render publica o endereço do site nesta variável. Ler daqui evita o erro
# mais comum de primeira implantação: subir tudo certo e receber
# "DisallowedHost" porque ninguém sabia qual endereço digitar na configuração.
ENDERECO_DO_RENDER = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if ENDERECO_DO_RENDER:
    ALLOWED_HOSTS.append(ENDERECO_DO_RENDER)
    CSRF_TRUSTED_ORIGINS.append(f"https://{ENDERECO_DO_RENDER}")

if not DEBUG:
    if SECRET_KEY == CHAVE_DESENVOLVIMENTO:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY não foi definida. Em produção a chave precisa ser "
            "secreta e exclusiva — a chave de desenvolvimento é pública neste "
            "repositório e permitiria forjar sessões de qualquer usuário."
        )

    # Em produção a sessão e o CSRF só trafegam por HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Aplicações ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "contas",
    "catalogo",
    "estudos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Banco de dados --------------------------------------------------------
#
# Sem DATABASE_URL configurada, usa um arquivo SQLite local — assim o sistema
# roda na máquina de quem estiver desenvolvendo sem instalar banco nenhum.
# Em produção, DATABASE_URL aponta para o PostgreSQL.

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'banco-local.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# --- Autenticação ----------------------------------------------------------

AUTH_USER_MODEL = "contas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# A entrada do programa é a tela do programa, não a do painel administrativo.
# O login do painel exige conta de equipe (is_staff): apontar LOGIN_URL para ele
# deixava qualquer analista de laboratório de fora — ele batia no formulário e
# recebia "insira um usuário e senha para uma conta de equipe".
LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "/quadro/"
LOGOUT_REDIRECT_URL = "entrar"

# Sessão expira em 12 horas — um turno de trabalho.
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# --- Localização -----------------------------------------------------------

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --- Arquivos estáticos ----------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# A folha que veste o painel administrativo com a identidade do programa.
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Troca o armazenamento de estáticos durante os testes. O porquê está no módulo.
TEST_RUNNER = "config.testes.Executor"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
