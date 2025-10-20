from src.common.cms_client import CMSClient

print("🎬 Pairing Jetson with CMS on Mac")

# Your Mac's IP address
CMS_URL = "http://192.168.1.83:5001"

client = CMSClient(cms_url=CMS_URL)
code = client.request_pairing()

if code:
    if client.wait_for_pairing():
        print("\n✅ Pairing successful!")
    else:
        print("\n❌ Pairing failed")
else:
    print("❌ Could not connect to CMS")
