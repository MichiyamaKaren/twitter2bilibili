import aiohttp
from datetime import datetime
from pytz import timezone

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
        async with aiohttp.ClientSession() as session:
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
            self.media_keys: List[str] = attachments.get('media_keys', [])
        else:
            self.media_keys = []
        self.media: List[Optional[TwitterMedia]] = [
            self.get_from_includes(tweet_includes, 'media', mkey) for mkey in self.media_keys]

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
                unwound_url = url.get('unwound_url', '')
                # 将短URL替换成unwound_url（按推特API文档，为full destination URL，媒体的URL不含这个域）
                replaced_text += text[i:url['start']] + unwound_url
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
