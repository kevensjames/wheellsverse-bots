// No-login preview of KAI's avatar so the operator can confirm what the daemon
// is actually serving (the dashboard's ◉ KAI tab uses the same avatar.js).
import { KaiAvatar } from './avatar.js?v=cyborg4';
const k = new KaiAvatar(document.getElementById('c'));
k.setMood('happy');
k.start();
k.setSpeaking(true);          // open the mouth + equalizer so it's clearly alive
window.__kai = k;
