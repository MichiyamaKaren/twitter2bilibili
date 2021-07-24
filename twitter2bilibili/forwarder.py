import os
import asyncio
from signal import SIGINT, SIGTERM
from loguru import logger

from .listener import TwitterListener
from .sender import BiliSender
from .tweet import Tweet

from typing import List, Dict


class T2BForwarder:
    def __init__(self, config_object) -> None:
        self.listener = TwitterListener(
            bearer_token=getattr(config_object, 'TWITTER_BEARER_TOKEN'),
            subscribe_users=getattr(config_object, 'subscribe_users'))
        self.sender = BiliSender(
            sessdata=getattr(config_object, 'BILI_SESSDATA'),
            bili_jct=getattr(config_object, 'BILI_BILI_JCT'),
            buvid3=getattr(config_object, 'BILI_BUVID3'))

        self.display_timezone: str = getattr(config_object, 'display_timezone')
        self.media_dir: str = getattr(config_object, 'media_dir', 'media_dir')
        if not os.path.exists(self.media_dir):
            os.mkdir(self.media_dir)

    async def _download_media(self, tweet: Tweet) -> List[str]:
        photo_media = [media for media in tweet.media if media.type == 'photo']
        media_paths = [os.path.join(self.media_dir, media.key)
                       for media in photo_media]

        download_pic_coroutines = [media.get_photo(
            path) for media, path in zip(photo_media, media_paths)]
        await asyncio.gather(*download_pic_coroutines)

        return media_paths

    def _delete_media(self, media_paths: List[str]):
        for path in media_paths:
            os.remove(path)

    @property
    def query(self) -> Dict:
        return {
            'expansions': 'author_id,attachments.media_keys,referenced_tweets.id',
            'tweet.fields': 'created_at,entities,in_reply_to_user_id,referenced_tweets,text',
            'media.fields': 'type,url', 'user.fields': 'username'}

    async def listener_initializer(self, listener: TwitterListener):
        await listener.get_rules()
        all_ids = [rule['id'] for rule in listener.rules]
        await listener.delete_rules(all_ids)
        await listener.add_rules(listener._make_rules('t2b'))
        logger.info(f'Start listening on rules: {listener.rules}')

    def tweet_filter(self, tweet: Tweet) -> bool:
        if tweet.type == 'retweeted':
            # 不带内容转推，认为是纯工商推，不处理
            return False
        if tweet.type == 'replied_to':
            # 待进一步实现
            return False
        return True

    def get_display_text(self, tweet: Tweet) -> str:
        display_text = ''
        # 剧透预警
        for hashtag in tweet.entities.get('hashtags', []):
            if hashtag['tag'] == '劇場版スタァライトネタバレ':
                display_text += '【剧透预警】本篇推文中含有少歌剧场版剧透内容\n'

        display_text += '{}于{}'.format(
            self.listener.get_author_name(tweet.author),
            tweet.get_create_time(self.display_timezone).strftime('%Y-%m-%d %H:%M:%S'))
        if tweet.type == 'original':
            display_text += '发推：\n' + tweet.parse_text()
        else:
            display_text += '转发了{}的推特：\n{}\n----------\n原推：\n{}'.format(
                self.listener.get_author_name(tweet.referenced_tweet.author),
                tweet.parse_text(),
                tweet.referenced_tweet.parse_text()
            )
        return display_text

    async def handler(self, tweet: Tweet):
        if not self.tweet_filter(tweet):
            return

        display_text = self.get_display_text(tweet)
        try:
            media_paths = await self._download_media(tweet)
            await self.sender.send(display_text, media_paths)
        except Exception as e:
            logger.error(f'Error: {e} on tweet id {tweet.id}')
        else:
            logger.info(
                f'Forwarded {tweet.author.username}\'s twitter, id {tweet.id}')
        finally:
            self._delete_media(media_paths)

    def run(self):
        loop = asyncio.get_event_loop()
        task = asyncio.ensure_future(self.listener.listen(
            self.listener_initializer, self.query, self.handler))
        # Ctrl C退出
        for signal in [SIGINT, SIGTERM]:
            loop.add_signal_handler(signal, task.cancel)
        loop.run_until_complete(task)
