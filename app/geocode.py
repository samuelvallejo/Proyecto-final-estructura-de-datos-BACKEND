import asyncio
import time
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from . import schema as s


class Geocoder:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.lock = asyncio.Lock()
        self.next_request = 0.0

    async def resolve(self, position):
        key = f'{position.lat:.4f},{position.lng:.4f}'
        with self.engine.connect() as conn:
            cached = conn.execute(select(s.geocode_cache).where(
                s.geocode_cache.c.cache_key == key, s.geocode_cache.c.expires_at > s.now())).mappings().first()
        if cached:
            return cached['payload']
        empty = {'street': None, 'neighborhood': None, 'city': None, 'fullAddress': None,
                 'countryCode': None, 'country': None, 'region': None, 'source': 'gps', 'cacheKey': key}
        if not self.settings.nominatim_user_agent:
            return empty
        async with self.lock:
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 1.1
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(self.settings.nominatim_url.rstrip('/') + '/reverse',
                        params={'format': 'jsonv2', 'lat': position.lat, 'lon': position.lng, 'zoom': 18, 'addressdetails': 1},
                        headers={'User-Agent': self.settings.nominatim_user_agent, 'Accept-Language': 'es'})
                    response.raise_for_status()
                    data = response.json()
                address = data.get('address', {})
                payload = {**empty,
                    'street': address.get('road') or address.get('pedestrian'),
                    'neighborhood': address.get('neighbourhood') or address.get('suburb') or address.get('quarter'),
                    'city': address.get('city') or address.get('town') or address.get('municipality') or address.get('village'),
                    'fullAddress': data.get('display_name'), 'countryCode': address.get('country_code'),
                    'country': address.get('country'), 'region': address.get('state') or address.get('region'),
                    'source': 'nominatim'}
                ttl = 7 * 86400_000
            except (httpx.HTTPError, ValueError, TypeError):
                payload, ttl = empty, 60_000
            with self.engine.begin() as conn:
                stmt = insert(s.geocode_cache).values(cache_key=key, payload=payload, expires_at=s.now() + ttl)
                conn.execute(stmt.on_conflict_do_update(index_elements=['cache_key'], set_={
                    'payload': payload, 'expires_at': s.now() + ttl}))
            return payload
