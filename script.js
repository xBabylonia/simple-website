const form = document.getElementById("ask-form");
const questionInput = document.getElementById("question");
const message = document.getElementById("message");

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const question = questionInput.value.trim();

  if (!question) {
    message.textContent = "Please type a question before sending.";
    questionInput.focus();
    return;
  }

  message.textContent = "Thanks! Your question has been received.";
  form.reset();
  questionInput.focus();
});
