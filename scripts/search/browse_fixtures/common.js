// Tiny helpers shared by the fixture pages. log() reports to the fixture server so the
// harness can check what the model actually did (not just what it claims).
function log(event, data) {
  fetch('/log', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: location.pathname, event, data})}).catch(() => {});
}
function code(s) { // deterministic short code from a string, so the model cannot guess it
  let h = 2166136261;
  for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  return 'K' + h.toString(36).toUpperCase().slice(0, 6);
}
