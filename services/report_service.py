import os
from datetime import datetime
from fpdf import FPDF

from services.ai_service import AIService
from services.adaptive_service import AdaptiveService


class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "AI Adaptive Learning - Quiz Report", ln=True, align="C")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 6, datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), ln=True, align="C")
        self.ln(4)

    def section_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 30, 120)
        self.cell(0, 8, title, ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def body_text(self, text):
        self.set_font("Helvetica", "", 11)
        self.safe_multi_cell(6, text)
        self.ln(1)

    def safe_multi_cell(self, h, text):
        """multi_cell(w=0, ...) computes width from the CURRENT x position.
        If a previous cell()/multi_cell() call left x anywhere but the left
        margin, w=0 can end up too narrow (or zero), causing fpdf2 to raise
        'Not enough horizontal space to render a single character'. Always
        reset x first."""
        self.set_x(self.l_margin)
        self.multi_cell(0, h, text)


def _safe(text):
    if text is None:
        return ""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def build_pdf_report(session, quiz_state, attempts, output_folder):
    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    total = quiz_state.correct_answers + quiz_state.wrong_answers
    accuracy = round((quiz_state.correct_answers / total) * 100, 1) if total else 0

    pdf.section_title("Student Statistics")
    pdf.body_text(
        f"Education Level: {_safe(session.education_level)}\n"
        f"Question Type: {_safe(session.question_type)}\n"
        f"Total Questions Attempted: {total}\n"
        f"Correct: {quiz_state.correct_answers}\n"
        f"Wrong: {quiz_state.wrong_answers}\n"
        f"Accuracy: {accuracy}%"
    )

    weak_topics = quiz_state.weak_topics or {}

    topic_elo = quiz_state.topic_elo or {}
    pdf.section_title("Topic Mastery")
    if topic_elo:
        pdf.body_text(
            "Estimated mastery level per topic, based on performance across the session:"
        )
        for topic, rating in sorted(topic_elo.items(), key=lambda x: -x[1]):
            percent = AdaptiveService.elo_to_mastery_percent(rating)
            label = AdaptiveService.elo_to_mastery_label(rating)
            pdf.body_text(f"- {_safe(topic)}: {label} ({percent}%)")
    else:
        pdf.body_text("No topic mastery data available for this session.")

    pdf.section_title("Weak Topics")
    if weak_topics:
        for topic, count in sorted(weak_topics.items(), key=lambda x: -x[1]):
            pdf.body_text(f"- {_safe(topic)} (missed {count} time(s))")
    else:
        pdf.body_text("No significant weak topics detected. Great job!")

    if weak_topics:
        pdf.section_title("Learning Summaries")
        try:
            ai = AIService()
        except Exception:
            ai = None
        for topic in weak_topics.keys():
            try:
                summary = ai.generate_summary(topic, session.extracted_text) if ai else "Summary unavailable (AI not configured)."
            except Exception:
                summary = "Summary unavailable."
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_x(pdf.l_margin)
            pdf.cell(0, 6, _safe(topic), ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.safe_multi_cell(5, _safe(summary))
            pdf.ln(2)

    pdf.section_title("Question History")
    for i, attempt in enumerate(attempts, start=1):
        q = attempt.question
        result = "Correct" if attempt.is_correct else "Wrong"
        pdf.set_font("Helvetica", "B", 10)
        pdf.safe_multi_cell(5, f"{i}. [{_safe(q.difficulty).upper()}] {_safe(q.topic)} - {result}")
        pdf.set_font("Helvetica", "", 10)
        pdf.safe_multi_cell(5, f"   Q: {_safe(q.question)}")
        pdf.safe_multi_cell(5, f"   Correct Answer: {_safe(q.answer)}")
        pdf.ln(1)

    pdf.section_title("Recommendations")
    if weak_topics:
        rec = (
            "Focus additional study time on the weak topics listed above. "
            "Use the 'Practice Weak Areas' feature to reinforce these concepts with new questions."
        )
    else:
        rec = "Performance is strong across all topics. Consider increasing difficulty or exploring advanced material."
    pdf.body_text(rec)

    os.makedirs(output_folder, exist_ok=True)
    filename = f"report_{session.id}.pdf"
    filepath = os.path.join(output_folder, filename)
    pdf.output(filepath)
    return filepath
