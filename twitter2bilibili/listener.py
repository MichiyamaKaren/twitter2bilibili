import json
import aiohttp
import asyncio
from loguru import logger

from .tweet import Tweet, TwitterUser

from typing import Dict, List, Coroutine, Callable


class TwitterListener:
    RULES_URL = 'https://api.twitter.com/2/tweets/search/stream/rules'
    STREAM_URL = 'https://api.twitter.com/2/tweets/search/stream'

    def __init__(self, bearer_token: str, subscribe_users: List[Dict]) -> None:
        self.bearer_token = bearer_token
        self._headers = self._make_headers()

        self.subscribe_users: Dict[str, Dict] = {
            user['username']: user for user in subscribe_users}

        self.rules: List[Dict] = []
        self.not_gotten_rules: bool = True

    def _make_headers(self) -> Dict:
        headers = {'Authorization': f'Bearer {self.bearer_token}'}
        return headers

    def _make_rules(self, tag) -> Dict:
        rule_value = ' OR '.join([
            'from:'+user['username'] for user in self.subscribe_users.values()])
        return [{'value': rule_value, 'tag': tag}]

    async def get_rules(self) -> List[Dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.RULES_URL, headers=self._headers) as response:
                if response.status != 200:
                    raise Exception(f'Cannot get rules (HTTP {response.status}): {await response.text()}')
                self.rules = (await response.json()).get('data', [])
        self.not_gotten_rules = False
        return self.rules

    async def delete_rules(self, ids: List[str]):
        if not ids:
            return
        payload = {'delete': {'ids': ids}}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.RULES_URL, json=payload, headers=self._headers) as response:
                if response.status != 200:
                    raise Exception(f'Cannot delete rules (HTTP {response.status}): {await response.text()}')
        self.rules = [rule for rule in self.rules if rule['id'] not in ids]

    async def add_rules(self, rules: List[Dict]):
        payload = {'add': rules}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.RULES_URL, json=payload, headers=self._headers) as response:
                if response.status != 201:
                    raise Exception(f'Cannot add rules (HTTP {response.status}): {await response.text()}')
                self.rules.extend((await response.json())['data'])

    def get_author_name(self, author:TwitterUser):
        if author.username in self.subscribe_users:
            return self.subscribe_users[author.username]['name']
        elif author.nickname is not None:
            return author.nickname
        else:
            return author.username

    def _split_tweets_response(self, tweets_response: Dict) -> List[Tweet]:
        tweet_dicts = tweets_response['data']
        if isinstance(tweet_dicts, dict):
            tweet_dicts = [tweet_dicts]
        tweets = [Tweet(
            **d, tweet_includes=tweets_response['includes']) for d in tweet_dicts]
        return tweets

    async def listen(self, initialize: Callable[['TwitterListener'], Coroutine], query: Dict,
                     tweet_handler: Callable[[Tweet], Coroutine]):
        await initialize(self)
        timeout = aiohttp.ClientTimeout(None)  # 永不超时
        while True:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.get(self.STREAM_URL, params=query, headers=self._headers) as response:
                        if response.status != 200:
                            raise Exception(f'Cannot get stream (HTTP {response.status}): {await response.text()}')
                        async for response_line in response.content:
                            if response_line != b'\r\n':  # '\r\n'为filtered stream的keep alive信号
                                tweets_response = json.loads(response_line)
                                try:
                                    tweets = self._split_tweets_response(tweets_response)
                                    await asyncio.gather(*[tweet_handler(tweet) for tweet in tweets])
                                except Exception as e:
                                    logger.error(f'Error {e} on response:\n {tweets_response}')
                except Exception as e:
                    logger.error(f'Connection closed due to error: {e}')
                    await session.close()
            await asyncio.sleep(60)    # 因为奇怪原因断连之后睡一段时间再重连上
            logger.info('Reconnected.')
