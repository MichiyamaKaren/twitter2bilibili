import os
import asyncio
from signal import SIGINT, SIGTERM
from loguru import logger

import json
from datetime import datetime, timedelta

from .listener import TwitterListener
from .sender import BiliSender
from .tweet import Tweet

from typing import List, Dict, Tuple, Optional


class AbortForwarding(Exception):
    pass


class RetryForwarding(Exception):
    def __init__(self, tweet_id: int, *args: object) -> None:
        super().__init__(*args)
        self.tweet_id = tweet_id


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

        self._forward_info_file = 'forward_info.json'
        self._forward_info_valid_time = timedelta(weeks=1)

    async def _download_photos(self, tweet: Tweet) -> List[bytes]:
        photo_media = [media for media in tweet.media if media.type == 'photo']
        download_photo_coroutines = [media.get_photo()
                                     for media in photo_media]
        return await asyncio.gather(*download_photo_coroutines)

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

    def _load_forward_info_file(self) -> Dict:
        if not os.path.exists(self._forward_info_file):
            return {}
        with open(self._forward_info_file, 'r') as f:
            forward_info = json.load(f)
        return forward_info

    def _filter_valid_forward_info(self, forward_info: Dict) -> Dict:
        valid_forward_info = forward_info.copy()
        now = datetime.now()
        for key, value in forward_info.items():
            time = datetime.strptime(value['time'], '%Y-%m-%d %H:%M:%S')
            if now-time > self._forward_info_valid_time:
                valid_forward_info.pop(key)
        return valid_forward_info

    def _save_forward_info_file(self, forward_info: Dict):
        valid_forward_info = self._filter_valid_forward_info(forward_info)
        with open(self._forward_info_file, 'w') as f:
            json.dump(valid_forward_info, f)

    def save_forward_info(self, tweet: Tweet, dynamic_id: int):
        forward_info = self._load_forward_info_file()
        forward_info[tweet.id] = {
            'dynamic_id': dynamic_id, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        self._save_forward_info_file(forward_info)

    def get_forward_dynamic_id(self, tweet_id: int) -> Optional[int]:
        forward_info = self._load_forward_info_file()
        if str(tweet_id) in forward_info:     # json存储时会将整数key转成字符串
            return forward_info[str(tweet_id)]['dynamic_id']
        else:
            return None

    def _check_spoiler(self, tweet: Tweet) -> bool:
        # 剧透预警
        for hashtag in tweet.entities.get('hashtags', []):
            if hashtag['tag'] == '劇場版スタァライトネタバレ':
                return True
        return False

    def get_forward_action(self, tweet: Tweet) -> Tuple[str, Optional[int]]:
        if tweet.type == 'original':
            return 'send', None
        elif tweet.type == 'retweeted':
            # 不带内容转推，认为是纯工商推，不处理
            raise AbortForwarding
        else:
            ref_subscribed = tweet.referenced_tweet.author.username in self.listener.subscribe_users
            if tweet.type == 'quoted':
                if ref_subscribed:
                    dynamic_id = self.get_forward_dynamic_id(tweet.referenced_tweet.id)
                    if dynamic_id is not None:
                        return ('send', dynamic_id) if tweet.media_keys else ('repost', dynamic_id)
                return 'send', None
            elif tweet.type == 'replied_to':
                if ref_subscribed:
                    dynamic_id = self.get_forward_dynamic_id(tweet.referenced_tweet.id)
                    if dynamic_id is not None:
                        return 'comment', dynamic_id
                # 只搬对已经转到B站的推的评论
                raise AbortForwarding

    async def on_send_dynamic(self, tweet: Tweet, dynamic_id: Optional[int]):
        text = ''
        if self._check_spoiler(tweet):
            text += '【剧透预警】本篇推文中含有少歌剧场版剧透内容\n'

        text += '{}于{}'.format(
            self.listener.get_author_name(tweet.author),
            tweet.get_create_time(self.display_timezone).strftime('%Y-%m-%d %H:%M:%S'))
        if tweet.type == 'original':
            text += '发推：\n' + tweet.parse_text()
        elif tweet.type == 'quoted':
            text += '转发了{}的推特：\n{}\n----------\n原推：'.format(
                self.listener.get_author_name(tweet.referenced_tweet.author),
                tweet.parse_text()
            )
            if dynamic_id is None:
                text += '\n' + tweet.referenced_tweet.parse_text()
            else:
                text += f'https://t.bilibili.com/{dynamic_id}'

        photos = await self._download_photos(tweet)
        response = await self.sender.send(text=text, image_streams=photos)
        self.save_forward_info(tweet, response['dynamic_id'])

    async def on_repost(self, tweet: Tweet, dynamic_id: int):
        text = ''
        if self._check_spoiler(tweet):
            text += '【剧透预警】本篇推文中含有少歌剧场版剧透内容\n'

        text += '{}于{}转发了此条推：\n{}'.format(
            self.listener.get_author_name(tweet.author),
            tweet.get_create_time(self.display_timezone).strftime(
                '%Y-%m-%d %H:%M:%S'),
            tweet.parse_text())
        if len(text) > 233:
            # 超过转发字数限制
            # 由于动态转发API不会返回动态id，所以只能退而重发一条
            await self.on_send_dynamic(tweet, dynamic_id)
        else:
            await self.sender.repost_dynamic(text=text, dynamic_id=dynamic_id)

    async def on_comment(self, tweet: Tweet, dynamic_id: int):
        text = ''
        if self._check_spoiler(tweet):
            text += '【剧透预警】本条评论中含有少歌剧场版剧透内容\n'

        text += '{}于{}评论：\n{}'.format(
            self.listener.get_author_name(tweet.author),
            tweet.get_create_time(self.display_timezone).strftime(
                '%Y-%m-%d %H:%M:%S'),
            tweet.parse_text())
        await self.sender.send_comment(text=text, dynamic_id=dynamic_id)

    async def handler(self, tweet: Tweet):
        try:
            action, dynamic_id = self.get_forward_action(tweet)
            if action == 'send':
                await self.on_send_dynamic(tweet, dynamic_id)
            elif action == 'repost':
                await self.on_repost(tweet, dynamic_id)
            elif action == 'comment':
                await self.on_comment(tweet, dynamic_id)
        except AbortForwarding:
            logger.debug(f'Aborted tweet id {tweet.id}')
        except Exception as e:
            logger.error(f'Error on tweet id {tweet.id}: {e}')
        else:
            logger.info(f'Forwarded tweet id {tweet.id}')

    def run(self):
        loop = asyncio.get_event_loop()
        task = asyncio.ensure_future(self.listener.listen(
            self.listener_initializer, self.query, self.handler))
        # Ctrl C退出
        for signal in [SIGINT, SIGTERM]:
            loop.add_signal_handler(signal, task.cancel)
        loop.run_until_complete(task)
