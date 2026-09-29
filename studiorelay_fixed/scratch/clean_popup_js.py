with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('btn-activate-license')
start_target = "async function _0x151c6f"
start_idx = text.find(start_target)

end_target = "await _0x3df3bf[_0x4ccfad(0x5ff)](_0x1d4c5f);"
end_idx = text.find(end_target) + len(end_target)

print("Start target found:", start_idx)
print("End target found:", end_idx)

replacement = """async function _0x151c6f(){return {'valid': true, 'tier': 'LIFETIME'};}
(async function initNewCleanLicenseSystem() {
    const CTB_SECRET_SALT = "CTB_NEW_2026_MASTER_SECRET_KEY";

    async function sha256(str) {
        const buffer = new TextEncoder().encode(str);
        const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async function getMachineID() {
        let timezone = '';
        try { timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
        const hardwareSeed = [
            navigator.userAgent,
            navigator.language,
            screen.width + "x" + screen.height,
            screen.colorDepth,
            navigator.hardwareConcurrency || 4,
            timezone,
            new Date().getTimezoneOffset()
        ].join('|');

        const hashHex = await sha256(hardwareSeed);
        return 'CTB-' + hashHex.substring(0, 4).toUpperCase() + '-' + hashHex.substring(4, 8).toUpperCase() + '-' + hashHex.substring(8, 12).toUpperCase() + '-' + hashHex.substring(12, 16).toUpperCase();
    }

    async function generateKeyForMachine(machineId, validity) {
        const cleanId = machineId.trim().toUpperCase();
        const rawSeed = cleanId + "_" + CTB_SECRET_SALT + "_" + validity;
        const hashHex = await sha256(rawSeed);
        return 'CTB-VIP-' + hashHex.substring(0, 4).toUpperCase() + '-' + hashHex.substring(4, 8).toUpperCase() + '-' + hashHex.substring(8, 12).toUpperCase() + '-' + hashHex.substring(12, 16).toUpperCase();
    }

    async function checkKey(machineId, userKey) {
        const cleanKey = userKey.trim().toUpperCase();
        const tiers = ['LIFETIME', '1MONTH', '3MONTHS', '1YEAR'];
        for (const t of tiers) {
            const exp = await generateKeyForMachine(machineId, t);
            if (cleanKey === exp) return { valid: true, tier: t };
        }
        return { valid: false };
    }

    const displayMachineId = document.getElementById('display-machine-id');
    const btnCopyMachineId = document.getElementById('btn-copy-machine-id');
    const inputLicenseKey = document.getElementById('input-license-key');
    const btnActivate = document.getElementById('btn-activate-license');
    const activationError = document.getElementById('activation-error');
    const lockView = document.getElementById('view-license-lock');
    const unlockedUI = document.getElementById('main-unlocked-ui');

    if (!lockView || !unlockedUI) return;

    const machineId = await getMachineID();
    if (displayMachineId) displayMachineId.textContent = machineId;

    if (btnCopyMachineId) {
        btnCopyMachineId.onclick = (e) => {
            e.preventDefault();
            navigator.clipboard.writeText(machineId).then(() => {
                btnCopyMachineId.textContent = '✅ Copied Machine ID!';
                setTimeout(() => { btnCopyMachineId.textContent = '📋 Copy Machine ID'; }, 2000);
            });
        };
    }

    chrome.storage.local.get(['ctb_new_vip_key'], async (res) => {
        const storedKey = res.ctb_new_vip_key;
        if (storedKey) {
            const status = await checkKey(machineId, storedKey);
            if (status.valid) {
                lockView.style.display = 'none';
                unlockedUI.style.display = 'block';
                return;
            }
        }
        lockView.style.display = 'block';
        unlockedUI.style.display = 'none';
    });

    if (btnActivate && inputLicenseKey) {
        btnActivate.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const userKey = inputLicenseKey.value.trim().toUpperCase();
            if (!userKey) {
                if (activationError) {
                    activationError.style.color = '#ef4444';
                    activationError.textContent = 'Please enter a VIP License Key.';
                }
                return;
            }

            const status = await checkKey(machineId, userKey);
            if (status.valid) {
                chrome.storage.local.set({ 'ctb_new_vip_key': userKey, 'ctb_vip_activated': true }, () => {
                    if (activationError) {
                        activationError.style.color = '#34d399';
                        activationError.textContent = '⚡ VIP License Activated Successfully!';
                    }
                    setTimeout(() => {
                        lockView.style.display = 'none';
                        unlockedUI.style.display = 'block';
                    }, 600);
                });
            } else {
                if (activationError) {
                    activationError.style.color = '#ef4444';
                    activationError.textContent = '❌ Invalid VIP Key for this Machine ID.';
                }
            }
        };
    }
})();"""

new_text = text[:start_idx] + replacement + text[end_idx:]

with open(r'c:\Users\Admin\Desktop\Tools\dola channa extension\channa\popup.js', 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Successfully replaced legacy obfuscated license logic in popup.js!")
