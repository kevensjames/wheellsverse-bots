// If you already have a session, skip the landing and go straight to chat.
    // /auth/me returns 200 + user JSON when logged in, 401 otherwise.
    fetch("/auth/me", { credentials: "same-origin" })
      .then(r => { if (r.ok) window.location.replace("/kai-ui/chat.html"); })
      .catch(() => {});
