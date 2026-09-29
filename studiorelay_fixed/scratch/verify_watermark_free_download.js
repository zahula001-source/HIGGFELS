'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

async function verifyBridge() {
  const listeners = new Map();
  const sent = [];
  const windowObject = {
    addEventListener(type, listener) {
      listeners.set(type, listener);
    }
  };
  const sandbox = {
    window: windowObject,
    location: { href: 'https://www.dola.com/chat/test' },
    console,
    chrome: {
      runtime: {
        sendMessage(message) {
          sent.push(message);
          return Promise.resolve({ ok: true });
        }
      }
    }
  };

  vm.runInNewContext(read('raw-watermark-free-downloader.js'), sandbox);
  const listener = listeners.get('DOLA_VIDEO_EXTRACTED');
  assert.equal(typeof listener, 'function');

  listener({ detail: { source: 'player', url: 'https://cdn.test/preview.mp4' } });
  listener({ detail: { source: 'fallback_api', url: 'javascript:alert(1)' } });
  assert.equal(sent.length, 0, 'preview and invalid URLs must be rejected');

  listener({
    detail: {
      source: 'fallback_api',
      url: '  https://cdn.test/raw.mp4  ',
      vid: 'video-1',
      topicTitle: 'Raw title'
    }
  });
  listener({
    detail: {
      source: 'fallback_api',
      url: 'https://cdn.test/raw-alias.mp4',
      vid: 'video-1'
    }
  });

  assert.equal(sent.length, 1, 'duplicate vid must only be forwarded once');
  assert.equal(sent[0].type, 'BRANDAI_RAW_VIDEO_DOWNLOAD');
  assert.equal(sent[0].video.url, 'https://cdn.test/raw.mp4');
  assert.equal(sent[0].video.pageUrl, sandbox.location.href);
  assert.equal(sent[0].video.prompt, 'Raw title');
}

function verifyBackgroundHandler() {
  const background = read('background.js');
  const marker = '/* Watermark-free raw master downloader.';
  const start = background.indexOf(marker);
  assert.notEqual(start, -1, 'raw background handler marker is missing');

  const legacyGuard =
    "if(_0x5d09b6&&_0x5d09b6.type!=='BRANDAI_RAW_VIDEO_DOWNLOAD')return;";
  assert.equal(background.split(legacyGuard).length - 1, 1);

  let listener;
  let failNextDownload = false;
  let nextDownloadId = 100;
  const downloads = [];
  const chrome = {
    runtime: {
      lastError: null,
      onMessage: {
        addListener(registered) {
          listener = registered;
        }
      }
    },
    downloads: {
      download(options, callback) {
        downloads.push(options);
        if (failNextDownload) {
          failNextDownload = false;
          chrome.runtime.lastError = { message: 'simulated failure' };
          callback(undefined);
          chrome.runtime.lastError = null;
          return;
        }
        callback(nextDownloadId++);
      }
    }
  };

  vm.runInNewContext(background.slice(start), {
    chrome,
    Set,
    String,
    Date: class extends Date {
      static now() {
        return 1700000000000;
      }
    }
  });
  assert.equal(typeof listener, 'function');

  const responses = [];
  const respond = response => responses.push(response);

  assert.equal(listener({ type: 'OLD_PREVIEW_DOWNLOAD' }, {}, respond), false);
  assert.equal(responses.length, 0);

  assert.equal(
    listener({
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
      video: { source: 'player', url: 'https://cdn.test/preview.mp4' }
    }, {}, respond),
    false
  );
  assert.equal(responses.at(-1).reason, 'Rejected non-original stream');
  assert.equal(downloads.length, 0);

  assert.equal(
    listener({
      type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
      video: {
        source: 'fallback_api',
        url: 'https://cdn.test/raw.mp4',
        vid: 'video-1',
        prompt: 'unsafe: title / test'
      }
    }, {}, respond),
    true
  );
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0].saveAs, false);
  assert.equal(downloads[0].conflictAction, 'uniquify');
  assert.match(
    downloads[0].filename,
    /^TheBrandAI_Videos\/unsafe__title___test_1700000000000_no_watermark\.mp4$/
  );
  assert.equal(responses.at(-1).downloaded, true);

  listener({
    type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
    video: {
      source: 'fallback_api',
      url: 'https://cdn.test/raw-alias.mp4',
      vid: 'video-1'
    }
  }, {}, respond);
  assert.equal(downloads.length, 1, 'duplicate vid must not download');
  assert.equal(responses.at(-1).reason, 'Already downloaded');

  failNextDownload = true;
  listener({
    type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
    video: {
      source: 'fallback_api',
      url: 'https://cdn.test/retry.mp4',
      vid: 'video-retry'
    }
  }, {}, respond);
  assert.equal(responses.at(-1).error, 'simulated failure');

  listener({
    type: 'BRANDAI_RAW_VIDEO_DOWNLOAD',
    video: {
      source: 'fallback_api',
      url: 'https://cdn.test/retry.mp4',
      vid: 'video-retry'
    }
  }, {}, respond);
  assert.equal(downloads.length, 3, 'failed downloads must be retryable');
  assert.equal(responses.at(-1).downloaded, true);
}

function verifyManifestAndExtractor() {
  const manifest = JSON.parse(read('manifest.json'));
  const mainScripts = manifest.content_scripts.find(group => group.world === 'MAIN');
  const isolatedScripts = manifest.content_scripts.find(group => !group.world);

  assert.deepEqual(
    mainScripts.js.slice(0, 2),
    ['without watermark/extractor.js', 'inject.js']
  );
  assert.ok(isolatedScripts.js.includes('raw-watermark-free-downloader.js'));
  assert.ok(manifest.permissions.includes('downloads'));

  const extractor = read(path.join('without watermark', 'extractor.js'));
  assert.match(extractor, /DOLA_VIDEO_EXTRACTED/);
  assert.match(extractor, /source:\s*'fallback_api'/);

  for (const group of manifest.content_scripts) {
    for (const relativePath of [...(group.js || []), ...(group.css || [])]) {
      assert.ok(
        fs.existsSync(path.join(root, relativePath)),
        'Manifest resource is missing: ' + relativePath
      );
    }
  }
}

function verifyJavaScriptSyntax() {
  for (const relativePath of [
    'background.js',
    'raw-watermark-free-downloader.js',
    path.join('without watermark', 'extractor.js')
  ]) {
    new vm.Script(read(relativePath), { filename: relativePath });
  }
}

(async () => {
  verifyJavaScriptSyntax();
  verifyManifestAndExtractor();
  await verifyBridge();
  verifyBackgroundHandler();
  console.log('Watermark-free download verification passed.');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
