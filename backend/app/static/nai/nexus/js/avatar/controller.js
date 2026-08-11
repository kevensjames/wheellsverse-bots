// ============================================================================
// KAI avatar controller (§9 asset strategy + §41 fallback)
// Selects the render backend and exposes ONE unified API (litHalo, lookAt,
// destroy) so nothing else in the app cares which backend is live.
//
//   canvas2d  — the procedural presence (this repo's working backend + the
//               guaranteed WebGL-less fallback, §41). Mounts immediately.
//   gltf      — photoreal rigged GLB/VRM (js/avatar/gltf.js). Activates only when
//               a 3D lib + rigged asset are supplied; see mountKaiPhotoreal().
//
// We mount the placeholder now and DO NOT claim photoreal complete — honest §9.
// ============================================================================
import { mountAvatar } from '../avatar.js';
import { tryMountGltf, hasWebGL } from './gltf.js';

export function mountKai(canvas) {
  const a = mountAvatar(canvas);
  canvas.dataset.avatarBackend = 'canvas2d';
  return {
    backend: 'canvas2d',
    litHalo: s => a.litHalo && a.litHalo(s),
    lookAt: (x, y) => a.lookAt && a.lookAt(x, y),
    destroy: () => a.destroy && a.destroy(),
  };
}

// Integrator entry point: once window.THREE (+GLTFLoader) and assets/kai.glb
// exist, call this on a DEDICATED canvas (a WebGL context can't share a 2D one).
// Returns the gltf controller, or null if the lib/asset/WebGL isn't available.
export async function mountKaiPhotoreal(canvas) { return tryMountGltf(canvas); }

export { hasWebGL };
