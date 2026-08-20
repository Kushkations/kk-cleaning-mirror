#!/usr/bin/env node
/* Draws the Mozart Properties mark into public/icon.png (192x192).
 *
 * The icon is generated instead of shipped as a binary so that a deploy is a
 * pure-text payload: every deployed file can then be checked byte for byte
 * against this repo. Pure Node - zlib and nothing else. */

const zlib = require('zlib');
const fs = require('fs');
const path = require('path');

const SIZE = 192;
const SS = 3;                 // supersampling factor, for smooth edges
const BG = [255, 255, 255];

/* ---- the mark, in the same 0..100 coordinate space as the header logo ---- */
const rgb = h => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

function cubic(p0, p1, p2, p3, steps) {
  const out = [];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps, u = 1 - t;
    out.push([
      u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
      u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
    ]);
  }
  return out;
}
function quad(p0, p1, p2, steps) {
  const out = [];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps, u = 1 - t;
    out.push([
      u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
      u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
    ]);
  }
  return out;
}
const bar = (x1, y1, x2, y2, x3, y3, x4, y4) => [[x1, y1], [x2, y2], [x3, y3], [x4, y4]];

const swoosh = [[6, 34]]
  .concat(cubic([6, 34], [0, 66], [20, 96], [52, 96], 24))
  .concat(cubic([52, 96], [78, 96], [93, 85], [99, 70], 24))
  .concat(cubic([99, 70], [90, 81], [74, 88], [52, 88], 24))
  .concat(cubic([52, 88], [26, 88], [10, 64], [18, 36], 24));

const roofed = [[68, 92], [68, 50]]
  .concat(quad([68, 50], [68, 41], [77, 41], 12))
  .concat([[91, 41], [91, 92]]);

/* painter's order: back to front, exactly as the SVG stacks them */
const SHAPES = [
  { pts: bar(14, 92, 14, 58, 30, 49, 30, 92), fill: rgb('#33B0E4') },
  { pts: bar(28, 45, 46, 32, 46, 92, 28, 92), fill: rgb('#A6A8AB') },
  { pts: bar(48, 28, 66, 13, 66, 92, 48, 92), fill: rgb('#189BD7') },
  { pts: roofed, fill: rgb('#A6A8AB') },
  { pts: bar(72.1, 49, 73.9, 49, 73.9, 90, 72.1, 90), fill: rgb('#7E8184') },
  { pts: bar(78.1, 45, 79.9, 45, 79.9, 90, 78.1, 90), fill: rgb('#7E8184') },
  { pts: bar(84.1, 44, 85.9, 44, 85.9, 90, 84.1, 90), fill: rgb('#7E8184') },
  { pts: swoosh, fill: rgb('#189BD7') }
];

function inside(pts, x, y) {           // even-odd fill rule
  let hit = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

/* the mark lives in x 0..100, y 8..100 - fit it into the square with a margin */
const PAD = 10;
const span = 100 - PAD * 2;
const toUser = p => ({ x: ((p + 0.5) / (SIZE * SS)) * (100 + PAD * 2) - PAD, });

function render() {
  const px = Buffer.alloc(SIZE * SIZE * 3);
  const scale = (100 + 8) / SIZE;       // user units per device pixel
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      let r = 0, g = 0, b = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const ux = (x + (sx + 0.5) / SS) * scale - 4;
          const uy = (y + (sy + 0.5) / SS) * scale + 4;
          let c = BG;
          for (const s of SHAPES) if (inside(s.pts, ux, uy)) c = s.fill;
          r += c[0]; g += c[1]; b += c[2];
        }
      }
      const n = SS * SS, i = (y * SIZE + x) * 3;
      px[i] = Math.round(r / n); px[i + 1] = Math.round(g / n); px[i + 2] = Math.round(b / n);
    }
  }
  return px;
}

/* ---- minimal PNG writer ---- */
const CRC = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return buf => {
    let c = -1;
    for (const b of buf) c = t[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ -1) >>> 0;
  };
})();

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(CRC(body));
  return Buffer.concat([len, body, crc]);
}

function png(pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(SIZE, 0);
  ihdr.writeUInt32BE(SIZE, 4);
  ihdr[8] = 8;    // bit depth
  ihdr[9] = 2;    // truecolour
  const raw = Buffer.alloc(SIZE * (SIZE * 3 + 1));
  for (let y = 0; y < SIZE; y++) {
    raw[y * (SIZE * 3 + 1)] = 0;   // filter: none
    pixels.copy(raw, y * (SIZE * 3 + 1) + 1, y * SIZE * 3, (y + 1) * SIZE * 3);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0))
  ]);
}

const out = process.argv[2] || path.join(__dirname, 'public', 'icon.png');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, png(render()));
console.log('wrote ' + out + ' (' + fs.statSync(out).size + ' bytes)');
