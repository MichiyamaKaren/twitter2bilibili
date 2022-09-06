import json
import asyncio
from loguru import logger

from .tweet import Tweet, TwitterUser
from .twitter_api import TwitterAPI, TwitterAPIException, ClientResponse

from typing import Dict, List, Coroutine, Callable


class TwitterListener:
    def __init__(self, api: TwitterAPI, subscribe_users: List[Dict]) -> None:
        self.api = api

        self.subscribe_users: Dict[str, Dict] = {
            user['username']: user for user in subscribe_users}

        self.rules: List[Dict] = []
        self.not_gotten_rules: bool = True

    def _make_rules(self, tag) -> Dict:
        rule_value = ' OR '.join([
            'from:'+user['username'] for user in self.subscribe_users.values()])
        return [{'value': rule_value, 'tag': tag}]

    async def get_rules(self) -> List[Dict]:
        self.rules = (await self.api.get_stream_rules()).get('data', [])
        self.not_gotten_rules = False
        return self.rules

    async def delete_rules(self, ids: List[str]):
        if not ids:
            return
        payload = {'delete': {'ids': ids}}
        await self.api.set_stream_rules(payload)
        self.rules = [rule for rule in self.rules if rule['id'] not in ids]

    async def add_rules(self, rules: List[Dict]):
        payload = {'add': rules}
        response = await self.api.set_stream_rules(payload)
        self.rules.extend(response['data'])

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

    async def _try_connect_until_succeed(self, query: Dict, retry_interval: float = 300) -> ClientResponse:
        while True:
            try:
                response = await self.api.get_filtered_stream(query)
            except TwitterAPIException as e:
                logger.error(f'Connect failed due to twitter error {e.code}: {e.data}')
            except Exception as e:
                logger.error(f'Connect failed due to error: {e}')
            else:
                logger.info('Connected.')
                return response

            # 推特filtered stream同时只允许一个连接，客户端断开之后在连接在服务端会保持一段时间，故睡一段时间再尝试重连
            # 间隔时间过短会导致尝试总时间拉长（原因不明），经测试间隔300s不会多次重连
            await asyncio.sleep(retry_interval)

    async def listen(self, initialize: Callable[['TwitterListener'], Coroutine], query: Dict,
                     tweet_handler: Callable[[Tweet], Coroutine]):
        await initialize(self)
        while True:
            response = await self._try_connect_until_succeed(query)
            try:
                async for response_line in response.content:
                    if response_line != b'\r\n':  # '\r\n'为filtered stream的keep alive信号
                        tweets_response = json.loads(response_line)
                        if 'errors' in tweets_response:
                            logger.error(f'Filtered stream error:\n{tweets_response["errors"]}')
                            break

                        try:
                            tweets = self._split_tweets_response(tweets_response)
                            await asyncio.gather(*[tweet_handler(tweet) for tweet in tweets])
                        except Exception as e:
                            logger.error(f'Error {e} on response:\n {tweets_response}')
            except Exception as e:
                logger.error(f'Connection closed due to error: {e}')
            finally:
                response.release()
