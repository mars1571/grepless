// @map article.gif.encode: a GIF written from PNG frames with no dependency: PNG decoded, one palette for every frame, only the changed rectangle of each frame stored, LZW
import zlib from 'node:zlib';

/** {width, height, rgb} of a PNG of 8 bits per channel, RGB or RGBA, not interlaced (what a browser screenshot is). */
export function decodePNG(buf) {
  let pos = 8, width = 0, height = 0, depth = 0, type = 0;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), kind = buf.toString('ascii', pos + 4, pos + 8), data = buf.subarray(pos + 8, pos + 8 + len);
    if (kind === 'IHDR') { width = data.readUInt32BE(0); height = data.readUInt32BE(4); depth = data[8]; type = data[9]; if (data[12]) throw new Error('interlaced PNG'); }
    else if (kind === 'IDAT') idat.push(data);
    else if (kind === 'IEND') break;
    pos += 12 + len;
  }
  if (depth !== 8 || (type !== 2 && type !== 6)) throw new Error(`PNG of depth ${depth} and colour type ${type} is not supported`);
  const bpp = type === 6 ? 4 : 3, stride = width * bpp, raw = zlib.inflateSync(Buffer.concat(idat));
  const rgb = new Uint8Array(width * height * 3);
  let prev = new Uint8Array(stride), cur = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const at = y * (stride + 1), filter = raw[at];
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? cur[x - bpp] : 0, b = prev[x], c = x >= bpp ? prev[x - bpp] : 0;
      let v = raw[at + 1 + x];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      cur[x] = v & 255;
    }
    for (let x = 0, o = y * width * 3; x < width; x++) { rgb[o + x * 3] = cur[x * bpp]; rgb[o + x * 3 + 1] = cur[x * bpp + 1]; rgb[o + x * 3 + 2] = cur[x * bpp + 2]; }
    [prev, cur] = [cur, prev];
  }
  return { width, height, rgb };
}

/** 256 colours for all the frames: the most frequent ones kept exactly (the interface's flat colours), the rest by median cut. */
export function palette(frames, size = 256, exact = 96) {
  const counts = new Map();
  for (const f of frames) for (let i = 0; i < f.rgb.length; i += 3) { const k = (f.rgb[i] << 16) | (f.rgb[i + 1] << 8) | f.rgb[i + 2]; counts.set(k, (counts.get(k) || 0) + 1); }
  const all = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => [k >> 16, (k >> 8) & 255, k & 255, n]);
  if (all.length <= size) return all.map(c => c.slice(0, 3));
  const kept = all.slice(0, exact), rest = all.slice(exact);
  let boxes = [rest];
  while (boxes.length < size - exact) {
    let best = -1, bi = -1, bc = 0;
    boxes.forEach((bx, i) => {
      if (bx.length < 2) return;
      const w = bx.reduce((s, c) => s + c[3], 0);
      for (let ch = 0; ch < 3; ch++) {
        let lo = 255, hi = 0;
        for (const col of bx) { if (col[ch] < lo) lo = col[ch]; if (col[ch] > hi) hi = col[ch]; }
        const score = (hi - lo) * Math.sqrt(w);
        if (score > best) { best = score; bi = i; bc = ch; }
      }
    });
    if (bi < 0 || best <= 0) break;
    const bx = boxes[bi].sort((p, q) => p[bc] - q[bc]), total = bx.reduce((s, c) => s + c[3], 0);
    let acc = 0, cut = 1;
    for (let i = 0; i < bx.length - 1; i++) { acc += bx[i][3]; if (acc >= total / 2) { cut = i + 1; break; } }
    boxes.splice(bi, 1, bx.slice(0, cut), bx.slice(cut));
  }
  const merged = boxes.map(bx => { const w = bx.reduce((s, c) => s + c[3], 0); return [0, 1, 2].map(ch => Math.round(bx.reduce((s, col) => s + col[ch] * col[3], 0) / w)); });
  return [...kept.map(c => c.slice(0, 3)), ...merged];
}

