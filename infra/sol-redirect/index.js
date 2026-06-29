// Edge redirect: app.wheellsverse.com/sol* -> wheellsverse.com/sol*
// The Sol app is served (correctly, with all fixes) from Cloudflare Pages on
// wheellsverse.com. app.wheellsverse.com is a separate, stale origin (the
// Railway backend that also serves KAI / the API / /go links). This Worker is
// scoped ONLY to the /sol path on app., so everything else on app. is untouched.
export default {
  fetch(request) {
    const url = new URL(request.url);
    url.protocol = "https:";
    url.hostname = "wheellsverse.com";
    // 302 (temporary) so it is trivially reversible and never hard-cached.
    return Response.redirect(url.toString(), 302);
  },
};
