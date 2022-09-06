from .utils.network import get_session

from typing import Dict, Union, Optional
from aiohttp import ClientTimeout, ClientResponse


class TwitterAPIException(BaseException):
    def __init__(self, code: int, data: Dict) -> None:
        self.code = code
        self.data = data


class TwitterAPI:
    TWEET_LOOKUP_BASE_URL = 'https://api.twitter.com/2/tweets/'
    STREAM_URL = 'https://api.twitter.com/2/tweets/search/stream'
    STREAM_RULES_URL = 'https://api.twitter.com/2/tweets/search/stream/rules'

    def __init__(self, bearer_token: str) -> None:
        self.bearer_token = bearer_token
        self._headers = self._make_headers()

    def _make_headers(self) -> Dict:
        headers = {'Authorization': f'Bearer {self.bearer_token}'}
        return headers

    async def request(self, method: str, url: str, params: Optional[Dict] = None,
                      json: Optional[Dict] = None, **kwargs) -> ClientResponse:
        session = get_session()
        headers = kwargs.pop('headers', self._headers)
        response = await session.request(method, url, params=params, json=json, headers=headers, **kwargs)

        if not response.ok:
            data = await response.json()
            response.release()
            raise TwitterAPIException(code=response.status, data=data)
        return response

    async def request_json(self, method: str, url: str, **kwargs) -> Dict:
        response = await self.request(method, url, **kwargs)
        data = await response.json()
        response.release()
        return data

    async def tweet_lookup(self, tweet_id: int, query: Dict) -> Dict:
        url = self.TWEET_LOOKUP_BASE_URL + str(tweet_id)
        return await self.request_json('GET', url, params=query)

    async def get_stream_rules(self) -> Dict:
        return await self.request_json('GET', self.STREAM_RULES_URL)

    async def set_stream_rules(self, payload: Dict) -> Dict:
        return await self.request_json('POST', self.STREAM_RULES_URL, json=payload)

    async def get_filtered_stream(self, query: Dict,
                                  timeout: Union[ClientTimeout, float, None] = None) -> ClientResponse:
        # timeout=None为永不超时
        return await self.request('GET', self.STREAM_URL, params=query, timeout=timeout)
