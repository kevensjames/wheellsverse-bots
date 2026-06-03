// Page-specific init for signup.html. Lives in its own file so the page can
// stay free of inline <script> blocks and CSP can stay strict
// (script-src 'self', no 'unsafe-inline').

bindAuthForm({
  formId: "signup-form",
  submitId: "submit",
  errorId: "error",
  endpoint: "/auth/signup",
  buildBody: () => ({
    email:     document.getElementById("email").value.trim(),
    password:  document.getElementById("password").value,
    full_name: document.getElementById("full_name").value.trim(),
  }),
  successRedirect: "/kai-ui/",
});
