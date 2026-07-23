import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from groq import Groq
from flask import current_app


class AIServiceError(Exception):
    pass


class AIService:
    def __init__(self):
        api_key = current_app.config.get("GROQ_API_KEY")
        if not api_key:
            raise AIServiceError(
                "GROQ_API_KEY is not set. Add it to your .env file (see .env.example)."
            )
        self.client = Groq(api_key=api_key, timeout=25.0, max_retries=0)
        self.model = current_app.config.get("GROQ_MODEL", "openai/gpt-oss-20b")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_questions(self, text, education_level, question_type,
                            requested_questions, topics_filter=None):
        """
        Generate a mixed set of easy/medium/hard questions and return them as
        plain dicts (NOT saved to DB here — the caller decides how to persist
        them, e.g. tagging weak-practice questions separately).

        The three difficulty buckets are independent Groq API calls, so they
        run concurrently (thread pool) instead of one after another — this
        cuts total generation time roughly 3x since each call is
        network-bound (waiting on Groq), not CPU-bound.
        """
        per_bucket = max(1, requested_questions // 3)
        buckets = {
            "easy": per_bucket,
            "medium": per_bucket,
            "hard": requested_questions - (2 * per_bucket),
        }
        buckets = {k: v for k, v in buckets.items() if v > 0}

        all_questions = []
        errors = []

        with ThreadPoolExecutor(max_workers=len(buckets)) as executor:
            futures = {
                executor.submit(
                    self._generate_bucket, text, education_level, question_type,
                    count, difficulty, topics_filter
                ): difficulty
                for difficulty, count in buckets.items()
            }
            for future in as_completed(futures):
                difficulty = futures[future]
                try:
                    all_questions.extend(future.result())
                except AIServiceError as e:
                    errors.append(str(e))

        if not all_questions:
            detail = "; ".join(errors) if errors else "no questions were returned"
            raise AIServiceError(f"AI could not generate any questions from this material ({detail}).")

        return all_questions

    def _generate_bucket(self, text, education_level, question_type, count, difficulty, topics_filter):
        """Generate one difficulty bucket, with up to 2 retries. Raises
        AIServiceError if all attempts fail for this bucket."""
        prompt = self._build_prompt(
            text=text,
            education_level=education_level,
            question_type=question_type,
            total_questions=count,
            difficulty=difficulty,
            topics_filter=topics_filter,
        )

        last_error = None
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4,
                    max_tokens=min(4000, count * 350),
                )
                response_text = response.choices[0].message.content
                parsed = self._parse_json(response_text)
                validated = self._validate_questions(parsed, question_type)
                if validated:
                    return validated
            except Exception as e:  # noqa: BLE001 - we deliberately retry on any parse/API error
                last_error = e
                continue

        raise AIServiceError(
            f"could not generate {difficulty} questions after 2 attempts: {last_error}"
        )

    def generate_summary(self, topic, context_text=""):
        """Short 2-3 line plain-English explanation of a weak topic."""
        prompt = (
            f"Explain this topic simply in 3 lines for a student who got it wrong: \"{topic}\".\n"
            "No bullet points, no markdown, plain text only."
        )
        if context_text:
            prompt += f"\n\nRelevant study material for context:\n\"\"\"{context_text[:3000]}\"\"\""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return f"Review the topic '{topic}' again — it appeared in your incorrect answers."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, text, education_level, question_type, total_questions,
                       difficulty, topics_filter=None):
        topic_hint = ""
        if topics_filter:
            topic_hint = (
                f"\nFocus ONLY on these topics (the student got these wrong before): "
                f"{', '.join(topics_filter)}. Generate NEW, different questions strictly "
                f"about these topics.\n"
            )

        type_rules = (
            'Each question must be Multiple Choice with exactly 3 options in the '
            '"options" array, and "answer" must exactly match one of the 3 options.'
            if question_type == "mcq" else
            'Each question must be Fill in the Blank. Use "_____" inside "question" to mark '
            'the blank. Set "options" to an empty array []. "answer" is the exact word/phrase '
            "that fills the blank."
        )

        return f"""
You are an expert educational assessment designer.

STUDY MATERIAL:
\"\"\"{text[:12000]}\"\"\"

Generate exactly {total_questions} questions for {education_level} level.
Every question MUST have difficulty: "{difficulty}". Do NOT generate any other difficulty.
{topic_hint}
RULES:
1. Automatically detect topics from the material.
2. Every question MUST have exactly one topic.
3. Questions must test understanding, not memorization.
4. Explanation must be one short sentence.
5. "source_quote" must be the exact sentence/phrase from the study material that proves the answer.
6. {type_rules}
7. Return ONLY a valid JSON array — nothing else, no markdown fences, no commentary.

JSON FORMAT (array of objects with EXACTLY these keys):
[
  {{
    "topic": "SQL Joins",
    "difficulty": "{difficulty}",
    "question_type": "{question_type}",
    "question": "Which JOIN returns only matching rows?",
    "options": ["INNER JOIN", "LEFT JOIN", "RIGHT JOIN"],
    "answer": "INNER JOIN",
    "explanation": "INNER JOIN returns only matching rows.",
    "source_quote": "Types include INNER JOIN which returns only matching rows."
  }}
]

The response MUST start with [ and end with ].
"""

    def _parse_json(self, response_text):
        text = response_text.strip()
        text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```", "", text)
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            raise AIServiceError("AI response did not contain a JSON array.")
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError as e:
            raise AIServiceError(f"AI returned invalid JSON: {e}")

    def _validate_questions(self, questions, question_type):
        validated = []
        seen = set()
        for q in questions:
            try:
                question_text = str(q["question"]).strip()
                if not question_text or question_text in seen:
                    continue
                seen.add(question_text)

                topic = str(q.get("topic", "General")).strip() or "General"
                difficulty = str(q.get("difficulty", "medium")).lower()
                if difficulty not in ("easy", "medium", "hard"):
                    difficulty = "medium"
                explanation = str(q.get("explanation", "")).strip()
                answer = str(q["answer"]).strip()
                source_quote = str(q.get("source_quote", "")).strip()

                if question_type == "mcq":
                    options = q.get("options", [])
                    if not isinstance(options, list) or len(options) != 3:
                        continue
                    validated.append({
                        "topic": topic, "difficulty": difficulty, "question_type": "mcq",
                        "question": question_text,
                        "option_a": str(options[0]), "option_b": str(options[1]),
                        "option_c": str(options[2]),
                        "answer": answer, "explanation": explanation,
                        "source_quote": source_quote,
                    })
                else:
                    validated.append({
                        "topic": topic, "difficulty": difficulty, "question_type": "fill",
                        "question": question_text,
                        "option_a": "", "option_b": "", "option_c": "",
                        "answer": answer, "explanation": explanation,
                        "source_quote": source_quote,
                    })
            except (KeyError, TypeError, IndexError):
                continue
        return validated
