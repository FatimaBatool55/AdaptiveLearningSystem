from datetime import datetime
from sqlalchemy.ext.mutable import MutableDict, MutableList
from . import db


class LearningSession(db.Model):
    __tablename__ = "learning_sessions"

    id = db.Column(db.Integer, primary_key=True)
    education_level = db.Column(db.String(50), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)  # mcq / fill
    requested_questions = db.Column(db.Integer, nullable=False)
    extracted_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    questions = db.relationship(
        "Question", backref="session", cascade="all, delete-orphan", lazy=True
    )
    quiz_state = db.relationship(
        "QuizState", backref="session", uselist=False, cascade="all, delete-orphan"
    )
    attempts = db.relationship(
        "QuizAttempt", backref="session", cascade="all, delete-orphan", lazy=True
    )
    questionnaire = db.relationship(
        "Questionnaire", backref="session", uselist=False, cascade="all, delete-orphan"
    )


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("learning_sessions.id"), nullable=False)
    topic = db.Column(db.String(200), default="General")
    difficulty = db.Column(db.String(20), default="medium")  # easy/medium/hard
    question_type = db.Column(db.String(20), default="mcq")   # mcq / fill
    question = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500))
    option_b = db.Column(db.String(500))
    option_c = db.Column(db.String(500))
    answer = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text)
    source_quote = db.Column(db.Text)
    is_weak_practice = db.Column(db.Boolean, default=False)

    # Elo rating for adaptive difficulty selection. Seeded from the AI's
    # difficulty label, then recalibrated after every attempt based on how
    # students actually perform on it (see AdaptiveService.update_elo).
    elo_rating = db.Column(db.Float, default=1300.0)
    times_answered = db.Column(db.Integer, default=0)
    times_correct = db.Column(db.Integer, default=0)

    def to_dict(self, include_answer=False):
        data = {
            "id": self.id,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "question_type": self.question_type,
            "question": self.question,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
        }
        if include_answer:
            data["answer"] = self.answer
            data["explanation"] = self.explanation
            data["source_quote"] = self.source_quote
        return data


class QuizState(db.Model):
    __tablename__ = "quiz_states"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("learning_sessions.id"), nullable=False, unique=True)
    current_question = db.Column(db.Integer, default=1)
    current_difficulty = db.Column(db.String(20), default="medium")
    correct_answers = db.Column(db.Integer, default=0)
    wrong_answers = db.Column(db.Integer, default=0)

    # MutableList/MutableDict make SQLAlchemy detect in-place .append()/[key]=
    # mutations on JSON columns and persist them — the previous version used
    # plain JSON columns which silently dropped in-place mutations.
    used_questions = db.Column(MutableList.as_mutable(db.JSON), default=list)
    weak_topics = db.Column(MutableDict.as_mutable(db.JSON), default=dict)

    current_topic = db.Column(db.String(200), default="")
    total_questions = db.Column(db.Integer, default=10)
    completed = db.Column(db.Boolean, default=False)
    mode = db.Column(db.String(20), default="normal")  # normal / weak_practice
    started_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Elo-based adaptive difficulty: student's overall ability rating plus
    # a per-topic breakdown, both updated after every answer. Using per-topic
    # ratings (not just one global number) is what lets the system say
    # "strong in Topic A, weak in Topic B" instead of one blended difficulty.
    student_elo = db.Column(db.Float, default=1300.0)
    topic_elo = db.Column(MutableDict.as_mutable(db.JSON), default=dict)


class QuizAttempt(db.Model):
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("learning_sessions.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    question = db.relationship("Question")


class Questionnaire(db.Model):
    __tablename__ = "questionnaires"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("learning_sessions.id"), nullable=False)

    # Each stores one of: "Strongly Agree", "Agree", "Neutral", "Disagree", "Strongly Disagree"
    q1_understanding = db.Column(db.String(30))         # improved understanding of study material
    q2_adaptive_difficulty = db.Column(db.String(30))   # difficulty matched learning level
    q3_feedback = db.Column(db.String(30))              # explanations/feedback helped identify mistakes
    q4_weak_topics = db.Column(db.String(30))           # weak-topic summaries improved understanding
    q5_trust = db.Column(db.String(30))                 # AI-generated questions/answers felt accurate & trustworthy
    q6_engagement = db.Column(db.String(30))            # system kept me engaged / motivated to keep studying
    q7_ease_of_use = db.Column(db.String(30))           # easy to use and navigate
    q8_preference = db.Column(db.String(30))            # prefer this over traditional self-study

    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
