import datetime, hashlib, tweepy, urllib

from django.conf import settings
from django.contrib.auth import hashers, models as auth_models
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core import mail
from django.db import models
from django.test import client
from django.utils import timezone
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

class TwitterAccessToken(mongoengine.EmbeddedDocument):
    key = mongoengine.StringField(max_length=150)
    secret = mongoengine.StringField(max_length=150)

class User(auth.User):
    username = mongoengine.StringField(
        max_length=30,
        min_length=4,
        regex=r'^' + USERNAME_REGEX + r'$',
        required=True,
        verbose_name=_("username"),
        help_text=_("Minimal of 4 characters and maximum of 30. Letters, digits and @/./+/-/_ only."),
    )
    lazyuser_username = mongoengine.BooleanField(default=True)

    birthdate = fields.LimitedDateTimeField(upper_limit=upper_birthdate_limit, lower_limit=lower_birthdate_limit)
    gender = fields.GenderField()
    language = fields.LanguageField()


    profile_image = fields.ProfileImageField()

    facebook_access_token = mongoengine.StringField(max_length=150)
    facebook_profile_data = mongoengine.DictField()

    twitter_access_token = mongoengine.EmbeddedDocumentField(TwitterAccessToken)
    twitter_profile_data = mongoengine.DictField()
    twitter_name = mongoengine.StringField(max_length=100)

    google_access_token = mongoengine.StringField(max_length=150)
    google_profile_data = mongoengine.DictField()

    foursquare_access_token = mongoengine.StringField(max_length=150)
    foursquare_profile_data = mongoengine.DictField()

    connections = mongoengine.ListField(mongoengine.EmbeddedDocumentField(Connection))
    connection_last_unsubscribe = mongoengine.DateTimeField()
    is_online = mongoengine.BooleanField(default=False)

    @models.permalink
    def get_absolute_url(self):
        return ('profile', (), {'username': self.username})

    def get_profile_url(self):
        return self.get_absolute_url()

    def is_anonymous(self):
        return not self.is_authenticated()

    def is_authenticated(self):
        # TODO: Check if *_data fields are really false if not linked with third-party authentication
        return self.has_usable_password() or self.facebook_profile_data or self.twitter_profile_data or self.google_profile_data or self.foursquare_profile_data

    def check_password(self, raw_password):
        def setter(raw_password):
            self.set_password(raw_password)
        return hashers.check_password(raw_password, self.password, setter)

    def set_unusable_password(self):
        self.password = hashers.make_password(None)
        self.save()
        return self

    def has_usable_password(self):
        return hashers.is_password_usable(self.password)

    def email_user(self, subject, message, from_email=None):
        mail.send_mail(subject, message, from_email, [self.email])

    def get_twitter_link(self):
        return 'http://twitter.com/#!/%s' % self.twitter_name

    def get_image_url(self):

        # TODO: Save images after each login, so you don't have to contact facebook or twitter on each request

        if self.profile_image == 'twitter' and self.twitter_profile_data and 'profile_image_url' in self.twitter_profile_data:
            return self.twitter_profile_data['profile_image_url']

        elif self.profile_image == 'facebook':
            return '%s?type=square' % utils.graph_api_url('%s/picture' % self.facebook_id)

        elif self.profile_image == 'foursquare' and self.foursquare_profile_data and 'photo' in self.foursquare_profile_data:
            return self.foursquare_profile_data['photo']

        elif self.profile_image == 'google' and self.google_profile_data and 'picture' in self.google_profile_data:
            return self.google_profile_data['picture']

        elif self.email:
            request = client.RequestFactory(**settings.DEFAULT_REQUEST).request()
            default_url = request.build_absolute_uri(staticfiles_storage.url(settings.DEFAULT_USER_IMAGE))

            return 'https://secure.gravatar.com/avatar/%(email_hash)s?%(args)s' % {
                'email_hash': hashlib.md5(self.email.lower()).hexdigest(),
                'args': urllib.urlencode({
                    'default': default_url,
                    'size': 50,
                }),
            }

        else:
            return staticfiles_storage.url(settings.DEFAULT_USER_IMAGE)

    @classmethod
    def create_user(cls, username, email=None, password=None):
        now = timezone.now()
        if not username:
            raise ValueError("The given username must be set")
        email = auth_models.UserManager.normalize_email(email)
        user = cls(
            username=username,
            email=email or None,
            is_staff=False,
            is_active=True,
            is_superuser=False,
            last_login=now,
            date_joined=now,
        )
        user.set_password(password)
        user.save()
        return user
