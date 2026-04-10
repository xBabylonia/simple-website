const form = document.getElementById("ask-form");
const questionInput = document.getElementById("question");
const message = document.getElementById("message");

function setMessage(text, type) {
  message.textContent = text;
  message.classList.remove("message--success", "message--error");

  if (type) {
    message.classList.add(`message--${type}`);
  }
}

questionInput.addEventListener("input", () => {
  setMessage("", null);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const question = questionInput.value.trim();

  if (!question) {
    setMessage("Please type a question before sending.", "error");
    questionInput.focus();
    return;
  }

  setMessage("Thanks! Your question has been received.", "success");
  form.reset();
  questionInput.focus();
});
