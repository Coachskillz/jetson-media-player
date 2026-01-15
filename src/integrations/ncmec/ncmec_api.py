import os, json, requests
from typing import Optional, Generator, Dict

POSTER_BASE = "https://posterapi.ncmec.org"
ORG_CODE = "NCMEC"    # Change if you are given a specific org code

class NCMECPosterClient:
    def __init__(self):
        self.client_id = os.getenv("NCMEC_POSTER_CLIENT_ID")
        self.client_secret = os.getenv("NCMEC_POSTER_CLIENT_SECRET")
        if not (self.client_id and self.client_secret):
            raise RuntimeError("Set NCMEC_POSTER_CLIENT_ID and _SECRET env vars")
        self._token = None

    def _get_token(self) -> str:
        payload = {"clientId": self.client_id, "clientSecret": self.client_secret}
        headers = {
            "Content-Type": "application/json-patch+json",
            "Accept": "application/json"
        }
        r = requests.post(f"{POSTER_BASE}/Auth/Token", data=json.dumps(payload), headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()["accessToken"]

    @property
    def token(self) -> str:
        if not self._token:
            self._token = self._get_token()
        return self._token

    def search_posters(self, *, page_size: int = 100, page: int = 1) -> Generator[Dict, None, None]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        body = {
            "organizationCode": ORG_CODE,
            "pageNumber": page,
            "pageSize": page_size
        }
        r = requests.post(f"{POSTER_BASE}/Poster/Search", headers=headers, json=body, timeout=30)
        r.raise_for_status()
        posters = r.json().get("posters", [])
        for poster in posters:
            yield poster
