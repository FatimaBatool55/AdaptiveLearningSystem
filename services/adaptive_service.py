"""
Adaptive difficulty engine.

USER-FACING ALGORITHM: Simple difficulty ladder (easy <-> medium <-> hard)
---------------------------------------------------------------------------
This is what the student sees and what actually drives which question comes
next. It's deterministic and easy to explain in a viva/demo:

    correct answer -> escalate one level   (easy -> medium -> hard)
    wrong answer   -> de-escalate one level (hard -> medium -> easy)

state.current_difficulty is ALWAYS one of "easy" / "medium" / "hard" and is
updated directly by apply_answer() every single time — no hidden formula
between an answer and what the student sees next.

INTERNAL / RESEARCH LAYER: Elo rating (not shown in the UI)
---------------------------------------------------------------------------
Underneath, the system also keeps an Elo-style ability rating per student and
per topic (cf. Pelánek, 2016, "Applications of the Elo Rating System in
Adaptive Educational Systems"). This is NOT used to decide what the student
sees or which question is served — it exists purely as a finer-grained,
continuous measurement for the research paper (e.g. plotting ability growth
across a session, comparing topics). It is written to the PDF report's
"Per-Topic Ability Rating" section, but intentionally never surfaced in the
quiz UI, because a raw number like "1327" means nothing to an end user
without training in psychometrics — showing it just confuses people, whereas
"easy/medium/hard" is instantly understandable.

    Expected(correct) = 1 / (1 + 10^((Q_elo - S_elo) / 400))
    S_elo_new = S_elo + K_student * (actual - expected)
    Q_elo_new = Q_elo - K_question * (actual - expected)
"""

from models import db
from models.models import Question, QuizState

DIFFICULTY_ORDER = ["easy", "medium", "hard"]
DIFFICULTY_UP = {"easy": "medium", "medium": "hard", "hard": "hard"}
DIFFICULTY_DOWN = {"hard": "medium", "medium": "easy", "easy": "easy"}

# Seed ratings for each AI-assigned difficulty label (chess-style scale) —
# internal research metric only, see module docstring.
SEED_ELO = {"easy": 1000.0, "medium": 1300.0, "hard": 1600.0}
K_STUDENT = 40.0
K_QUESTION = 15.0


