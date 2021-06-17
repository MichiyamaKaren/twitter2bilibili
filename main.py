import os
import logging
import asyncio

from twitter2bilibili import TwitterListener, BiliSender
from twitter2bilibili import Tweet

from config import TWITTER_BEARER_TOKEN, BILI_BILI_JCT, BILI_BUVID3, BILI_SESSDATA, \
    subscribe_users, display_timezone


sender = BiliSender(sessdata=BILI_SESSDATA, bili_jct=BILI_BILI_JCT, buvid3=BILI_BUVID3)

logging.basicConfig(filename='main.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')


async def initialize_listener(listener: TwitterListener):
    await listener.get_rules()
    all_ids = [rule['id'] for rule in listener.rules]
    await listener.delete_rules(all_ids)
    await listener.add_rules(listener._make_rules('test'))
    print(listener.rules)


async def forwarding(listener: TwitterListener, tweet: Tweet):
    if tweet.type == 'replied_to':
        # 待进一步实现
        return

    display_text = ''
    # 剧透预警
    for hashtag in tweet.entities.get('hashtags', []):
        if hashtag['tag'] == '劇場版スタァライトネタバレ':
            display_text += '【剧透预警】本篇推文中含有少歌剧场版剧透内容\n'

    display_text += '{}于{}'.format(
        listener.get_author_name(tweet.author),
        tweet.get_create_time(display_timezone).strftime('%Y-%m-%d %H:%M:%S'))
    if tweet.type == 'original':
        display_text += '发推：\n' + tweet.parse_text()
    else:
        display_text += '转发了{}于{}的推特：\n'.format(
            listener.get_author_name(tweet.referenced_tweet.author),
            tweet.referenced_tweet.get_create_time(display_timezone),
            tweet.referenced_tweet.parse_text()
        )
        if tweet.type == 'quoted':
            display_text += tweet.parse_text()+'\n'
        display_text += '----------\n原推：\n'+tweet.referenced_tweet.parse_text()

    # 处理图片
    pic_dir = 'pic_dir'
    if not os.path.exists(pic_dir):
        os.mkdir(pic_dir)
    photo_media = [media for media in tweet.media if media.type == 'photo']
    media_paths = [os.path.join(pic_dir, media.key) for media in photo_media]
    download_pic_coroutines = [media.get_photo(
        path) for media, path in zip(photo_media, media_paths)]

    try:
        for future in asyncio.as_completed(download_pic_coroutines):
            await future
        await sender.send(display_text, media_paths)
    except Exception as e:
        logging.error(f'Error: {e} on tweet id {tweet.id}')
    for path in media_paths:
        os.remove(path)

    logging.info(f'Forwarded {tweet.author.username}\'s twitter.')

query = {'expansions': 'author_id,attachments.media_keys,referenced_tweets.id',
         'tweet.fields': 'created_at,entities,in_reply_to_user_id,referenced_tweets,text',
         'media.fields': 'type,url', 'user.fields': 'username'}

listener = TwitterListener(TWITTER_BEARER_TOKEN, subscribe_users)
listener.run(initialize=initialize_listener,
             query=query, tweet_handler=forwarding)
