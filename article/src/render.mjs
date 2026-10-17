// @map article.render.pages: every figure page rendered with Chrome: a PNG at twice its size for each figure, the preview cards at their own size, a GIF for each scene
// Usage: node article/src/render.mjs [folder holding node_modules/playwright] [--only name]
// Playwright comes from node_modules next to this repository, or from the folder given (npm i -D playwright).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { encodeGIF } from './gif.mjs';

const here = path.dirname(new URL(import.meta.url).pathname);
const args = process.argv.slice(2);
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;
const where = args.find(a => !a.startsWith('--') && a !== only) || path.join(here, '..', '..');
const { chromium } = createRequire(path.join(where, 'package.json'))('playwright');
const pages = path.join(here, 'html'), out = path.join(here, '..', 'images');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
for (const file of fs.readdirSync(pages).filter(f => f.endsWith('.html')).sort()) {
  const name = file.replace(/\.html$/, '');
  if (only && !name.startsWith(only)) continue;
  const scene = name.endsWith('.scene');
  const card = ['og-image', 'social-preview', 'devto-cover'].includes(name);   // preview cards at their exact size
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: card ? 1 : 2 });
  await page.goto('file://' + path.join(pages, file));
  await page.evaluate(() => document.fonts.ready);
  const fig = page.locator('#fig');
  if (!scene) {
    const target = path.join(out, name + '.png');
    await fig.screenshot({ path: target });
    const box = await fig.boundingBox(), k = card ? 1 : 2;
    console.log(`${name}.png  ${Math.round(box.width * k)}×${Math.round(box.height * k)}, ${(fs.statSync(target).size / 1024).toFixed(0)} KB`);
  } else {
    const duration = await page.evaluate(() => window.scene.duration);
    const frames = [];
    let last = null;
    for (let t = 0; t <= duration + 1e-6; t += 1 / 15) {
      const key = await page.evaluate(x => window.scene.render(x), t);
      if (key === last) { frames[frames.length - 1].delay += 100 / 15; continue; }
      last = key;
      frames.push({ png: await fig.screenshot(), delay: 100 / 15 });
    }
    const { gif, frames: n, width, height } = encodeGIF(frames);
    const target = path.join(out, name.replace(/\.scene$/, '') + '.gif');
    fs.writeFileSync(target, gif);
    console.log(`${path.basename(target)}  ${width}×${height}, ${n} frames, ${(gif.length / 1024).toFixed(0)} KB`);
  }
  await page.close();
}
await browser.close();
// @end article.render.pages