function indexer(pal) {
  const cache = new Map();
  return (r, g, b) => {
    const k = (r << 16) | (g << 8) | b;
    let i = cache.get(k);
    if (i === undefined) {
      let best = Infinity;
      for (let j = 0; j < pal.length; j++) { const d = (pal[j][0] - r) ** 2 + (pal[j][1] - g) ** 2 + (pal[j][2] - b) ** 2; if (d < best) { best = d; i = j; } }
      cache.set(k, i);
    }
    return i;
  };
}

function lzw(indices, minCode = 8) {
  const clear = 1 << minCode, eoi = clear + 1, out = [];
  let size = minCode + 1, next = eoi + 1, acc = 0, bits = 0, dict = new Map();
  const emit = code => { acc |= code << bits; bits += size; while (bits >= 8) { out.push(acc & 255); acc >>>= 8; bits -= 8; } };
  emit(clear);
  let prefix = indices[0];
  for (let i = 1; i < indices.length; i++) {
    const k = indices[i], key = prefix * 256 + k, hit = dict.get(key);
    if (hit !== undefined) { prefix = hit; continue; }
    emit(prefix);
    if (next < 4096) { dict.set(key, next++); if (next > (1 << size) && size < 12) size++; }
    else { emit(clear); dict = new Map(); size = minCode + 1; next = eoi + 1; }
    prefix = k;
  }
  emit(prefix);
  emit(eoi);
  if (bits > 0) out.push(acc & 255);
  return Uint8Array.from(out);
}

/** frames: [{png: Buffer, delay: centiseconds}] → a looping GIF Buffer. Each frame after the first stores only what changed. */
export function encodeGIF(frames) {
  const decoded = frames.map(f => decodePNG(f.png));
  const { width, height } = decoded[0];
  const pal = palette(decoded);
  while (pal.length < 256) pal.push([0, 0, 0]);
  const index = indexer(pal);
  const parts = [];
  const header = Buffer.alloc(13);
  header.write('GIF89a', 0);
  header.writeUInt16LE(width, 6);
  header.writeUInt16LE(height, 8);
  header[10] = 0xf7;
  parts.push(header, Buffer.from(pal.flat()), Buffer.from([0x21, 0xff, 0x0b, ...Buffer.from('NETSCAPE2.0'), 0x03, 0x01, 0x00, 0x00, 0x00]));
  let previous = null;
  const stored = [];
  decoded.forEach((f, n) => {
    const idx = new Uint8Array(width * height);
    for (let i = 0, p = 0; i < idx.length; i++, p += 3) idx[i] = index(f.rgb[p], f.rgb[p + 1], f.rgb[p + 2]);
    let x0 = 0, y0 = 0, x1 = width - 1, y1 = height - 1;
    if (previous) {
      x0 = width; y0 = height; x1 = -1; y1 = -1;
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const i = y * width + x;
        if (idx[i] !== previous[i]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      }
      if (x1 < 0) { stored[stored.length - 1].delay += frames[n].delay; return; }
    }
    const w = x1 - x0 + 1, h = y1 - y0 + 1, sub = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) sub.set(idx.subarray((y0 + y) * width + x0, (y0 + y) * width + x0 + w), y * w);
    stored.push({ x: x0, y: y0, w, h, sub, delay: frames[n].delay });
    previous = idx;
  });
  for (const f of stored) {
    const delay = Math.max(2, Math.round(f.delay));
    parts.push(Buffer.from([0x21, 0xf9, 0x04, 0x04, delay & 255, (delay >> 8) & 255, 0x00, 0x00]));
    const desc = Buffer.alloc(10);
    desc[0] = 0x2c;
    desc.writeUInt16LE(f.x, 1); desc.writeUInt16LE(f.y, 3); desc.writeUInt16LE(f.w, 5); desc.writeUInt16LE(f.h, 7);
    parts.push(desc, Buffer.from([8]));
    const data = lzw(f.sub, 8);
    for (let i = 0; i < data.length; i += 255) { const chunk = data.subarray(i, i + 255); parts.push(Buffer.from([chunk.length]), Buffer.from(chunk)); }
    parts.push(Buffer.from([0]));
  }
  parts.push(Buffer.from([0x3b]));
  return { gif: Buffer.concat(parts), frames: stored.length, width, height };
}
// @end article.gif.encode
