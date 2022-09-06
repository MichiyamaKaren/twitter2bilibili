import aiohttp
from datetime import datetime
from pytz import timezone

from .twitter_api import TwitterAPI
from .utils.network import get_session

from typing import Optional, Dict, List


class TwitterUser:
    def __init__(self, id: str, username: str, name: str = None, **kwargs) -> None:
        """
        Args:
            id (str): 推特用户的数字id
            username (str): 推特用户名（唯一）
            nickname (str, optional): 推特名（在推特时间线上显示的），默认为None
        """
        self.id = id
        self.username = username
        self.nickname = name


class TwitterMedia:
    def __init__(self, media_key: str, type: str, url: Optional[str] = None, **kwargs) -> None:
        self.key = media_key
        self.type = type  # 可能为photo, GIF, or video
        if self.type == 'photo':
            self.url: str = url
        else:
            self.url = None

    async def get_photo(self) -> bytes:
        session = get_session()
        async with session.get(self.url) as response:
            return await response.read()


class TwitterPlace:
    pass


class TwitterPoll:
    pass


class Tweet:
    def __init__(self, id: str, text: str, author_id: Optional[str] = None,
                 created_at: Optional[str] = None, referenced_tweets: Optional[Dict] = None,
                 entities: Optional[Dict] = None, attachments: Optional[Dict] = None,
                 tweet_includes: Optional[Dict] = None, **kwargs) -> None:
        self.id = id
        self.raw_text = text

        if tweet_includes is None:
            tweet_includes = {}

        if author_id is not None:
            self.author: Optional[TwitterUser] = self.get_from_includes(
                tweet_includes, 'users', author_id)
        else:
            self.author = None
        if created_at is not None:
            self.create_time: Optional[datetime] = self._parse_time(created_at)
        else:
            self.create_time = None

        if referenced_tweets is None:
            self.type: str = 'original'  # 可能为original, retweeted, quoted, replied_to
            self.referenced_tweet: Optional[Tweet] = None
        else:
            self.type = referenced_tweets[0]['type']
            self.referenced_tweet = self.get_from_includes(
                tweet_includes, 'tweets', referenced_tweets[0]['id'])
        # entities可能包含的域：annotation、urls、hashtags、mentions、cashtags
        if entities is not None:
            self.entities: Dict[str, List[Dict]] = entities
        else:
            self.entities = {}

        if attachments is not None:
            media_keys: List[str] = attachments.get('media_keys', [])
        else:
            media_keys = []
        self.media: Dict[str, Optional[TwitterMedia]] = {mkey: 
            self.get_from_includes(tweet_includes, 'media', mkey) for mkey in media_keys}

    def _parse_time(self, create_time: str) -> datetime:
        utc_time = datetime.strptime(create_time, '%Y-%m-%dT%H:%M:%S.%fZ')
        return utc_time.replace(tzinfo=timezone('utc'))

    def get_create_time(self, time_zone: str = 'utc') -> datetime:
        if self.create_time is None:
            return None
        else:
            return self.create_time.astimezone(tz=timezone(time_zone))

    def parse_text(self) -> str:
        text = self.raw_text
        # 将推特短URL恢复成正常的URL，并删除媒体URL
        urls = self.entities.get('urls', [])
        if urls:
            replaced_text = ''
            i = 0
            for url in urls:
                expanded_url = url['expanded_url']
                if 'unwound_url' not in url:
                    expanded_url = ''   # 媒体的URL不含这个域
                replaced_text += text[i:url['start']] + expanded_url
                i = url['end']
            text = replaced_text.strip()
        # TODO:如果有@，将text转成格式串，@的地方接收想要展示的用户名
        # 注意上面的处理已经改变串长
        return text

    def get_from_includes(self, includes: Dict[str, List[Dict]], include_type: str, unique_id: str):
        """
        从推特API返回的includes字典解析出推特对象（推文/用户/媒体等）

        Args:
            include_type (str): 推特对象的种类，应为'tweets','users','places','media','polls'之中其一
            unique_id (str): 能唯一确定出推特对象的ID值
        """
        include_class = {'tweets': Tweet, 'users': TwitterUser, 'media': TwitterMedia,
                         'places': TwitterPlace, 'polls': TwitterPoll}
        unique_field = {'tweets': 'id', 'users': 'id', 'media': 'media_key',
                        'places': 'id', 'polls': 'id'}
        include_object = None
        for obj in includes.get(include_type, []):
            if obj[unique_field[include_type]] == unique_id:
                include_object = obj.copy()
        if include_object is None:
            return None
        else:
            if include_type == 'tweets':
                include_object.update({'tweet_includes': includes})
            return include_class[include_type](**include_object)

    async def retrieve_media(self, api: TwitterAPI, update_self: bool = True) -> Dict[str, TwitterMedia]:
        tweet_resp = await api.tweet_lookup(
            tweet_id=self.id,
            query={'expansions': 'attachments.media_keys', 'media.fields': 'type,url'})
        media_data = tweet_resp.get('includes', {}).get('media', {})
        retrived = {data['media_key']: TwitterMedia(**data) for data in media_data}
        if update_self:
            self.media.update(retrived)
        return retrived

    async def get_media(self, media_keys: Optional[List[str]] = None,
                        twitter_api: Optional[TwitterAPI] = None,
                        update_on_retrieve: bool = True) -> List[TwitterMedia]:
        if media_keys is None:
            media_keys = self.media.keys()

        if any(map(lambda key: self.media.get(key, None) is None, media_keys)):
            if twitter_api is None:
                raise ValueError('twiter_api is needed to retrieve media data')
            retrieved = await self.retrieve_media(twitter_api, update_on_retrieve)
            media_dict = self.media if update_on_retrieve else retrieved
        else:
            media_dict = self.media

        try:
            return [media_dict[key] for key in media_keys]
        except KeyError as e:
            raise KeyError(f'media key {e.args[0]} is not included by this tweet')