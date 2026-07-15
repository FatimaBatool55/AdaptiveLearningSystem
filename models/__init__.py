from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from models.models import (  # noqa: E402,F401
    LearningSession,
    Question,
    QuizState,
    QuizAttempt,
    Questionnaire,
)
