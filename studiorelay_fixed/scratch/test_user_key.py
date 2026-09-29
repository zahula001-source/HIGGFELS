import hashlib

seed = "CTB-815F-AB80-DD75-0B26_CTB_PRO_VIP_LIFETIME_SALT_2026_PRO_PROTECT_2026"
h = hashlib.sha256(seed.encode('utf-8')).hexdigest().upper()
key = f"CTB-VIP-{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"
print("Expected Key for CTB-815F-AB80-DD75-0B26:")
print(key)
