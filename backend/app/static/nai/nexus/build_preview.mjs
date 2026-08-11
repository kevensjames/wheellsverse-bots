import fs from 'fs';
const rd = p => fs.readFileSync(p, 'utf8');
const html = rd('index.html');
const css = rd('css/tokens.css') + '\n' + rd('css/nexus.css');
const js = rd('/tmp/nexus.bundle.js');
// inline the KAI portrait as a data URI so the single-file build has no external assets
const kaiB64 = fs.readFileSync('assets/kai.jpg').toString('base64');
const bodyInner = html.split('<body>')[1].split('</body>')[0]
  .replace(/<script type="module" src="js\/app\.js"><\/script>/, '')
  .replace(/src="assets\/kai\.jpg"/, `src="data:image/jpeg;base64,${kaiB64}"`);

// (a) standalone self-contained file (keeps <html data-*> for the repo demo)
const standalone =
`<!DOCTYPE html>
<html lang="en" data-kai="idle" data-q="high">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#04060d"><title>KAI · Command Nexus</title>
<style>${css}</style></head>
<body>${bodyInner}<script type="module">${js}</script></body></html>`;
fs.writeFileSync('nexus.preview.html', standalone);

// (b) artifact-format (no doctype/html/head/body skeleton; wrapper adds it)
const artifact =
`<title>KAI · Command Nexus</title>
<style>${css}</style>
${bodyInner}
<script type="module">${js}</script>`;
fs.writeFileSync('/tmp/nexus.artifact.html', artifact);

console.log('standalone', (fs.statSync('nexus.preview.html').size/1024).toFixed(1)+'kb',
            '| artifact', (fs.statSync('/tmp/nexus.artifact.html').size/1024).toFixed(1)+'kb');
