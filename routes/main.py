import os
import time
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    jsonify, send_file, current_app, flash
)
from werkzeug.utils import secure_filename

from models import db
from models.models import (
    LearningSession, Question, QuizState, QuizAttempt, Questionnaire
)
from services.file_service import allowed_file, extract_text
from services.ai_service import AIService, AIServiceError
from services.adaptive_service import AdaptiveService, SEED_ELO
from services.report_service import build_pdf_report

main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def question_json(q, reveal=False):
    return q.to_dict(include_answer=reveal)


def _save_questions(session_id, items, question_type, is_weak_practice=False):
    for item in items:
        q = Question(
            session_id=session_id,
            topic=item["topic"],
            difficulty=item["difficulty"],
            question_type=question_type,
            question=item["question"],
            option_a=item.get("option_a", ""),
            option_b=item.get("option_b", ""),
            option_c=item.get("option_c", ""),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
            source_quote=item.get("source_quote", ""),
            is_weak_practice=is_weak_practice,
            elo_rating=SEED_ELO.get(item["difficulty"], 1300.0),
        )
        db.session.add(q)
    db.session.commit()


# ---------------------------------------------------------------------
# HOME
# ---------------------------------------------------------------------

@main_bp.route("/")
def home():
    return render_template("home.html")


# ---------------------------------------------------------------------
# UPLOAD
# ---------------------------------------------------------------------

@main_bp.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html")

    education_level = request.form.get("education_level", "University")
    question_type = request.form.get("question_type", "mcq")
    try:
        question_count = int(request.form.get("question_count", 10))
    except (TypeError, ValueError):
        question_count = 10

    merged_text = ""
    notes = request.form.get("notes", "").strip()
    if notes:
        merged_text += notes + "\n\n"

    files = request.files.getlist("files")
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    extraction_start = time.monotonic()
    for file in files:
        if not file or file.filename == "":
            continue
        if not allowed_file(file.filename):
            flash(f"Skipped unsupported file type: {file.filename}")
            continue

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if current_app.config.get("IS_VERCEL") and ext in ("jpg", "jpeg", "png"):
            flash(
                f"Skipped {file.filename}: image text extraction (OCR) isn't available "
                "on this hosting platform. Please use a PDF, DOCX, PPTX, or TXT file instead."
            )
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        file_start = time.monotonic()
        try:
            merged_text += extract_text(filepath) + "\n\n"
        except Exception as e:
            flash(f"Could not read {filename}: {e}")
            continue
        finally:
            current_app.logger.info(
                f"[timing] Extracted {filename} in {time.monotonic() - file_start:.1f}s"
            )
    current_app.logger.info(
        f"[timing] All file extraction took {time.monotonic() - extraction_start:.1f}s total"
    )

    if not merged_text.strip() or len(merged_text.strip()) < 20:
        flash("No readable study material found. Paste some notes or upload a valid file.")
        return redirect(url_for("main.upload"))

    session_obj = LearningSession(
        education_level=education_level,
        question_type=question_type,
        requested_questions=question_count,
        extracted_text=merged_text,
    )
    db.session.add(session_obj)
    db.session.commit()

    ai_start = time.monotonic()
    try:
        ai = AIService()
        generated = ai.generate_questions(
            text=merged_text,
            education_level=education_level,
            question_type=question_type,
            requested_questions=question_count,
        )
    except AIServiceError as e:
        current_app.logger.info(
            f"[timing] AI generation FAILED after {time.monotonic() - ai_start:.1f}s: {e}"
        )
        flash(f"Failed to generate questions: {e}")
        db.session.delete(session_obj)
        db.session.commit()
        return redirect(url_for("main.upload"))

    current_app.logger.info(
        f"[timing] AI question generation took {time.monotonic() - ai_start:.1f}s "
        f"for {len(generated)} questions"
    )

    _save_questions(session_obj.id, generated, question_type)

    AdaptiveService.create_state(session_obj.id, total_questions=len(generated))

    return redirect(url_for("main.quiz", session_id=session_obj.id))


# ---------------------------------------------------------------------
# QUIZ — single page, AJAX only (no reload per question)
# ---------------------------------------------------------------------

@main_bp.route("/quiz/<int:session_id>")
def quiz(session_id):
    session_obj = LearningSession.query.get_or_404(session_id)
    state = AdaptiveService.create_state(session_id, total_questions=session_obj.requested_questions)

    q = AdaptiveService.pick_next_question(session_id, state)
    if q is None:
        state.completed = True
        db.session.commit()
        return render_template("quiz.html", session_id=session_id, initial_question=None, state=state)

    state.current_topic = q.topic
    db.session.commit()

    return render_template(
        "quiz.html",
        session_id=session_id,
        initial_question=question_json(q),
        question_number=state.current_question,
        total_questions=state.total_questions,
        state=state,
    )


# ---------------------------------------------------------------------
# AJAX: submit answer (grades + updates adaptive state; does NOT advance
# current_question — that happens exactly once, in /next)
# ---------------------------------------------------------------------

@main_bp.route("/submit/<int:session_id>", methods=["POST"])
def submit(session_id):
    state = QuizState.query.filter_by(session_id=session_id).first_or_404()
    data = request.get_json(force=True)
    question_id = data.get("question_id")
    selected_answer = (data.get("selected_answer") or "").strip()

    question = Question.query.get_or_404(question_id)
    is_correct = selected_answer.strip().lower() == (question.answer or "").strip().lower()

    attempt = QuizAttempt(session_id=session_id, question_id=question.id, is_correct=is_correct)
    db.session.add(attempt)

    AdaptiveService.mark_used(state, question.id)
    AdaptiveService.apply_answer(state, question, is_correct)

    finished = state.current_question >= state.total_questions
    db.session.commit()

    return jsonify({
        "correct": is_correct,
        "correct_answer": question.answer,
        "explanation": question.explanation,
        "finished": finished,
    })


