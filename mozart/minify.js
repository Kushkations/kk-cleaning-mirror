// Minify the deployable copy: node minify.js  (run by build.py when available)
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { minify } = require('terser');
const CleanCSS = require('clean-css');

const SRC = path.join(__dirname, 'index.html');
const OUT = path.join(__dirname, 'dist', 'index.html');

(async () => {
  const src = fs.readFileSync(SRC, 'utf8');
  const [head, r1] = split(src, '<style>');
  const [css, r2] = split(r1, '</style>');
  const [body, r3] = split(r2, '<script>');
  const [js, tail] = split(r3, '</script>');

  const cssOut = new CleanCSS({ level: 2 }).minify(css).styles;
  const res = await minify(js, {
    ecma: 2020,
    compress: { passes: 2 },
    mangle: { toplevel: false },   // App/data/helpers are referenced from inline onclick handlers
    format: { comments: false }
  });
  if (res.error) throw res.error;

  const bodyOut = body.split('\n').map(l => l.trim()).filter(Boolean).join('\n');
  const out = head + '<style>' + cssOut + '</style>' + bodyOut + '<script>' + res.code + '</script>' + tail;
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, out);
  // the rest of the deployed bundle: data, manifest, and the generated icon
  const dist = path.dirname(OUT);
  fs.writeFileSync(path.join(dist, 'seed.json'),
    JSON.stringify(JSON.parse(fs.readFileSync(path.join(__dirname, 'seed.json'), 'utf8'))));
  fs.copyFileSync(path.join(__dirname, 'manifest.json'), path.join(dist, 'manifest.json'));
  execFileSync(process.execPath, [path.join(__dirname, 'make-icon.js'), path.join(dist, 'icon.png')],
    { stdio: 'inherit' });

  console.log('source :', Buffer.byteLength(src), 'bytes');
  console.log('minified:', Buffer.byteLength(out), 'bytes');
  for (const f of fs.readdirSync(dist).sort()) console.log('  ' + f, fs.statSync(path.join(dist, f)).size);

  function split(s, m) { const i = s.indexOf(m); return [s.slice(0, i), s.slice(i + m.length)]; }
})();
