import datetime, hashlib, tweepy, urllib

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.db import models
from django.test import client
from django.utils.translation import ugettext_lazy as _

import mongoengine
from mongoengine.django import auth

from piplmesh.account import fields, utils

LOWER_DATE_LIMIT = 366 * 120
USERNAME_REGEX = r'[\w.@+-]+'

def upper_birthdate_limit():
    return datetime.datetime.today()

def lower_birthdate_limit():
    return datetime.datetime.today() - datetime.timedelta(LOWER_DATE_LIMIT)

class Connection(mongoengine.EmbeddedDocument):
    http_if_none_match = mongoengine.StringField()
    http_if_modified_since = mongoengine.StringField()
    channel_id = mongoengine.StringField()

class User(auth.User):
    username = mongoengine.StringField(
        max_length=30,
        min_length=4,
        regex=r'^' + USERNAME_REGEX + r'$',
        required=True,
        verbose_name=_("username"),
        help_text=_("Minimal of 4 characters and maximum of 30. Letters, digits and @/./+/-/_ only."),
    )

    birthdate = fields.LimitedDateTimeField(upper_limit=upper_birthdate_limit, lower_limit=lower_birthdate_limit)
    gender = fields.GenderField()
    language = fields.LanguageField()

    profile_image = fields.ProfileImageField()

    facebook_id = mongoengine.IntField()
    facebook_token = mongoengine.StringField(max_length=150)
    facebook_link = mongoengine.StringField(max_length=100)

    twitter_id = mongoengine.IntField()
    twitter_token_key = mongoengine.StringField(max_length=150)
    twitter_token_secret = mongoengine.StringField(max_length=150)

    connections = mongoengine.ListField(mongoengine.EmbeddedDocumentField(Connection))
    connection_last_unsubscribe = mongoengine.DateTimeField()
    is_online = mongoengine.BooleanField(default=False)


    @models.permalink
    def get_absolute_url(self):
        return ('profile', (), {'username': self.username})

    def get_profile_url(self):
        return self.get_absolute_url()

    def get_image_url(self):
        # TODO: Save images after each login, so you don't have to contact facebook or twitter on each request

        if self.profile_image == 'twitter':
            twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
            twitter_auth.set_access_token(self.twitter_token_key, self.twitter_token_secret)
            return tweepy.API(twitter_auth).me().profile_image_url

        elif self.profile_image == 'facebook':
            return '%s?type=square' % utils.graph_api_url('%s/picture' % self.username)

        else:
            request = client.RequestFactory(**settings.DEFAULT_REQUEST).request()
            default_url = request.build_absolute_uri(staticfiles_storage.url(settings.DEFAULT_USER_IMAGE))
            if self.email:
                return 'https://secure.gravatar.com/avatar/%(email_hash)s?%(args)s' % {
                    'email_hash': hashlib.md5(self.email.lower()).hexdigest(),
                    'args': urllib.urlencode({
                        'default': default_url,
                        'size': 50,
                        }),
                    }
            else:
                return default_url
