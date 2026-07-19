// SOL member app — core/guard.js
// Classic script (shared global scope). SolGuard: the ONE duplicate-submit lock.
// Centralizes the ~18 bespoke in-flight flags/Sets/Maps (_checkoutInFlight,
// _premCancelInFlight, _payInFlight[id], _bankRemoveInFlight, _kycInFlight,
// _discJoinBusy, _reserveBusy, _commPostBusy, _commLikeBusy[id], _commCommentBusy[id],
// _commReportBusy, _goalRestoreBusy, _goalConfirmBusy, notifState.busy[id], …).
//
// Semantics (preserved from the audited guards):
//   • acquire() is SYNCHRONOUS — take the lock before the first await
//   • a duplicate acquire() returns false (the second click is dropped)
//   • release() is idempotent and safe
//   • run()/runFor() release in finally and re-throw the original error
//   • per-record concurrency: reading notification A must not block B, etc.
//   • keys are stable internal strings — NEVER raw email/name/amount/provider id
//   • no persistence, no localStorage, no timeout auto-unlock, no optimistic state
window.SolGuard = (function () {
  const locks = new Set();
  const api = {
    acquire(key) {
      if (locks.has(key)) return false;
      locks.add(key);
      return true;
    },
    release(key) {
      locks.delete(key);
    },
    isLocked(key) {
      return locks.has(key);
    },
    // run(key, fn): acquire → await fn() → release in finally. Returns fn()'s
    // value on success; returns undefined WITHOUT calling fn if already locked
    // (the caller treats undefined-return as "dropped duplicate"). Re-throws
    // fn()'s error after releasing so callers keep their catch/UI behavior.
    async run(key, fn) {
      if (!api.acquire(key)) return undefined;
      try {
        return await fn();
      } finally {
        api.release(key);
      }
    },
    // runFor(scope, id, fn): per-record convenience — key = `scope:id`.
    runFor(scope, id, fn) {
      return api.run(scope + ':' + id, fn);
    },
  };
  return api;
})();
