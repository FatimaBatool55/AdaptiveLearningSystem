from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from models.models import (  
    LearningSession,
    Question,
    QuizState,
    QuizAttempt,
    Questionnaire,
)
