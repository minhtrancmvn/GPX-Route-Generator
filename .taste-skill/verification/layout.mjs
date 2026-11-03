import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { Browser } from '/Users/coffeemug/.claude/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const browser = await Browser.launch();
const results = [];
try {
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:8000/');
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewport({ width, height: 900, mobile: width < 520 });
    for (const format of ['landscape', 'portrait']) {
      await page.eval((format) => document.querySelector(`[name="output_format"][value="${format}"]`).click(), format);
      const metrics = await page.eval(() => {
        const stage = document.querySelector('#video-stage').getBoundingClientRect();
        const empty = document.querySelector('#empty-state').getBoundingClientRect();
        const settings = document.querySelector('.controls').getBoundingClientRect();
        const preview = document.querySelector('.status-panel').getBoundingClientRect();
        return {
          width: innerWidth,
          format: document.querySelector('[name="output_format"]:checked').value,
          scrollWidth: document.documentElement.scrollWidth,
          stageRatio: stage.width / stage.height,
          emptyFits: empty.top >= stage.top && empty.bottom <= stage.bottom,
          previewFirst: preview.top < settings.top,
          targets: [...document.querySelectorAll('.split input, .advanced summary')].map(el => el.getBoundingClientRect().height),
        };
      });
      results.push(metrics);
      assert.equal(metrics.scrollWidth, width, `Horizontal overflow at ${width}px`);
      assert.ok(Math.abs(metrics.stageRatio - (format === 'portrait' ? 9 / 16 : 16 / 9)) < 0.02, `Wrong stage ratio at ${width}px: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.emptyFits, `Clipped empty state at ${width}px: ${format}`);
      if (width <= 900) assert.ok(metrics.previewFirst);
      if (width <= 520) assert.ok(metrics.targets.every(height => height >= 44));
    }
  }
  await page.setViewport({ width: 390, height: 844, mobile: true });
  await page.eval(() => {
    document.querySelector('.advanced').open = true;
    document.querySelector('#drop-zone').classList.add('has-file');
    document.querySelector('#drop-filename').textContent = 'synthetic-test-route-with-a-deliberately-long-filename-'.repeat(4) + '.gpx';
    document.querySelector('#gpx-file').focus();
  });
  const upload = await page.eval(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    focus: getComputedStyle(document.querySelector('#drop-zone')).outlineStyle,
    outlineWidth: getComputedStyle(document.querySelector('#drop-zone')).outlineWidth,
  }));
  assert.equal(upload.scrollWidth, 390);
  assert.equal(upload.focus, 'solid');
  assert.equal(upload.outlineWidth, '3px');
  results.push({ longFilenameAndUploadFocus: upload });
  await page.screenshot({ path: '.taste-skill/verification/mobile-advanced.jpg', fullPage: true });
  for (const [system, explicit, expected] of [
    ['dark', null, 'rgb(22, 24, 25)'],
    ['dark', 'light', 'rgb(237, 241, 239)'],
    ['light', 'dark', 'rgb(22, 24, 25)'],
  ]) {
    await page.send('Emulation.setEmulatedMedia', { features: [
      { name: 'prefers-color-scheme', value: system },
      { name: 'prefers-reduced-motion', value: 'reduce' },
    ] });
    await page.eval(theme => {
      if (theme) document.documentElement.dataset.theme = theme;
      else delete document.documentElement.dataset.theme;
    }, explicit);
    await page.eval(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const theme = await page.eval(() => {
      const color = selector => {
        const style = getComputedStyle(document.querySelector(selector));
        return { foreground: style.color, background: style.backgroundColor };
      };
      const luminance = rgb => rgb.match(/[\d.]+/g).slice(0, 3).map(v => {
        const n = Number(v) / 255;
        return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, v, index) => sum + v * [0.2126, 0.7152, 0.0722][index], 0);
      const contrast = (fg, bg) => {
        const pair = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
        return (pair[0] + 0.05) / (pair[1] + 0.05);
      };
      return {
        background: getComputedStyle(document.body).backgroundColor,
        buttonContrast: contrast(...Object.values(color('#render-button'))),
        downloadContrast: contrast(...Object.values(color('#download-link'))),
        labelContrast: contrast(getComputedStyle(document.querySelector('.eyebrow')).color, getComputedStyle(document.querySelector('.controls')).backgroundColor),
        reducedMotion: getComputedStyle(document.querySelector('.spinner-ring')).animationDuration,
      };
    });
    assert.equal(theme.background, expected);
    assert.ok(theme.buttonContrast >= 4.5, JSON.stringify(theme));
    assert.ok(theme.downloadContrast >= 4.5, JSON.stringify(theme));
    assert.ok(theme.labelContrast >= 4.5, JSON.stringify(theme));
    assert.ok(parseFloat(theme.reducedMotion) < 0.001);
    results.push({ system, explicit, ...theme });
  }
  await page.setViewport({ width: 1440, height: 900 });
  await page.eval(() => {
    document.querySelector('.advanced').open = false;
    document.querySelector('#drop-zone').classList.remove('has-file');
    document.querySelector('[value="landscape"]').click();
    document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: '.taste-skill/verification/desktop-dark.jpg' });
  assert.deepEqual(page.consoleErrors, []);
  console.log(JSON.stringify(results, null, 2));
} finally {
  writeFileSync('.taste-skill/verification/layout-results.json', JSON.stringify(results, null, 2) + '\n');
  await browser.close();
}
