import logging
import time
import requests
import imagehash
from imgurpython import ImgurClient
from imgurpython.helpers.error import ImgurClientRateLimitError, ImgurClientError
from PIL import Image
from io import BytesIO
from imgurpython.imgur.models.gallery_album import GalleryAlbum
from imgurpython.imgur.models.gallery_image import GalleryImage


class GimgurException(Exception):
    pass


# This class blocks and retries when the rate limit is close to being spent.  Not thread-safe.
class RateLimitedImgurClient(ImgurClient):
    def __init__(self, client_id, client_secret, access_token=None, refresh_token=None, mashape_key=None,
                 credit_lower_limit=10):
        super(RateLimitedImgurClient, self).__init__(client_id, client_secret, access_token, refresh_token, mashape_key)
        self.credit_lower_limit = credit_lower_limit

    def make_request(self, method, route, data=None, force_anon=False):
        def run_make_request():
            try:
                return super(RateLimitedImgurClient, self).make_request(method, route, data, force_anon)
            except ImgurClientRateLimitError:
                logging.warning("Rate Limit hit.\tUser credits remaining: %s\tApp credits remaining: %s",
                                self.credits['UserRemaining'], self.credits['ClientRemaining'])
                return None
            except ImgurClientError as e:
                if e.status_code == 500:
                    logging.warning("Imgur is over capacity.")
                    return None
                else:
                    raise

        def is_ok_to_make_request():
            if route == 'credits':
                return True
            if hasattr(self, 'credits'):
                if self.credits['UserRemaining'] and self.credits['ClientRemaining']:
                    if int(self.credits['UserRemaining']) > self.credit_lower_limit \
                            and int(self.credits['ClientRemaining']) > self.credit_lower_limit:
                        return True
            return False

        while True:
            if is_ok_to_make_request():
                result = run_make_request()
                if result is not None:
                    return result
            # Sleep before trying again
            logging.info('Sleeping for 10 minutes')
            time.sleep(60 * 10)
            logging.info("Checking credits")
            self.credits = self.get_credits()

    def get_items_iter(self, section, pages=1):
        if section == 'hot':
            sort_mode = 'top'
            sleep_time = 60 * 30
        elif section == 'user':
            sort_mode = 'time'
            sleep_time = 60 * 1
        else:
            raise GimgurException(u"Unrecognized section: %s", section)

        while True:
            for page_num in range(pages):
                image_gallery = self.gallery(section=section, sort=sort_mode, window='day', page=page_num)

                for item in image_gallery:
                    yield item
            logging.debug("Sleeping for %d seconds", sleep_time)
            time.sleep(sleep_time)


class Post:
    def __init__(self, gallery_item, imgur_client):
        self.post_id = gallery_item.id
        self.title = gallery_item.title
        self.imgur_client = imgur_client
        self.album = list()
        self.errors = []
        self.top_comment = None

        if isinstance(gallery_item, GalleryImage):
            try:
                self._process_gallery_image(gallery_item)
            except IOError as err:
                # This appears to happen with certain image types
                # TODO: Filter on mimetype
                logging.warning(u"Exception while calling process_gallery_image(%s, %s)", unicode(self),
                                gallery_item.link)
                self.errors.append(err)
                return
        elif isinstance(gallery_item, GalleryAlbum):
            # There's no point in continuing if there are no images in the gallery
            if int(gallery_item.images_count) == 0:
                self.errors.append(GimgurException("Empty gallery: %s", self.post_id))
                return

            try:
                self._process_gallery_album(gallery_item)
            except ImgurClientError as err:
                # As far as I can tell this happens when a gallery is deleted after between the gallery call and now
                # This happens often enough that we'll only log it as a warning
                logging.warning(u"Exception while calling process_gallery_album(%s, %s)", str(self),
                                gallery_item.link)
                self.errors.append(err)
        else:
            raise GimgurException(u"Received unknown class in gallery query: {}".format(type(gallery_item)))

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

    def _process_gallery_image(self, gi):
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

        self.add_image(pi)

    def _process_gallery_album(self, ga):
        for gi in self.imgur_client.get_album_images(ga.id):
            self._process_gallery_image(gi)

    def refresh_top_comment(self, imgur_client):
        try:
            self.top_comment = imgur_client.gallery_item_comments(self.post_id)[0].comment
        except ImgurClientError as err:
            # This seems to happen with old posts.  Imgur bug.
            logging.exception(u"Exception while calling gallery_item_comments(%s)", unicode(self.post_id))
            self.errors.append(err)
        return self.top_comment


class PostImage:
    def __init__(self, image_id):
        self.image_id = image_id

    def __str__(self):
        return self.image_id


class HashStoreMock(dict):
    def set(self, k, v):
        logging.info(u"Setting: [%s] = %s", k, v)
        self[k] = v

    def get(self, k):
        if k in self:
            v = self[k]
            logging.info(u"Retrieving: [%s]: %s", k, v)
            return v
        else:
            logging.info(u"Retrieving: [%s]: None", k)
            return None