# ---------------------------------------------------------------------
# AJAX: advance to next question (the ONLY place current_question is
# incremented — fixes the previous double-increment bug where both
# /submit and /next bumped the counter)
# ---------------------------------------------------------------------

@main_bp.route("/next/<int:session_id>", methods=["POST"])
def next_question(session_id):
    state = QuizState.query.filter_by(session_id=session_id).first_or_404()

    def results_payload():
        return {
            "accuracy": AdaptiveService.get_accuracy(state),
            "correct": state.correct_answers,
            "wrong": state.wrong_answers,
            "weak_topics": state.weak_topics or {},
        }

    if state.completed or state.current_question >= state.total_questions:
        state.completed = True
        db.session.commit()
        return jsonify({"finished": True, "results": results_payload()})

    state.current_question += 1
    q = AdaptiveService.pick_next_question(session_id, state)

    if q is None:
        state.completed = True
        db.session.commit()
        return jsonify({"finished": True, "results": results_payload()})

    state.current_topic = q.topic
    db.session.commit()

    return jsonify({
        "finished": False,
        "question": question_json(q),
        "question_number": state.current_question,
        "total_questions": state.total_questions,
        "difficulty": state.current_difficulty,
    })


# ---------------------------------------------------------------------
# RETAKE — reset the SAME quiz state (not delete/recreate, which lost the
# session's total_questions/mode context in the previous version)
# ---------------------------------------------------------------------

@main_bp.route("/retake/<int:session_id>", methods=["POST"])
def retake(session_id):
    session_obj = LearningSession.query.get_or_404(session_id)
    state = QuizState.query.filter_by(session_id=session_id).first_or_404()
    AdaptiveService.reset_state(state, total_questions=session_obj.requested_questions, mode="normal")
    return jsonify({"status": "ok", "redirect": url_for("main.quiz", session_id=session_id)})


# ---------------------------------------------------------------------
# PRACTICE WEAK AREAS — generates NEW AI questions only on weak topics
# ---------------------------------------------------------------------

@main_bp.route("/weak/<int:session_id>", methods=["POST"])
def weak_practice(session_id):
    session_obj = LearningSession.query.get_or_404(session_id)
    state = QuizState.query.filter_by(session_id=session_id).first_or_404()
    weak_topics = list((state.weak_topics or {}).keys())

    if not weak_topics:
        return jsonify({"status": "error", "message": "No weak topics found yet."}), 400

    try:
        ai = AIService()
        generated = ai.generate_questions(
            text=session_obj.extracted_text,
            education_level=session_obj.education_level,
            question_type=session_obj.question_type,
            requested_questions=max(6, len(weak_topics) * 3),
            topics_filter=weak_topics,
        )
    except AIServiceError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    _save_questions(session_obj.id, generated, session_obj.question_type, is_weak_practice=True)

    AdaptiveService.reset_state(state, total_questions=len(generated), mode="weak_practice")

    return jsonify({"status": "ok", "redirect": url_for("main.quiz", session_id=session_id)})


# ---------------------------------------------------------------------
# DOWNLOAD PDF REPORT — previously just returned "PDF Report Coming Soon"
# ---------------------------------------------------------------------

@main_bp.route("/download/<int:session_id>")
def download_report(session_id):
    session_obj = LearningSession.query.get_or_404(session_id)
    state = QuizState.query.filter_by(session_id=session_id).first_or_404()
    attempts = (
        QuizAttempt.query.filter_by(session_id=session_id)
        .order_by(QuizAttempt.created_at.asc())
        .all()
    )

    reports_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "reports")
    filepath = build_pdf_report(session_obj, state, attempts, reports_folder)

    return send_file(filepath, as_attachment=True, download_name=f"quiz_report_{session_id}.pdf")


# ---------------------------------------------------------------------
# QUESTIONNAIRE — fixed to match the (now-corrected) Questionnaire model
# ---------------------------------------------------------------------

@main_bp.route("/questionnaire/<int:session_id>", methods=["POST"])
def questionnaire(session_id):
    LearningSession.query.get_or_404(session_id)
    data = request.get_json(force=True) if request.is_json else request.form

    existing = Questionnaire.query.filter_by(session_id=session_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()

    q = Questionnaire(
        session_id=session_id,
        q1_understanding=data.get("q1", "Neutral"),
        q2_adaptive_difficulty=data.get("q2", "Neutral"),
        q3_feedback=data.get("q3", "Neutral"),
        q4_weak_topics=data.get("q4", "Neutral"),
        q5_trust=data.get("q5", "Neutral"),
        q6_engagement=data.get("q6", "Neutral"),
        q7_ease_of_use=data.get("q7", "Neutral"),
        q8_preference=data.get("q8", "Neutral"),
        comments=data.get("comments", ""),
    )
    db.session.add(q)
    db.session.commit()

    return jsonify({"status": "ok", "message": "Thank you for your feedback!"})


# ---------------------------------------------------------------------
# MISC
# ---------------------------------------------------------------------

@main_bp.route("/health")
def health():
    return {"status": "running", "application": "AI Adaptive Learning Assistant"}


@main_bp.app_errorhandler(404)
def not_found(error):
    return render_template("base.html"), 404


@main_bp.app_errorhandler(413)
def payload_too_large(error):
    flash(
        "That upload was too large for this deployment platform to accept. "
        "Try a smaller file, or paste the text directly into the notes box instead."
    )
    return redirect(url_for("main.upload"))


@main_bp.app_errorhandler(500)
def server_error(error):
    return "500 - Internal Server Error", 500
