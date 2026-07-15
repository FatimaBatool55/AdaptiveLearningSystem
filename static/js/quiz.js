(function () {
  const sessionId = window.SESSION_ID;
  let currentQuestion = window.INITIAL_QUESTION;
  let questionNumber = window.QUESTION_NUMBER || 1;
  let totalQuestions = window.TOTAL_QUESTIONS || 10;
  let difficulty = window.INITIAL_DIFFICULTY || "medium";
  let answered = false;

  const quizCard = document.getElementById("quizCard");
  const resultsCard = document.getElementById("resultsCard");
  const questionnaireCard = document.getElementById("questionnaireCard");

  const questionCounter = document.getElementById("questionCounter");
  const difficultyBadge = document.getElementById("difficultyBadge");
  const questionText = document.getElementById("questionText");
  const optionsContainer = document.getElementById("optionsContainer");
  const feedbackBox = document.getElementById("feedbackBox");
  const feedbackAlert = document.getElementById("feedbackAlert");
  const explanationBox = document.getElementById("explanationBox");
  const nextBtn = document.getElementById("nextBtn");

  function renderQuestion(q) {
    answered = false;
    feedbackBox.classList.add("d-none");
    nextBtn.classList.add("d-none");
    questionCounter.textContent = `Question ${questionNumber} of ${totalQuestions}`;
    difficultyBadge.textContent = `Difficulty: ${difficulty}`;
    questionText.textContent = q.question;

    optionsContainer.innerHTML = "";

    if (q.question_type === "mcq") {
      const options = [q.option_a, q.option_b, q.option_c].filter(Boolean);
      options.forEach((optText) => {
        const btn = document.createElement("button");
        btn.className = "btn option-btn";
        btn.textContent = optText;
        btn.addEventListener("click", () => submitAnswer(q.id, optText, btn));
        optionsContainer.appendChild(btn);
      });
    } else {
      // Fill in the blank
      const inputGroup = document.createElement("div");
      inputGroup.className = "input-group";
      const input = document.createElement("input");
      input.type = "text";
      input.className = "form-control";
      input.placeholder = "Type your answer...";
      const submitBtn = document.createElement("button");
      submitBtn.className = "btn btn-primary";
      submitBtn.textContent = "Submit";
      submitBtn.addEventListener("click", () => submitAnswer(q.id, input.value, submitBtn, input));
      inputGroup.appendChild(input);
      inputGroup.appendChild(submitBtn);
      optionsContainer.appendChild(inputGroup);
    }
  }

  function submitAnswer(questionId, selectedAnswer, clickedBtn, inputEl) {
    if (answered) return;
    answered = true;

    fetch(`/submit/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_id: questionId, selected_answer: selectedAnswer }),
    })
      .then((res) => res.json())
      .then((data) => {
        // Disable all option buttons
        document.querySelectorAll(".option-btn").forEach((b) => (b.disabled = true));
        if (inputEl) inputEl.disabled = true;

        if (clickedBtn && clickedBtn.classList.contains("option-btn")) {
          clickedBtn.classList.add(data.correct ? "correct-answer" : "wrong-answer");
          if (!data.correct) {
            document.querySelectorAll(".option-btn").forEach((b) => {
              if (b.textContent.trim() === data.correct_answer.trim()) {
                b.classList.add("correct-answer");
              }
            });
          }
        }

        feedbackBox.classList.remove("d-none");
        feedbackAlert.className = "alert " + (data.correct ? "alert-success" : "alert-danger");
        feedbackAlert.textContent = data.correct
          ? "✓ Correct!"
          : `✗ Wrong. Correct Answer: ${data.correct_answer}`;
        explanationBox.textContent = data.explanation || "";

        nextBtn.classList.remove("d-none");
        nextBtn.dataset.finished = data.finished ? "true" : "false";
      })
      .catch((err) => {
        console.error(err);
        answered = false;
      });
  }

  nextBtn.addEventListener("click", () => {
    fetch(`/next/${sessionId}`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        if (data.finished) {
          showResults(data.results);
        } else {
          questionNumber = data.question_number;
          totalQuestions = data.total_questions;
          difficulty = data.difficulty;
          renderQuestion(data.question);
        }
      })
      .catch((err) => console.error(err));
  });

  function showResults(results) {
    quizCard.classList.add("d-none");
    resultsCard.classList.remove("d-none");
    questionnaireCard.classList.remove("d-none");

    document.getElementById("accuracyStat").textContent = `${results.accuracy}%`;
    document.getElementById("correctStat").textContent = results.correct;
    document.getElementById("wrongStat").textContent = results.wrong;

    const weakList = document.getElementById("weakTopicsList");
    weakList.innerHTML = "";
    const weakTopics = results.weak_topics || {};
    const weakSection = document.getElementById("weakTopicsSection");

    if (Object.keys(weakTopics).length === 0) {
      weakSection.classList.add("d-none");
    } else {
      weakSection.classList.remove("d-none");
      Object.entries(weakTopics).forEach(([topic, count]) => {
        const li = document.createElement("li");
        li.className = "list-group-item";
        li.innerHTML = `<span>${topic}</span><span class="badge bg-danger rounded-pill">${count}</span>`;
        weakList.appendChild(li);
      });
    }
  }

  document.getElementById("retakeBtn").addEventListener("click", () => {
    fetch(`/retake/${sessionId}`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        window.location.href = data.redirect;
      });
  });

  document.getElementById("weakBtn").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "Generating...";
    fetch(`/weak/${sessionId}`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        if (data.status === "ok") {
          window.location.href = data.redirect;
        } else {
          alert(data.message || "Could not generate weak-topic practice.");
          btn.disabled = false;
          btn.textContent = "Practice Weak Areas";
        }
      });
  });

  document.getElementById("questionnaireForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());

    fetch(`/questionnaire/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then(() => {
        form.classList.add("d-none");
        document.getElementById("thankYouBox").classList.remove("d-none");
      });
  });

  // Initial render
  if (currentQuestion) {
    renderQuestion(currentQuestion);
  } else {
    // No questions available -> straight to results (edge case)
    fetch(`/next/${sessionId}`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        if (data.finished) showResults(data.results);
      });
  }
})();
