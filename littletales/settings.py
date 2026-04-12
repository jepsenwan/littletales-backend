"""
Django settings for littletales project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-change-me-in-production')

DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = [h.strip() for h in os.getenv(
    'ALLOWED_HOSTS',
    'localhost,127.0.0.1,0.0.0.0'
).split(',') if h.strip()]

CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv(
    'CSRF_TRUSTED_ORIGINS', ''
).split(',') if o.strip()]

# Behind Railway's proxy: respect X-Forwarded-Proto so Django knows requests are HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'storages',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

LOCAL_APPS = [
    'apps.stories',
    'apps.users',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'littletales.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'littletales.wsgi.application'

import dj_database_url
DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Override AWS_PROFILE to prevent boto3 from using system SSO profile
os.environ.pop('AWS_PROFILE', None)
os.environ.pop('AWS_DEFAULT_PROFILE', None)

# Cloudflare R2 Storage
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID', '4d33d3e4994fb3e42eea951d5bff3c8c')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'curiosee')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', 'https://pub-b24ac0e5c2074ef0896d30c5872b466b.r2.dev')
R2_LOCATION = 'twinkle-twinkle'  # prefix inside the bucket

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "access_key": R2_ACCESS_KEY_ID,
            "secret_key": R2_SECRET_ACCESS_KEY,
            "bucket_name": R2_BUCKET_NAME,
            "endpoint_url": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            "region_name": "auto",
            "location": R2_LOCATION,
            "custom_domain": R2_PUBLIC_URL.replace('https://', ''),
            "default_acl": None,
            "querystring_auth": False,
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20
}

CORS_ALLOW_ALL_ORIGINS = True

# Yunwu AI Configuration (primary image generation)
YUNWU_API_KEY = os.getenv('YUNWU_API_KEY', '')
# Ordered fallback keys (comma-separated). Tried in order; first non-empty key wins.
# Falls back to YUNWU_API_KEY if YUNWU_API_KEYS is unset.
YUNWU_API_KEYS = [k.strip() for k in os.getenv('YUNWU_API_KEYS', '').split(',') if k.strip()]
if not YUNWU_API_KEYS and YUNWU_API_KEY:
    YUNWU_API_KEYS = [YUNWU_API_KEY]
YUNWU_BASE_URL = os.getenv('YUNWU_BASE_URL', 'https://yunwu.ai/v1')
YUNWU_IMAGE_MODEL = os.getenv('YUNWU_IMAGE_MODEL', 'gemini-3.1-flash-image-preview')

# APIMart AI Configuration (fallback image generation)
APIMART_API_KEY = os.getenv('APIMART_API_KEY', '')
APIMART_BASE_URL = os.getenv('APIMART_BASE_URL', 'https://api.apimart.ai/v1')
AI_TEXT_MODEL = os.getenv('AI_TEXT_MODEL', 'gpt-4o-mini')
AI_IMAGE_MODEL = os.getenv('AI_IMAGE_MODEL', 'doubao-seedance-4-5')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

# Volcengine TTS Configuration
VOLCENGINE_TTS_APPID = os.getenv('VOLCENGINE_TTS_APPID', '2300143737')
VOLCENGINE_TTS_TOKEN = os.getenv('VOLCENGINE_TTS_TOKEN', 'bWGwaHi3bItvoDPfVH50RiWZsde6M4Qj')
VOLCENGINE_TTS_CLUSTER = os.getenv('VOLCENGINE_TTS_CLUSTER', 'volcano_tts')
VOLCENGINE_TTS_URL = 'https://openspeech.bytedance.com/api/v1/tts'

# Available TTS voices
TTS_VOICES = {
    'en': [
        {'id': 'en_female_dacey_uranus_bigtts', 'name': 'Dacey', 'gender': 'female', 'lang': 'en'},
        {'id': 'en_female_stokie_uranus_bigtts', 'name': 'Stokie', 'gender': 'female', 'lang': 'en'},
        {'id': 'en_male_tim_uranus_bigtts', 'name': 'Tim', 'gender': 'male', 'lang': 'en'},
        {'id': 'en_female_anna_mars_bigtts', 'name': 'Anna', 'gender': 'female', 'lang': 'en'},
        {'id': 'en_male_adam_mars_bigtts', 'name': 'Adam', 'gender': 'male', 'lang': 'en'},
        {'id': 'en_female_sarah_mars_bigtts', 'name': 'Sarah', 'gender': 'female', 'lang': 'en'},
        {'id': 'en_male_dryw_mars_bigtts', 'name': 'Dryw', 'gender': 'male', 'lang': 'en'},
        {'id': 'en_male_smith_mars_bigtts', 'name': 'Smith', 'gender': 'male', 'lang': 'en'},
        {'id': 'en_female_amanda_mars_bigtts', 'name': 'Amanda', 'gender': 'female', 'lang': 'en'},
        # Children voices (also work for English)
        {'id': 'zh_male_tiancaitongsheng_mars_bigtts', 'name': 'Child Boy', 'gender': 'male', 'lang': 'en', 'tag': 'child'},
        {'id': 'zh_male_naiqimengwa_mars_bigtts', 'name': 'Cute Kid', 'gender': 'male', 'lang': 'en', 'tag': 'child'},
        {'id': 'zh_female_shaoergushi_mars_bigtts', 'name': 'Story Girl', 'gender': 'female', 'lang': 'en', 'tag': 'child'},
        {'id': 'zh_female_peiqi_uranus_bigtts', 'name': 'Peppa', 'gender': 'female', 'lang': 'en', 'tag': 'child'},
    ],
    'zh': [
        {'id': 'zh_female_vv_uranus_bigtts', 'name': 'Vivi 2.0', 'name_en': 'Vivi 2.0', 'gender': 'female', 'lang': 'zh'},
        {'id': 'zh_female_xiaoxue_uranus_bigtts', 'name': '儿童绘本', 'name_en': 'Children Story', 'gender': 'female', 'lang': 'zh'},
        {'id': 'zh_male_tiancaitongsheng_mars_bigtts', 'name': '天才童声', 'name_en': 'Child Boy', 'gender': 'male', 'lang': 'zh', 'tag': 'child'},
        {'id': 'zh_male_naiqimengwa_mars_bigtts', 'name': '奶气萌娃', 'name_en': 'Cute Kid', 'gender': 'male', 'lang': 'zh', 'tag': 'child'},
        {'id': 'zh_female_shaoergushi_mars_bigtts', 'name': '少儿故事', 'name_en': 'Story Girl', 'gender': 'female', 'lang': 'zh', 'tag': 'child'},
        {'id': 'zh_female_peiqi_uranus_bigtts', 'name': '佩奇猪', 'name_en': 'Peppa', 'gender': 'female', 'lang': 'zh', 'tag': 'child'},
    ],
}

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)

# Django Sites Framework
SITE_ID = 1

# JWT Settings
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=360),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer', 'JWT'),
}

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# django-allauth settings
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_USERNAME_REQUIRED = True
ACCOUNT_AUTHENTICATION_METHOD = 'username_email'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_UNIQUE_EMAIL = True
LOGIN_REDIRECT_URL = '/api/v1/users/oauth-success/'
ACCOUNT_LOGOUT_REDIRECT_URL = 'http://localhost:5173/login'

# Social account settings
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_LOGIN_ON_GET = True

# Email settings for verification (using console backend for development)
# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # This is the SMTP server for Gmail
EMAIL_USE_TLS = True           # Gmail requires TLS
EMAIL_PORT = 587               # Standard port for SMTP with TLS
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'pivot.cs.project@gmail.com')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', 'pghvqicwwtowuijr')
EMAIL_TIMEOUT = 180
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
ACCOUNT_EMAIL_SUBJECT_PREFIX = '[Twinkle Twinkle] '

# Google OAuth settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        'OAUTH_PKCE_ENABLED': True,
    }
}