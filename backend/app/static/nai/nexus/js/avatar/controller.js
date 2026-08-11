// ============================================================================
// KAI avatar controller (§9 / §21 / §41)
// Backends, in preference order:
//   portrait — semi-photoreal generated hero image (assets/kai.jpg) + live canvas
//              overlay (halo · particles · eye-glow · state). Default.
//   gltf     — rigged GLB/VRM in WebGL (js/avatar/gltf.js), when a lib + asset exist.
//   canvas2d — procedural mannequin (js/avatar.js): the guaranteed fallback if the
//              portrait image fails to load or the stage markup is absent (§41).
// One unified API (litHalo, lookAt, destroy) regardless of backend.
// ============================================================================
import { mountAvatar } from '../avatar.js';
import { mountPortrait } from './portrait.js';
import { tryMountGltf, hasWebGL } from './gltf.js';

export function mountKai(stage) {
  const img = stage.querySelector('#kai-portrait');
  const halo = stage.querySelector('#kai-halo');
  const fx = stage.querySelector('#kai-fx');

  if (img && halo && fx) {
    const p = mountPortrait({ stage, halo, fx, img });
    stage.dataset.avatarBackend = 'portrait';
    // if the hero image can't load, fall back to the procedural mannequin (§41)
    img.addEventListener('error', () => {
      img.style.display = 'none';
      const c = document.createElement('canvas'); c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:1';
      stage.appendChild(c); mountAvatar(c); stage.dataset.avatarBackend = 'canvas2d-fallback';
    }, { once: true });
    return { backend: 'portrait', litHalo: s => p.litHalo(s), lookAt: (x, y) => p.lookAt(x, y), destroy: () => p.destroy() };
  }

  // no portrait markup → procedural mannequin
  const canvas = stage.querySelector('canvas') || stage.appendChild(document.createElement('canvas'));
  const a = mountAvatar(canvas); stage.dataset.avatarBackend = 'canvas2d';
  return { backend: 'canvas2d', litHalo: s => a.litHalo && a.litHalo(s), lookAt: (x, y) => a.lookAt && a.lookAt(x, y), destroy: () => a.destroy && a.destroy() };
}

export async function mountKaiPhotoreal(canvas) { return tryMountGltf(canvas); }
export { hasWebGL };
