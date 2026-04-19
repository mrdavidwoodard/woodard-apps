import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'woodard_apps.db'}")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 25 * 1024 * 1024))

    DEFAULT_USER_FIRST_NAME = os.getenv("DEFAULT_USER_FIRST_NAME", "Demo")
    DEFAULT_USER_LAST_NAME = os.getenv("DEFAULT_USER_LAST_NAME", "User")
    DEFAULT_USER_EMAIL = os.getenv("DEFAULT_USER_EMAIL", "admin@woodard.local")
    DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD", "password")
    DEFAULT_USER_ROLE = os.getenv("DEFAULT_USER_ROLE", "admin")
    CREATE_DEFAULT_USER = os.getenv("CREATE_DEFAULT_USER", "true").lower() == "true"
    AUTO_CREATE_DATABASE = os.getenv("AUTO_CREATE_DATABASE", "true").lower() == "true"


class DevelopmentConfig(Config):
    DEBUG = True
    ENV = "development"


class ProductionConfig(Config):
    DEBUG = False
    ENV = "production"
    CREATE_DEFAULT_USER = os.getenv("CREATE_DEFAULT_USER", "false").lower() == "true"
    AUTO_CREATE_DATABASE = os.getenv("AUTO_CREATE_DATABASE", "false").lower() == "true"


def config_by_name(config_name=None):
    name = config_name or os.getenv("FLASK_ENV", "development")
    config_class = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
    }.get(name, DevelopmentConfig)

    if config_class is ProductionConfig and not os.getenv("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production.")

    return config_class
