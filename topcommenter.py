import requests
import imagehash
import redis
import time
import logging
from imgurpython import ImgurClient
from PIL import Image
from io import BytesIO
from helpers import get_config
from imgurpython.imgur.models.gallery_album import GalleryAlbum
from imgurpython.imgur.models.gallery_image import GalleryImage
from imgurpython.helpers.error import ImgurClientError

# Redis client
r = None

# Imgur client
client = None


class Post:
    def __init__(self, post_id, title):
        self.post_id = post_id
        self.title = title
        self.album = list()

    def add_image(self, pi):
        assert isinstance(pi, PostImage)
        self.album.append(pi)

    @property
    def post_hash(self):
        return u''.join(i.image_hash for i in self.album)

    def __str__(self):
        return u"{}: {} images".format(self.title, len(self.album))

    def __eq__(self, other):
        return self.post_id == other.post_id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.post_id)


class PostImage:
    def __init__(self, image_id):
        self.image_id = image_id

    def __str__(self):
        return self.image_id


def process_gallery_image(post, gi):
    def get_thumbnail(size='s'):
        return u'{}.'.format(size).join(gi.link.rsplit('.', 1))

    def get_difference_hash(tn_url):
        tn_response = requests.get(tn_url)
        if not tn_response.ok:
            pi.thumbnail = None
            tn_response = requests.get(gi.link)
        tn_image = Image.open(BytesIO(tn_response.content))
        return imagehash.dhash(tn_image)

    pi = PostImage(gi.id)
    pi.thumbnail = get_thumbnail()
    try:
        pi.image_hash = str(get_difference_hash(pi.thumbnail))
    except IOError:
        return

    post.add_image(pi)


def process_gallery_album(post, ga):
    for gi in client.get_album_images(ga.id):
        process_gallery_image(post, gi)


def get_posts(section, pages=1):
    posts = []
    # This set keeps a temporary record of posts we've seen in this function call
    post_id_cache = set()
    for page_num in range(pages):
        if section == 'top':
            image_gallery = client.gallery(section='hot', sort='top', window='day', page=page_num)
        elif section == 'user':
            # Add one to the page number to avoid imgur bug where published albums have no images
            image_gallery = client.gallery(section='user', sort='time', window='day', page=page_num)

        for item in image_gallery:
            # Skip items we've seen in previous runs
            if r.get(item.id) or item.id in post_id_cache:
                continue
            else:
                post_id_cache.add(item.id)

            # Process gallery item
            p = Post(item.id, item.title)
            if isinstance(item, GalleryImage):
                try:
                    process_gallery_image(p, item)
                except IOError:
                    # This appears to happen with certain image types
                    # TODO: Filter on mimetype
                    logging.exception(u"Exception while calling process_gallery_image(%s, %s)", unicode(p), item.link)
                    r.set(p.post_id, 'error')
                    continue
            elif isinstance(item, GalleryAlbum):
                try:
                    # There's no point in continuing if there are no images in the gallery
                    if int(item.images_count) == 0:
                        r.set(p.post_id, 'error')
                        continue

                    process_gallery_album(p, item)

                    # There's no point in continuing if there are no images in the gallery
                    if len(p.album) == 0:
                        r.set(p.post_id, 'error')
                        continue
                except ImgurClientError:
                    # As far as I can tell this happens when a gallery is deleted after between the gallery call and now
                    # This happens often enough that we'll only log it as a warning
                    logging.warning(u"Exception while calling process_gallery_album(%s, %s)", unicode(p), item.link)
                    r.set(p.post_id, 'error')
                    continue
            else:
                raise ValueError(u"Received unknown class in gallery query: {}".format(type(item)))

            # If the hash has the value 'error', then skip.  This allows us to blacklist problematic hashes
            if r.get(p.post_hash) == 'error':
                logging.debug(u"Found post with blacklisted hash.  ID: %s  Hash: %s", item.id, p.post_hash)
                r.set(p.post_id, 'error')
                continue

            if section == 'top':
                try:
                    p.top_comment = client.gallery_item_comments(p.post_id)[0].comment
                except ImgurClientError:
                    # This seems to happen with old posts.  Imgur bug.
                    logging.exception(u"Exception while calling gallery_item_comments(%s)", unicode(p.post_id))
                    r.set(p.post_id, 'error')
                    continue

            posts.append(p)

    # Remove duplicates before returning to prevent double-commenting
    return list(set(posts))


def save_top_comment_info(post_list):
    for p in post_list:
        r.set(p.post_hash, p.top_comment)
        r.set(p.post_id, p.post_hash)


def comment_on_posts(post_list):
    for p in post_list:
        r.set(p.post_id, p.post_hash)
        stored_top_comment = r.get(p.post_hash)
        if stored_top_comment:
            logging.info(u"We found a repost!!!  Posting '%s' to %s", stored_top_comment, p.post_id)
            try:
                client.gallery_comment(p.post_id, stored_top_comment)
            except ImgurClientError:
                logging.exception(u"Exception while calling gallery_comment(%s, %s)", p.post_id, stored_top_comment)
                continue


def main():
    global r, client

    logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level='INFO', datefmt='%m/%d/%Y %I:%M:%S %p')

    config = get_config()
    config.read('auth.ini')

    client_id = config.get('credentials', 'client_id')
    client_secret = config.get('credentials', 'client_secret')
    refresh_token = config.get('credentials', 'refresh_token')

    client = ImgurClient(client_id, client_secret, None, refresh_token)
    r = redis.StrictRedis(host='localhost', port=6379, db=0)

    for i in range(60):
        # Scan for front page posts
        top_posts = get_posts('top', pages=1)
        save_top_comment_info(top_posts)

        logging.info(u"Saved %d new images to the database", len(top_posts))
        logging.debug(u"User Credit Limit Remaining: %s", client.credits['UserRemaining'])
        logging.debug(u"Client Credit Limit Remaining: %s", client.credits['ClientRemaining'])

        for j in range(10):
            # Scan for user posts
            user_posts = get_posts('user', pages=3)
            comment_on_posts(user_posts)
            logging.info(u"Scanned 3 pages of User Sub, found %d new posts", len(user_posts))
            logging.debug(u"User Credit Limit Remaining: %s", client.credits['UserRemaining'])
            logging.debug(u"Client Credit Limit Remaining: %s", client.credits['ClientRemaining'])
            time.sleep(120)

if __name__ == '__main__':
    main()
