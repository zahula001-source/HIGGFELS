import hashlib

# New Master Secret Salt
SALT = "CTB_NEW_2026_MASTER_SECRET_KEY"

# Test Machine ID from user screenshot
machine_id = "CTB-815F-AB80-DD75-0B26"

def gen_key(m_id, validity):
    raw = f"{m_id}_{SALT}_{validity}"
    h = hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()
    return f"CTB-VIP-{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

print("=== NEW MASTER SYSTEM VERIFICATION TEST ===")
print("Machine ID:", machine_id)
print("Lifetime Key:", gen_key(machine_id, "LIFETIME"))
print("1 Month Key: ", gen_key(machine_id, "1MONTH"))
print("3 Month Key: ", gen_key(machine_id, "3MONTHS"))
print("1 Year Key:  ", gen_key(machine_id, "1YEAR"))
