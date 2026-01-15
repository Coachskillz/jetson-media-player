# Project Facts

## Hardware
- Edge device: NVIDIA Jetson Orin Nano 8GB
- OS: JetPack 6.x

## Performance Targets
- Face detection: <20ms per frame
- FAISS search (100K): <1ms
- Total pipeline: <50ms

## Key Paths
- Player: /opt/skillz/player/
- Detection: /opt/skillz/detection/
- Databases: /opt/skillz/detection/databases/

## NCMEC Integration

- **API Base:** https://posterapi.ncmec.org
- **Auth:** OAuth2 client credentials
- **Token endpoint:** POST /Auth/Token
- **Search endpoint:** POST /Poster/Search
- **Env vars required:** NCMEC_POSTER_CLIENT_ID, NCMEC_POSTER_CLIENT_SECRET
- **Org code:** NCMEC (default)
- **Client implementation:** src/integrations/ncmec/ncmec_api.py

### Poster Data Flow
1. Central Hub fetches posters via search_posters()
2. Extract face images from poster data
3. Generate FAISS embeddings
4. Distribute index to Local Hubs
5. Local Hubs push to Jetsons
