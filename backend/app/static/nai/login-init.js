// Page-specific init for login.html. External file (CSP-friendly).

bindAuthForm({
  formId: "login-form",
  submitId: "submit",
  errorId: "error",
  endpoint: "/auth/login",
  buildBody: () => ({
    email:    document.getElementById("email").value.trim(),
    password: document.getElementById("password").value,
  }),
  successRedirect: "/kai-ui/chat.html",
});
