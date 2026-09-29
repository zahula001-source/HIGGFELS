(() => {
    'use strict';

    const DB_NAME = 'studio-relay-image-queue';
    const DB_VERSION = 1;
    const STORE_NAME = 'images';
    const SUMMARY_STORAGE_KEY = 'studio_relay_image_overlay_summary';
    const GET_SUMMARY_ACTION = 'studioRelayGetImageQueueSummary';
    const UPLOAD_ACTION = 'studioRelayUploadImageFromOverlay';
    const GET_DRAGGED_IMAGE_ACTION = 'studioRelayGetDraggedImagePayload';
    const MANUAL_ATTACHMENT_ACTION = 'studioRelayManualImageAttached';
    const MANUAL_ATTACHMENT_FAILURE_ACTION = 'studioRelayManualImageFailed';
    const CONTENT_UPLOAD_ACTION = 'studioRelayUploadImage';
    const SUPPORTED_TAB_PATTERNS = [
        '*://*.dola.com/*',
        '*://dola.com/*',
        '*://*.seaart.ai/*',
        '*://seaart.ai/*'
    ];

    let databasePromise;
    let activeUpload = null;

    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        if (message?.action === GET_SUMMARY_ACTION) {
            readAndPublishSummary()
                .then(summary => sendResponse({success: true, summary}))
                .catch(error => sendResponse({success: false, error: friendlyError(error)}));
            return true;
        }

        if (message?.action === GET_DRAGGED_IMAGE_ACTION) {
            getDraggedImagePayload(message, sender)
                .then(sendResponse)
                .catch(error => sendResponse({success: false, error: friendlyError(error)}));
            return true;
        }
        if (message?.action === MANUAL_ATTACHMENT_FAILURE_ACTION) {
            handleManualAttachmentFailure(message, sender)
                .then(sendResponse)
                .catch(error => sendResponse({success: false, error: friendlyError(error)}));
            return true;
        }
        if (message?.action === MANUAL_ATTACHMENT_ACTION) {
            handleManualAttachment(message, sender)
                .then(sendResponse)
                .catch(error => sendResponse({success: false, error: friendlyError(error)}));
            return true;
        }

        if (message?.action !== UPLOAD_ACTION) return undefined;
        if (activeUpload) {
            sendResponse({success: false, error: 'Another image upload is already in progress.'});
            return false;
        }

        activeUpload = handleUploadRequest(message, sender)
            .then(sendResponse)
            .catch(error => sendResponse({success: false, error: friendlyError(error)}))
            .finally(() => {
                activeUpload = null;
            });
        return true;
    });

    async function getDraggedImagePayload(message, sender) {
        if (!sender.tab?.id) throw new Error('The target Dola tab could not be identified.');
        const recordId = String(message.imageId || '');
        const operationId = String(message.operationId || '').trim();
        if (!/^[a-zA-Z0-9_-]{12,160}$/.test(operationId)) {
            throw new Error('The gallery drag operation is invalid or expired.');
        }
        const records = await getAllRecords();
        const record = records.find(image => String(image.id) === recordId);
        if (!record || !(record.blob instanceof Blob)) {
            throw new Error('The dragged image is no longer available in the gallery.');
        }

        return {
            success: true,
            image: {
                name: record.name,
                type: record.type || record.blob.type || 'image/png',
                size: record.size,
                lastModified: record.lastModified,
                dataUrl: await blobToDataUrl(record.blob, record.type)
            }
        };
    }
    async function handleManualAttachmentFailure(message, sender) {
        if (!sender.tab?.id) throw new Error('The target Dola tab could not be identified.');
        const details = message.image || {};
        const recordId = String(details.id || '');
        if (!recordId) return {success: true, ignored: true};

        const records = await getVerifiedRecords();
        const record = records.find(image => String(image.id) === recordId);
        if (!record) return {success: false, error: 'The dragged image is no longer in the gallery.'};

        record.status = 'queued';
        record.error = friendlyError(new Error(details.error || 'Dola did not accept the dragged image.'));
        record.uploadedAt = null;
        record.attachmentVerifiedAt = null;
        record.attachmentEvidence = '';
        await putRecord(record);
        const summary = await publishSummary(records, {
            id: String(record.id),
            name: String(record.name || 'Image'),
            status: 'error',
            error: record.error
        });
        return {success: true, summary};
    }
    async function handleManualAttachment(message, sender) {
        if (!sender.tab?.id || message?.image?.verified !== true) {
            throw new Error('The manual image attachment could not be verified.');
        }

        const details = message.image;
        const recordId = String(details.id || '');
        if (!recordId) return {success: true, ignored: true};

        const records = await getVerifiedRecords();
        const record = records.find(image => String(image.id) === recordId);
        if (!record) return {success: false, error: 'The dragged image is no longer in the gallery.'};

        const verifiedAt = Date.now();
        record.status = 'done';
        record.error = '';
        record.uploadedAt = verifiedAt;
        record.attachmentVerifiedAt = verifiedAt;
        record.attachmentEvidence = 'manual-' + String(details.method || 'drop') + '-' + String(details.evidence || 'composer-ui-evidence');
        await putRecord(record);
        const summary = await publishSummary(records, {
            id: String(record.id),
            name: String(record.name || 'Image'),
            status: 'done',
            evidence: record.attachmentEvidence
        });
        return {success: true, summary};
    }
    async function handleUploadRequest(message, sender) {
        const records = await getVerifiedRecords();
        records.sort(sortByOrder);

        if (message.mode === 'all') return uploadAllTabs(records);
        return uploadCurrentTab(records, String(message.imageId || ''), sender.tab?.id);
    }

    async function uploadCurrentTab(records, imageId, tabId) {
        if (!tabId) throw new Error('The current Dola tab could not be identified.');
        const record = records.find(image => String(image.id) === imageId);
        if (!record) throw new Error('That image is no longer in the queue.');

        try {
            const uploadResult = await sendImageToTab(tabId, record);
            const verifiedAt = Date.now();
            record.status = 'done';
            record.error = '';
            record.uploadedAt = verifiedAt;
            record.attachmentVerifiedAt = verifiedAt;
            record.attachmentEvidence = String(uploadResult.evidence || 'composer-ui-evidence');
            await putRecord(record);

            const summary = await publishSummary(records);
            return {
                success: true,
                summary,
                message: `${record.name} verified and attached to this tab.`
            };
        } catch (error) {
            record.status = 'queued';
            record.error = friendlyError(error);
            record.uploadedAt = null;
            record.attachmentVerifiedAt = null;
            record.attachmentEvidence = '';
            await putRecord(record);
            const summary = await publishSummary(records);
            return {
                success: false,
                summary,
                error: record.error
            };
        }
    }

    async function uploadAllTabs(records) {
        const queued = records.filter(image => image.status !== 'done');
        if (!queued.length) throw new Error('No queued images are available.');

        const tabs = (await queryTabs({url: SUPPORTED_TAB_PATTERNS}))
            .filter(tab => tab.id)
            .sort((left, right) => (left.windowId - right.windowId) || (left.index - right.index));
        if (!tabs.length) throw new Error('No open Dola or SeaArt tabs were found.');

        const pairCount = Math.min(queued.length, tabs.length);
        let successCount = 0;
        let failureCount = 0;

        for (let index = 0; index < pairCount; index += 1) {
            const record = queued[index];
            try {
                const uploadResult = await sendImageToTab(tabs[index].id, record);
                const verifiedAt = Date.now();
                record.status = 'done';
                record.error = '';
                record.uploadedAt = verifiedAt;
                record.attachmentVerifiedAt = verifiedAt;
                record.attachmentEvidence = String(uploadResult.evidence || 'composer-ui-evidence');
                successCount += 1;
            } catch (error) {
                record.status = 'queued';
                record.error = friendlyError(error);
                record.uploadedAt = null;
                record.attachmentVerifiedAt = null;
                record.attachmentEvidence = '';
                failureCount += 1;
            }
            await putRecord(record);
            await publishSummary(records);
        }

        const unmatched = queued.length - pairCount;
        const summary = await publishSummary(records);
        const parts = [`${successCount} image(s) uploaded`];
        if (failureCount) parts.push(`${failureCount} failed`);
        if (unmatched > 0) parts.push(`${unmatched} left queued`);

        return {
            success: successCount > 0 || failureCount === 0,
            summary,
            message: `${parts.join(', ')}.`
        };
    }

    async function readAndPublishSummary() {
        const records = await getVerifiedRecords();
        records.sort(sortByOrder);
        return publishSummary(records);
    }

    async function publishSummary(records, manualDrop = null) {
        const summary = buildSummary(records, 'background');
        if (manualDrop) summary.manualDrop = manualDrop;
        await setStorage({[SUMMARY_STORAGE_KEY]: summary});
        return summary;
    }

    function buildSummary(records, source) {
        const doneRecords = records
            .filter(image => image.status === 'done' && image.uploadedAt)
            .sort((left, right) => Number(right.uploadedAt) - Number(left.uploadedAt));
        const done = records.filter(image => image.status === 'done').length;

        return {
            total: records.length,
            queued: records.length - done,
            done,
            lastUploadedName: doneRecords[0]?.name || '',
            images: records.map(image => ({
                id: String(image.id),
                name: String(image.name || 'Untitled image'),
                status: image.status === 'done' ? 'done' : 'queued',
                order: Number(image.order) || 0,
                size: Number(image.size) || 0,
                error: String(image.error || '')
            })),
            source,
            updatedAt: Date.now()
        };
    }

    async function sendImageToTab(tabId, record) {
        const dataUrl = await blobToDataUrl(record.blob, record.type);
        const response = await sendTabMessage(tabId, {
            action: CONTENT_UPLOAD_ACTION,
            image: {
                name: record.name,
                type: record.type,
                size: record.size,
                lastModified: record.lastModified,
                dataUrl
            }
        });
        if (!response?.success || response?.verified !== true) {
            throw new Error(response?.error || 'Dola did not confirm an attached image preview.');
        }
        return response;
    }

    async function blobToDataUrl(blob, fallbackType) {
        if (!(blob instanceof Blob)) throw new Error('The stored image data is unavailable.');
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = '';
        const chunkSize = 0x8000;
        for (let index = 0; index < bytes.length; index += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
        }
        return `data:${blob.type || fallbackType || 'image/png'};base64,${btoa(binary)}`;
    }

    function openDatabase() {
        if (databasePromise) return databasePromise;
        databasePromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(STORE_NAME)) {
                    const store = database.createObjectStore(STORE_NAME, {keyPath: 'id'});
                    store.createIndex('order', 'order', {unique: false});
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('Image queue could not be opened.'));
        });
        return databasePromise;
    }

    async function getAllRecords() {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readonly');
            const request = transaction.objectStore(STORE_NAME).getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error || new Error('Image queue could not be read.'));
        });
    }

    async function getVerifiedRecords() {
        const records = await getAllRecords();
        const legacyDone = records.filter(record => record.status === 'done' && !Number(record.attachmentVerifiedAt));
        if (!legacyDone.length) return records;

        legacyDone.forEach(record => {
            record.status = 'queued';
            record.error = 'Previous Done status was not attachment-verified. Retry the upload.';
            record.uploadedAt = null;
            record.attachmentVerifiedAt = null;
            record.attachmentEvidence = '';
        });
        await Promise.all(legacyDone.map(record => putRecord(record)));
        return records;
    }

    async function putRecord(record) {
        const database = await openDatabase();
        return new Promise((resolve, reject) => {
            const transaction = database.transaction(STORE_NAME, 'readwrite');
            transaction.objectStore(STORE_NAME).put(record);
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error || new Error('Image status could not be saved.'));
            transaction.onabort = () => reject(transaction.error || new Error('Image status update was aborted.'));
        });
    }

    function queryTabs(queryInfo) {
        return new Promise((resolve, reject) => {
            chrome.tabs.query(queryInfo, tabs => {
                const error = chrome.runtime.lastError;
                if (error) reject(new Error(error.message));
                else resolve(tabs || []);
            });
        });
    }

    function sendTabMessage(tabId, message) {
        return new Promise((resolve, reject) => {
            chrome.tabs.sendMessage(tabId, message, response => {
                const error = chrome.runtime.lastError;
                if (error) reject(new Error(error.message));
                else resolve(response);
            });
        });
    }

    function setStorage(value) {
        return new Promise((resolve, reject) => {
            chrome.storage.local.set(value, () => {
                const error = chrome.runtime.lastError;
                if (error) reject(new Error(error.message));
                else resolve();
            });
        });
    }

    function friendlyError(error) {
        const message = error?.message || String(error);
        if (/receiving end does not exist|could not establish connection/i.test(message)) {
            return 'Refresh the target Dola tab once, then retry.';
        }
        if (/message length|native message host/i.test(message)) {
            return 'This image is too large to send to the page.';
        }
        return message;
    }

    function sortByOrder(left, right) {
        return (Number(left.order) - Number(right.order)) || (Number(left.addedAt) - Number(right.addedAt));
    }
})();
