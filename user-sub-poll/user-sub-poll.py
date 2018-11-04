#!/usr/bin/env python2.7

import redis
import sys
import ConfigParser
from gimgur import *

# Config constants
PAGES_PER_GET = 3


def comment_on_post(post):
    hash_store.set(post.post_id, post.post_hash)
    stored_top_comment = hash_store.get(post.post_hash)
    if stored_top_comment:
        if stored_top_comment.startswith(u"ERROR"):
            logging.warning(u"We found a bad hash when trying to comment on: %s", post.post_id)
            return

        logging.info(u"We found a repost!!!  Posting '%s' to %s", stored_top_comment, post.post_id)
        try:
            imgur_client.gallery_comment(post.post_id, stored_top_comment)
        except ImgurClientError:
            logging.exception(u"Exception while calling gallery_comment(%s, %s)", post.post_id, stored_top_comment)


def main():
    for item in imgur_client.get_items_iter('user', pages=PAGES_PER_GET):
        if hash_store.get(item.id):
            continue

        post = Post(item, imgur_client)

        # Blacklist the problem post
        if post.errors:
            hash_store.set(post.post_id, 'ERROR_POST')
            continue

        comment_on_post(post)


if __name__ == '__main__':
    try:
        # Configure logging
        logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level='INFO',
                            datefmt='%m/%d/%Y %I:%M:%S %p')
        logging.info("Starting...")

        # Read in credentials
        config = ConfigParser.ConfigParser()
        config.read('config/auth.ini')
        client_id = config.get('credentials', 'client_id')
        client_secret = config.get('credentials', 'client_secret')
        refresh_token = config.get('credentials', 'refresh_token')

        # Initiate client
        imgur_client = RateLimitedImgurClient(client_id, client_secret, None, refresh_token)
        # hash_store = redis.StrictRedis(host='localhost', port=6379, db=0)
        hash_store = HashStoreMock()

        # Enter the main loop
        main()
    except KeyboardInterrupt:
        logging.info("Quitting")
        sys.exit(0)
