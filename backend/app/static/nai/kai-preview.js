// No-login preview of KAI's avatar so the operator can confirm what the daemon
// is actually serving (the dashboard's ◉ KAI tab uses the same avatar.js).
// Drives a fake voice envelope so the mouth visibly lip-syncs without audio.
import { KaiAvatar } from './avatar.js?v=rpm1';

const k = new KaiAvatar(document.getElementById('c'));
k.setMood('happy');
k.start();
k.setSpeaking(true);
window.__kai = k;

// Demo "speech": oscillate the voice level so the jaw morph opens/closes as if
// talking (in the dashboard this is the real TTS amplitude).
let t = 0;
setInterval(() => {
  t += 0.12;
  const env = Math.max(0, Math.sin(t * 3.1) * 0.5 + Math.sin(t * 7.7) * 0.3 + 0.25);
  k.setVoiceLevel(Math.min(1, env));
}, 60);
