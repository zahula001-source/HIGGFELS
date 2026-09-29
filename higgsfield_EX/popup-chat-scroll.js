(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    const toggleBulk = document.getElementById('toggle-bulk-mode');
    const chkBulk = document.getElementById('chk-bulk-mode');
    const btnScroll = document.getElementById('btn-scroll-chat-videos');

    function syncToggles(val) {
      if (toggleBulk) toggleBulk.checked = Boolean(val);
      if (chkBulk) chkBulk.checked = Boolean(val);
    }

    // Load initial state
    try {
      chrome.storage.local.get(['brandai_bulk_mode'], res => {
        syncToggles(res?.brandai_bulk_mode);
      });
    } catch (e) {}

    async function broadcastBulkMode(enabled) {
      syncToggles(enabled);
      try {
        await chrome.storage.local.set({ brandai_bulk_mode: Boolean(enabled) });
        const tabs = await chrome.tabs.query({});
        for (const tab of tabs) {
          if (tab.id && tab.url && (tab.url.includes('dola.com') || tab.url.includes('zdola.com'))) {
            chrome.tabs.sendMessage(tab.id, { type: 'BRANDAI_SET_BULK_MODE', enabled: Boolean(enabled) }, () => {
              void chrome.runtime.lastError;
            });
          }
        }
      } catch (e) {}
    }

    if (toggleBulk) {
      toggleBulk.addEventListener('change', (e) => {
        broadcastBulkMode(e.target.checked);
      });
    }

    if (chkBulk) {
      chkBulk.addEventListener('change', (e) => {
        broadcastBulkMode(e.target.checked);
      });
    }

    if (btnScroll) {
      btnScroll.addEventListener('click', async () => {
        try {
          await broadcastBulkMode(true);
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (tab?.id) {
            chrome.tabs.sendMessage(tab.id, { type: 'BRANDAI_START_CHAT_SCROLL' }, () => {
              void chrome.runtime.lastError;
            });
            window.close();
          }
        } catch (e) {}
      });
    }
  });
})();
