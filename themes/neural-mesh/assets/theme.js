/* WheellsVerse · Neural-Mesh · runtime */
(function() {
  'use strict';
  function neuralCanvas() {
    var c = document.getElementById('neural-canvas');
    if (!c) return;
    var ctx = c.getContext('2d');
    function resize() { c.width = innerWidth; c.height = innerHeight; }
    resize(); addEventListener('resize', resize);
    var N = 60, nodes = [];
    for (var i = 0; i < N; i++) {
      nodes.push({ x: Math.random()*c.width, y: Math.random()*c.height,
                   vx: (Math.random()-.5)*.3, vy: (Math.random()-.5)*.3 });
    }
    function tick() {
      ctx.clearRect(0, 0, c.width, c.height);
      for (var k = 0; k < N; k++) {
        var n = nodes[k];
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > c.width) n.vx *= -1;
        if (n.y < 0 || n.y > c.height) n.vy *= -1;
      }
      ctx.strokeStyle = 'rgba(34,211,238,0.18)';
      ctx.lineWidth = 1;
      for (var i = 0; i < N; i++) {
        for (var j = i+1; j < N; j++) {
          var dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
          var d = Math.hypot(dx, dy);
          if (d < 140) {
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.globalAlpha = 1 - d / 140;
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#22d3ee';
      for (var m = 0; m < N; m++) {
        ctx.beginPath();
        ctx.arc(nodes[m].x, nodes[m].y, 1.6, 0, Math.PI*2);
        ctx.fill();
      }
      requestAnimationFrame(tick);
    }
    tick();
  }
  if (document.readyState !== 'loading') neuralCanvas();
  else document.addEventListener('DOMContentLoaded', neuralCanvas);
})();
