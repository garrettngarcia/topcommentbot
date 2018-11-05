#!/usr/bin/env python2.7

import redis
import sys
import os
import ConfigParser
from gimgur import *


def main():
    for item in imgur_client.get_items_iter('hot', pages=1):
        if hash_store.get(item.id):
            continue

        post = Post(item, imgur_client)
        post.refresh_top_comment(imgur_client)

        # Blacklist the problem post
        if post.errors:
            hash_store.set(post.post_id, 'ERROR_POST')
            logging.info("Skipping problem post: %s", post.post_id)
            continue
            
        logging.info("Saving comment %s to %s", post.top_comment, post.post_hash)
        hash_store.set(post.post_hash, post.top_comment)
        hash_store.set(post.post_id, post.post_hash)


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
        hash_store = redis.StrictRedis(host=os.environ["REDIS_HOST"], port=6379, db=0)

        # Enter the main loop
        main()
    except KeyboardInterrupt:
        logging.info("Quitting")
        sys.exit(0)
