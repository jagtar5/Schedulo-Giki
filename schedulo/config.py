import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "gik-timetable-secret-key-2026")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "timetable.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