class AdaptiveService:

    # ------------------------------------------------------------------
    # State lifecycle
    # ------------------------------------------------------------------
    @staticmethod
    def create_state(session_id, total_questions=10, mode="normal"):
        state = QuizState.query.filter_by(session_id=session_id).first()
        if state is None:
            state = QuizState(
                session_id=session_id,
                current_question=1,
                current_difficulty="medium",
                correct_answers=0,
                wrong_answers=0,
                used_questions=[],
                weak_topics={},
                current_topic="",
                total_questions=total_questions,
                completed=False,
                mode=mode,
                student_elo=1300.0,
                topic_elo={},
            )
            db.session.add(state)
            db.session.commit()
        return state

    @staticmethod
    def reset_state(state, total_questions=None, mode="normal"):
        state.current_question = 1
        state.current_difficulty = "medium"
        state.correct_answers = 0
        state.wrong_answers = 0
        state.used_questions = []
        state.weak_topics = {}
        state.current_topic = ""
        state.completed = False
        state.mode = mode
        state.student_elo = 1300.0
        state.topic_elo = {}
        if total_questions is not None:
            state.total_questions = total_questions
        db.session.commit()
        return state

    # ------------------------------------------------------------------
    # Question selection: never repeat, prefer same topic, then match the
    # CURRENT DIFFICULTY LABEL exactly (the thing the student actually saw
    # change). Falls back to the closest label if no exact match exists.
    # ------------------------------------------------------------------
    @staticmethod
    def pick_next_question(session_id, state):
        used_ids = set(state.used_questions or [])

        query = Question.query.filter_by(session_id=session_id)
        if state.mode == "weak_practice":
            query = query.filter_by(is_weak_practice=True)

        candidates = [q for q in query.all() if q.id not in used_ids]
        if not candidates:
            return None

        same_topic = [q for q in candidates if state.current_topic and q.topic == state.current_topic]
        pool = same_topic if same_topic else candidates

        exact = [q for q in pool if q.difficulty == state.current_difficulty]
        if exact:
            return exact[0]

        target_idx = DIFFICULTY_ORDER.index(state.current_difficulty)
        pool_sorted = sorted(pool, key=lambda q: abs(DIFFICULTY_ORDER.index(q.difficulty) - target_idx))
        if pool_sorted:
            return pool_sorted[0]

        return candidates[0]

    @staticmethod
    def mark_used(state, question_id):
        used = list(state.used_questions or [])
        used.append(question_id)
        state.used_questions = used  # reassignment (not in-place mutation) -> always persists

    @staticmethod
    def record_weak_topic(state, topic):
        weak = dict(state.weak_topics or {})
        weak[topic] = weak.get(topic, 0) + 1
        state.weak_topics = weak

    # ------------------------------------------------------------------
    # Elo helpers (internal research metric only — see module docstring)
    # ------------------------------------------------------------------
    @staticmethod
    def _topic_elo(state, topic):
        topic_ratings = state.topic_elo or {}
        return topic_ratings.get(topic, state.student_elo)

    @staticmethod
    def _set_topic_elo(state, topic, value):
        ratings = dict(state.topic_elo or {})
        ratings[topic] = value
        state.topic_elo = ratings

    @staticmethod
    def _expected_score(rating_a, rating_b):
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))

    @staticmethod
    def _update_elo(state, question, is_correct):
        topic = question.topic or "General"
        actual = 1.0 if is_correct else 0.0

        if not question.elo_rating:
            question.elo_rating = SEED_ELO.get(question.difficulty, 1300.0)

        student_rating = state.student_elo or 1300.0
        topic_rating = AdaptiveService._topic_elo(state, topic)
        question_rating = question.elo_rating

        blended_student_rating = (student_rating + topic_rating) / 2.0
        expected = AdaptiveService._expected_score(blended_student_rating, question_rating)

        state.student_elo = round(student_rating + K_STUDENT * (actual - expected), 2)
        AdaptiveService._set_topic_elo(state, topic, round(topic_rating + K_STUDENT * (actual - expected), 2))
        question.elo_rating = round(question_rating - K_QUESTION * (actual - expected), 2)
        question.times_answered = (question.times_answered or 0) + 1
        question.times_correct = (question.times_correct or 0) + (1 if is_correct else 0)

    # ------------------------------------------------------------------
    # Core adaptive update — call once per graded answer.
    # ------------------------------------------------------------------
    @staticmethod
    def apply_answer(state, question, is_correct):
        """Update counters, weak topics, the visible easy/medium/hard label,
        AND the internal Elo research metric — in that priority order. The
        difficulty label is always changed directly here; it never depends
        on the Elo numbers."""
        topic = question.topic or "General"

        # --- 1. The actual, user-visible adaptive step -------------------
        if is_correct:
            state.correct_answers += 1
            state.current_difficulty = DIFFICULTY_UP[state.current_difficulty]
        else:
            state.wrong_answers += 1
            AdaptiveService.record_weak_topic(state, topic)
            state.current_difficulty = DIFFICULTY_DOWN[state.current_difficulty]

        # --- 2. Internal research metric (not shown to the user) --------
        AdaptiveService._update_elo(state, question, is_correct)

    # ------------------------------------------------------------------
    @staticmethod
    def get_accuracy(state):
        total = state.correct_answers + state.wrong_answers
        if total == 0:
            return 0.0
        return round((state.correct_answers / total) * 100, 1)

    @staticmethod
    def elo_to_mastery_percent(rating):
        """Maps the internal Elo scale (roughly 800-1800) onto an intuitive
        0-100% mastery score for human-readable reporting. 1000 (easy seed)
        -> 20%, 1300 (medium seed) -> 50%, 1600 (hard seed) -> 80%."""
        percent = (rating - 800.0) / (1800.0 - 800.0) * 100.0
        return max(0, min(100, round(percent)))

    @staticmethod
    def elo_to_mastery_label(rating):
        percent = AdaptiveService.elo_to_mastery_percent(rating)
        if percent < 35:
            return "Needs Practice"
        if percent < 65:
            return "Developing"
        if percent < 85:
            return "Proficient"
        return "Strong"
