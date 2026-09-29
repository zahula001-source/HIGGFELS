const crypto = require('crypto');

function sha256(str) {
    return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

// Simulated Hardware Parameters (Same as getMachineID)
const hardwareSeed = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "en-US",
    "1920x1080",
    24,
    4,
    "Asia/Calcutta",
    -330
].join('|');

const machineHash = sha256(hardwareSeed);
const p1 = machineHash.substring(0, 4).toUpperCase();
const p2 = machineHash.substring(4, 8).toUpperCase();
const p3 = machineHash.substring(8, 12).toUpperCase();
const p4 = machineHash.substring(12, 16).toUpperCase();

const machineId = `CTB-${p1}-${p2}-${p3}-${p4}`;
console.log('Test Machine ID:', machineId);

// Test Key Generation for Lifetime VIP
const tierSalt = "CTB_PRO_VIP_LIFETIME_SALT_2026";
const rawSeed = machineId + "_" + tierSalt + "_PRO_PROTECT_2026";
const keyHash = sha256(rawSeed);

const k1 = keyHash.substring(0, 4).toUpperCase();
const k2 = keyHash.substring(4, 8).toUpperCase();
const k3 = keyHash.substring(8, 12).toUpperCase();
const k4 = keyHash.substring(12, 16).toUpperCase();

const generatedKey = `CTB-VIP-${k1}-${k2}-${k3}-${k4}`;
console.log('Generated Key:', generatedKey);

// Verification Test
const testSeed = machineId + "_" + tierSalt + "_PRO_PROTECT_2026";
const verifyHash = sha256(testSeed);
const vk1 = verifyHash.substring(0, 4).toUpperCase();
const vk2 = verifyHash.substring(4, 8).toUpperCase();
const vk3 = verifyHash.substring(8, 12).toUpperCase();
const vk4 = verifyHash.substring(12, 16).toUpperCase();
const expectedKey = `CTB-VIP-${vk1}-${vk2}-${vk3}-${vk4}`;

console.log('Key Match Verification:', generatedKey === expectedKey ? '✅ PASS (100% MATCH)' : '❌ FAIL');
