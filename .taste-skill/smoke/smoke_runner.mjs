import { spawn, execSync } from 'node:child_process';
import { writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { Browser, sleep } from '/Users/coffeemug/.claude/skills/design-taste-frontend/scripts/lib/cdp.mjs';

const CANONICAL_DIR = '/Users/coffeemug/Programming/GPX Route Generator';
const SMOKE_DIR = join(CANONICAL_DIR, '.taste-skill/smoke');
const SERVER_URL = 'http://127.0.0.1:8001';
const VALID_GPX_PATH = join(SMOKE_DIR, 'valid_route.gpx');
const INVALID_GPX_PATH = join(SMOKE_DIR, 'invalid_route.gpx');

const results = {
  timestamp: new Date().toISOString(),
  server: { url: SERVER_URL, pid: null, started: false },
  steps: [],
  ffprobe: {},
  consoleErrors: [],
  networkResponses: [],
  passed: true,
  failures: []
};

function log(msg) {
  const line = `[SMOKE ${new Date().toISOString().slice(11, 19)}] ${msg}`;
  console.log(line);
}

function recordStep(name, success, details = {}) {
  log(`Step: ${name} -> ${success ? 'PASSED' : 'FAILED'}`);
  results.steps.push({ name, success, ...details });
  if (!success) {
    results.passed = false;
    results.failures.push({ step: name, details });
  }
}

function runFFprobe(filePath) {
  try {
    const stdout = execSync(
      `/opt/homebrew/bin/ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,duration,r_frame_rate -show_entries format=duration,format_name -of json "${filePath}"`,
      { encoding: 'utf8' }
    );
    return JSON.parse(stdout);
  } catch (err) {
    log(`ffprobe error on ${filePath}: ${err.message}`);
    return { error: err.message };
  }
}

async function waitForServer(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${SERVER_URL}/api/config`);
      if (res.ok) {
        const json = await res.json();
        return json;
      }
    } catch {}
    await sleep(300);
  }
  throw new Error(`Server did not start on ${SERVER_URL} within ${timeoutMs}ms`);
}

async function run() {
  let serverProc = null;
  let browser = null;
  let page = null;

  try {
    // ─── Step 0: Start FastAPI App on 127.0.0.1:8001 ───
    log('Starting FastAPI server on 127.0.0.1:8001...');
    serverProc = spawn('python3', [join(SMOKE_DIR, 'server.py')], {
      cwd: CANONICAL_DIR,
      env: { ...process.env, PYTHONPATH: join(CANONICAL_DIR, 'src') },
      stdio: 'pipe'
    });
    results.server.pid = serverProc.pid;

    let serverLogs = '';
    serverProc.stdout.on('data', d => { serverLogs += d.toString(); });
    serverProc.stderr.on('data', d => { serverLogs += d.toString(); });

    const serverConfig = await waitForServer(15000);
    results.server.started = true;
    results.server.config = serverConfig;
    recordStep('00_start_server', true, { config: serverConfig, pid: serverProc.pid });

    // ─── Step 1: Launch Chrome and Open App ───
    log('Launching browser via cdp.mjs...');
    browser = await Browser.launch({ width: 1440, height: 900 });
    page = await browser.newPage({ width: 1440, height: 900 });

    // Setup network and console tracking
    await page.send('Network.enable');
    browser.on(page.sessionId, 'Network.responseReceived', (params) => {
      const url = params.response.url;
      if (url.includes('/api/')) {
        results.networkResponses.push({
          url,
          status: params.response.status,
          statusText: params.response.statusText,
          mimeType: params.response.mimeType
        });
        log(`API Response: ${params.response.status} ${url}`);
      }
    });

    log(`Navigating to ${SERVER_URL}...`);
    const navResult = await page.goto(SERVER_URL, { timeoutMs: 15000, settleMs: 1000 });

    // Check initial UI state
    const initialDom = await page.eval(() => ({
      title: document.title,
      statusTitle: document.querySelector('#status-title')?.textContent?.trim(),
      formatBadge: document.querySelector('#format-badge')?.textContent?.trim(),
      emptyStateVisible: !document.querySelector('#empty-state')?.hidden,
      previewImageHidden: document.querySelector('#preview-image')?.hidden,
      previewVideoHidden: document.querySelector('#preview-video')?.hidden,
      renderButtonDisabled: document.querySelector('#render-button')?.disabled,
    }));

    await page.screenshot({ path: join(SMOKE_DIR, '01_initial_landing.png') });
    const initialValid = (
      initialDom.title === 'GPX Route Generator' &&
      initialDom.statusTitle === 'Ready' &&
      initialDom.formatBadge === '1280 × 720' &&
      initialDom.emptyStateVisible &&
      initialDom.previewImageHidden &&
      initialDom.previewVideoHidden
    );
    recordStep('01_initial_landing', initialValid, initialDom);

    // ─── Step 2: Invalid GPX Error and UI Recovery ───
    log('Testing invalid GPX upload and error handling...');
    await page.send('DOM.enable');
    const rootDoc1 = await page.send('DOM.getDocument');
    const fileNode1 = await page.send('DOM.querySelector', {
      nodeId: rootDoc1.root.nodeId,
      selector: '#gpx-file'
    });
    await page.send('DOM.setFileInputFiles', {
      nodeId: fileNode1.nodeId,
      files: [INVALID_GPX_PATH]
    });
    await page.eval(() => {
      document.querySelector('#gpx-file').dispatchEvent(new Event('change', { bubbles: true }));
    });

    // Wait for error message to show up
    let invalidErrorHandled = false;
    let errorMessageText = '';
    for (let i = 0; i < 30; i++) {
      await sleep(200);
      const state = await page.eval(() => ({
        msg: document.querySelector('#message')?.textContent?.trim(),
        hasErrorClass: document.querySelector('#message')?.classList.contains('error'),
        emptyVisible: !document.querySelector('#empty-state')?.hidden,
        imgHidden: document.querySelector('#preview-image')?.hidden,
      }));
      if (state.hasErrorClass && state.msg.length > 0) {
        invalidErrorHandled = true;
        errorMessageText = state.msg;
        break;
      }
    }
    await page.screenshot({ path: join(SMOKE_DIR, '02_invalid_gpx_error.png') });
    recordStep('02_invalid_gpx_error', invalidErrorHandled, { errorMessage: errorMessageText });

    // ─── Step 3: Valid GPX Upload and Landscape Preview ───
    log('Uploading valid GPX and waiting for /api/preview PNG...');
    const rootDoc2 = await page.send('DOM.getDocument');
    const fileNode2 = await page.send('DOM.querySelector', {
      nodeId: rootDoc2.root.nodeId,
      selector: '#gpx-file'
    });
    await page.send('DOM.setFileInputFiles', {
      nodeId: fileNode2.nodeId,
      files: [VALID_GPX_PATH]
    });
    await page.eval(() => {
      document.querySelector('#gpx-file').dispatchEvent(new Event('change', { bubbles: true }));
    });

    // Wait for preview image to load and display
    let landscapePreviewReady = false;
    let previewSrc = '';
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      const pState = await page.eval(() => ({
        imgHidden: document.querySelector('#preview-image')?.hidden,
        imgSrc: document.querySelector('#preview-image')?.src || '',
        emptyHidden: document.querySelector('#empty-state')?.hidden,
        messageText: document.querySelector('#message')?.textContent?.trim(),
        errorClass: document.querySelector('#message')?.classList.contains('error'),
      }));
      if (!pState.imgHidden && pState.imgSrc.startsWith('blob:') && pState.emptyHidden && !pState.errorClass) {
        landscapePreviewReady = true;
        previewSrc = pState.imgSrc;
        break;
      }
    }

    await page.screenshot({ path: join(SMOKE_DIR, '03_valid_preview_landscape.png') });

    // Download the preview image blob from page
    if (landscapePreviewReady) {
      const b64Data = await page.eval(async () => {
        const img = document.querySelector('#preview-image');
        const res = await fetch(img.src);
        const buf = await res.arrayBuffer();
        let binary = '';
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
        return btoa(binary);
      });
      const previewImgPath = join(SMOKE_DIR, 'preview_landscape.png');
      writeFileSync(previewImgPath, Buffer.from(b64Data, 'base64'));
      const ffInfo = runFFprobe(previewImgPath);
      results.ffprobe.preview_landscape = ffInfo;
      const width = ffInfo.streams?.[0]?.width;
      const height = ffInfo.streams?.[0]?.height;
      const validDimensions = (width === 1280 && height === 720);
      recordStep('03_landscape_preview', landscapePreviewReady && validDimensions, {
        previewSrc,
        width,
        height,
        codec: ffInfo.streams?.[0]?.codec_name
      });
    } else {
      recordStep('03_landscape_preview', false, { error: 'Preview image blob did not render' });
    }

    // ─── Step 4: Switch Format to Portrait ───
    log('Switching format to Portrait (720x1280)...');
    const oldLandscapeBlobSrc = previewSrc;
    await page.eval(() => {
      const radio = document.querySelector('input[name="output_format"][value="portrait"]');
      radio.click();
    });

    let portraitPreviewReady = false;
    let portraitBadgeOk = false;
    let newPortraitSrc = '';
    for (let i = 0; i < 50; i++) {
      await sleep(250);
      const portState = await page.eval(() => ({
        badgeText: document.querySelector('#format-badge')?.textContent?.trim(),
        isPortraitStage: document.querySelector('#video-stage')?.classList.contains('portrait'),
        imgSrc: document.querySelector('#preview-image')?.src || '',
        isLoading: document.querySelector('#video-stage')?.classList.contains('preview-loading'),
      }));
      if (
        portState.badgeText === '720 × 1280' &&
        portState.isPortraitStage &&
        portState.imgSrc.startsWith('blob:') &&
        portState.imgSrc !== oldLandscapeBlobSrc &&
        !portState.isLoading
      ) {
        portraitBadgeOk = true;
        portraitPreviewReady = true;
        newPortraitSrc = portState.imgSrc;
        break;
      }
    }

    await page.screenshot({ path: join(SMOKE_DIR, '04_portrait_preview.png') });

    // Download portrait preview image blob
    const portraitImgPath = join(SMOKE_DIR, 'preview_portrait.png');
    const portraitB64 = await page.eval(async () => {
      const img = document.querySelector('#preview-image');
      const res = await fetch(img.src);
      const buf = await res.arrayBuffer();
      let binary = '';
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
      return btoa(binary);
    });
    writeFileSync(portraitImgPath, Buffer.from(portraitB64, 'base64'));
    const ffPortraitPreview = runFFprobe(portraitImgPath);
    results.ffprobe.preview_portrait = ffPortraitPreview;
    const pWidth = ffPortraitPreview.streams?.[0]?.width;
    const pHeight = ffPortraitPreview.streams?.[0]?.height;
    const portraitDimOk = (pWidth === 720 && pHeight === 1280);
    recordStep('04_portrait_format_switch', portraitBadgeOk && portraitDimOk, {
      width: pWidth,
      height: pHeight,
      codec: ffPortraitPreview.streams?.[0]?.codec_name
    });

    // ─── Step 5: Advanced Controls & Customization ───
    log('Testing Advanced Settings accordion and controls...');
    await page.eval(() => {
      const details = document.querySelector('details.advanced');
      details.open = true;

      // Adjust trail color to cyan and width to 10
      const trailColor = document.querySelector('input[name="trail_color"]');
      trailColor.value = '#00e5ff';
      trailColor.dispatchEvent(new Event('input', { bubbles: true }));

      const trailWidth = document.querySelector('#trail-width');
      trailWidth.value = '10';
      trailWidth.dispatchEvent(new Event('input', { bubbles: true }));

      // Select MT-15 avatar and size 60
      const avatarSelect = document.querySelector('#avatar-select');
      avatarSelect.value = 'mt15';
      avatarSelect.dispatchEvent(new Event('change', { bubbles: true }));

      const avatarSize = document.querySelector('#avatar-size');
      avatarSize.value = '60';
      avatarSize.dispatchEvent(new Event('input', { bubbles: true }));
    });

    await sleep(600);
    const advState = await page.eval(() => ({
      trailPreviewHeight: document.querySelector('#trail-preview-line')?.style.height,
      avatarPreviewSrc: document.querySelector('#avatar-preview')?.src,
      detailsOpen: document.querySelector('details.advanced')?.open,
    }));
    await page.screenshot({ path: join(SMOKE_DIR, '05_advanced_settings.png') });
    const advOk = (
      advState.detailsOpen &&
      advState.trailPreviewHeight === '10px' &&
      advState.avatarPreviewSrc?.includes('mt15')
    );
    recordStep('05_advanced_settings', advOk, advState);

    // ─── Step 6: Render Portrait Video & Job Polling ───
    log('Submitting portrait render job (duration: 5s, fps: 6 -> 30 frames)...');
    await page.eval(() => {
      const durationInput = document.querySelector('#duration');
      durationInput.value = '5';
      durationInput.dispatchEvent(new Event('input', { bubbles: true }));

      const fpsInput = document.querySelector('#fps');
      fpsInput.value = '6';
      fpsInput.dispatchEvent(new Event('input', { bubbles: true }));
    });

    // Click render button
    await page.eval(() => {
      document.querySelector('#render-button').click();
    });

    // Poll job progress and capture aria-valuenow transitions
    log('Monitoring render job polling and progress bar...');
    const progressHistory = [];
    let jobCompleted = false;
    let renderDetails = {};

    for (let i = 0; i < 60; i++) {
      await sleep(500);
      const pollState = await page.eval(() => {
        const pBar = document.querySelector('.progress-bar');
        return {
          statusTitle: document.querySelector('#status-title')?.textContent?.trim(),
          ariaValuenow: pBar?.getAttribute('aria-valuenow'),
          progressFillWidth: document.querySelector('#progress-fill')?.style?.width,
          progressLabel: document.querySelector('#progress-label')?.textContent?.trim(),
          requestLabel: document.querySelector('#request-label')?.textContent?.trim(),
          message: document.querySelector('#message')?.textContent?.trim(),
          spinnerLabel: document.querySelector('#spinner-label')?.textContent?.trim(),
          videoHidden: document.querySelector('#preview-video')?.hidden,
          videoSrc: document.querySelector('#preview-video')?.getAttribute('src') || document.querySelector('#preview-video')?.src,
          downloadHidden: document.querySelector('#download-link')?.hidden,
          downloadHref: document.querySelector('#download-link')?.getAttribute('href'),
          buttonDisabled: document.querySelector('#render-button')?.disabled,
        };
      });

      progressHistory.push({
        elapsedMs: i * 500,
        status: pollState.statusTitle,
        valuenow: pollState.ariaValuenow,
        label: pollState.progressLabel,
        msg: pollState.message
      });

      if (pollState.statusTitle === 'Completed' && !pollState.videoHidden && !pollState.downloadHidden) {
        jobCompleted = true;
        renderDetails = pollState;
        break;
      }
      if (pollState.statusTitle === 'Failed' || (pollState.message && pollState.message.includes('failed'))) {
        throw new Error(`Render failed: ${pollState.message}`);
      }
    }

    await page.screenshot({ path: join(SMOKE_DIR, '06_render_portrait_completed.png') });
    recordStep('06_render_portrait_job', jobCompleted, {
      renderDetails,
      progressHistorySample: progressHistory.filter((_, idx) => idx % 2 === 0)
    });

    // ─── Step 7: Video Playback & Download Verification (Portrait) ───
    log('Verifying video element playback and downloading portrait MP4...');
    const playResult = await page.eval(async () => {
      const v = document.querySelector('#preview-video');
      try {
        v.muted = true;
        await v.play();
        return { playing: !v.paused, currentTime: v.currentTime, duration: v.duration };
      } catch (err) {
        return { error: err.message };
      }
    });

    const videoUrl = `${SERVER_URL}${renderDetails.downloadHref}`;
    log(`Downloading portrait MP4 from ${videoUrl}...`);
    const vidRes = await fetch(videoUrl);
    const vidBuffer = Buffer.from(await vidRes.arrayBuffer());
    const portraitMp4Path = join(SMOKE_DIR, 'rendered_portrait.mp4');
    writeFileSync(portraitMp4Path, vidBuffer);

    const ffPortraitMp4 = runFFprobe(portraitMp4Path);
    results.ffprobe.video_portrait = ffPortraitMp4;
    const vWidth = ffPortraitMp4.streams?.[0]?.width;
    const vHeight = ffPortraitMp4.streams?.[0]?.height;
    const vDuration = parseFloat(ffPortraitMp4.format?.duration || ffPortraitMp4.streams?.[0]?.duration || '0');
    const vCodec = ffPortraitMp4.streams?.[0]?.codec_name;
    const portraitVideoValid = (
      vidRes.status === 200 &&
      vWidth === 720 &&
      vHeight === 1280 &&
      Math.abs(vDuration - 5.0) < 0.5 &&
      vCodec === 'h264'
    );
    recordStep('07_portrait_video_playback_and_download', portraitVideoValid, {
      httpStatus: vidRes.status,
      fileBytes: vidBuffer.length,
      width: vWidth,
      height: vHeight,
      duration: vDuration,
      codec: vCodec,
      playback: playResult
    });

    // ─── Step 8: Render Landscape Video (Exercise Both Formats) ───
    log('Switching back to Landscape and executing second render...');
    await page.eval(() => {
      const radio = document.querySelector('input[name="output_format"][value="landscape"]');
      radio.click();
    });
    await sleep(800);

    // Click render button for landscape
    await page.eval(() => {
      document.querySelector('#render-button').click();
    });

    let landscapeJobCompleted = false;
    let landscapeRenderDetails = {};
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      const pollState = await page.eval(() => ({
        statusTitle: document.querySelector('#status-title')?.textContent?.trim(),
        ariaValuenow: document.querySelector('.progress-bar')?.getAttribute('aria-valuenow'),
        videoHidden: document.querySelector('#preview-video')?.hidden,
        downloadHidden: document.querySelector('#download-link')?.hidden,
        downloadHref: document.querySelector('#download-link')?.getAttribute('href'),
        message: document.querySelector('#message')?.textContent?.trim(),
      }));

      if (pollState.statusTitle === 'Completed' && !pollState.videoHidden && !pollState.downloadHidden) {
        landscapeJobCompleted = true;
        landscapeRenderDetails = pollState;
        break;
      }
      if (pollState.statusTitle === 'Failed') {
        throw new Error(`Landscape render failed: ${pollState.message}`);
      }
    }

    await page.screenshot({ path: join(SMOKE_DIR, '07_render_landscape_completed.png') });

    // Download landscape MP4
    const landVideoUrl = `${SERVER_URL}${landscapeRenderDetails.downloadHref}`;
    const landRes = await fetch(landVideoUrl);
    const landBuffer = Buffer.from(await landRes.arrayBuffer());
    const landscapeMp4Path = join(SMOKE_DIR, 'rendered_landscape.mp4');
    writeFileSync(landscapeMp4Path, landBuffer);

    const ffLandscapeMp4 = runFFprobe(landscapeMp4Path);
    results.ffprobe.video_landscape = ffLandscapeMp4;
    const lWidth = ffLandscapeMp4.streams?.[0]?.width;
    const lHeight = ffLandscapeMp4.streams?.[0]?.height;
    const lDuration = parseFloat(ffLandscapeMp4.format?.duration || ffLandscapeMp4.streams?.[0]?.duration || '0');
    const lCodec = ffLandscapeMp4.streams?.[0]?.codec_name;
    const landscapeVideoValid = (
      landRes.status === 200 &&
      lWidth === 1280 &&
      lHeight === 720 &&
      Math.abs(lDuration - 5.0) < 0.5 &&
      lCodec === 'h264'
    );
    recordStep('08_landscape_video_render_and_download', landscapeVideoValid, {
      httpStatus: landRes.status,
      fileBytes: landBuffer.length,
      width: lWidth,
      height: lHeight,
      duration: lDuration,
      codec: lCodec
    });

    // ─── Step 9: Collect Console Errors ───
    results.consoleErrors = page.consoleErrors || [];
    log(`Collected ${results.consoleErrors.length} console errors during session`);

  } catch (err) {
    log(`FATAL ERROR during smoke run: ${err.message}\n${err.stack}`);
    recordStep('fatal_error', false, { error: err.message, stack: err.stack });
  } finally {
    // ─── Clean up resources ───
    log('Cleaning up browser and server processes...');
    if (page) {
      try { await page.close(); } catch {}
    }
    if (browser) {
      try { await browser.close(); } catch {}
    }
    if (serverProc) {
      try {
        serverProc.kill('SIGTERM');
        await sleep(300);
        if (!serverProc.killed) serverProc.kill('SIGKILL');
      } catch {}
    }

    // Save full JSON results
    writeFileSync(join(SMOKE_DIR, 'smoke_results.json'), JSON.stringify(results, null, 2));
    log(`Smoke test finished. Status: ${results.passed ? 'ALL PASSED' : 'SOME FAILED'}`);
    log(`Results saved to ${join(SMOKE_DIR, 'smoke_results.json')}`);
  }
}

run();
