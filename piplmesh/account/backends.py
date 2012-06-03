import json, urllib, urlparse

from django.conf import settings
from django.core import urlresolvers
from django.utils import crypto

from mongoengine import queryset
from mongoengine.django import auth
from mongoengine.queryset import DoesNotExist, OperationError

import tweepy

from piplmesh.account import models

LAZYUSER_USERNAME_TEMPLATE = 'guest-%s'

class MongoEngineBackend(auth.MongoEngineBackend):
    # TODO: Implement object permission support
    supports_object_permissions = False
    # TODO: Implement anonymous user backend
    supports_anonymous_user = False
    # TODO: Implement inactive user backend
    supports_inactive_user = False

    def authenticate(self, username, password):
        user = self.user_class.objects(username__iexact=username).first()
        if user:
            if password and user.check_password(password):
                return user
        return None

    def get_user(self, user_id):
        try:
            return self.user_class.objects.with_id(user_id)
        except self.user_class.DoesNotExist:
            return None

    @property
    def user_class(self):
        return models.User

class FacebookBackend(MongoEngineBackend):
    """
    Facebook authentication.
    """

    def authenticate(self, facebook_token, request):
        """
        Retrieves an access token and Facebook data. Determine if user already
        exists. If not, a new user is created. Finally, the user's Facebook
        data is saved.
        """

        fb, access_token = getFacebookData(facebook_token, request)
        # TODO: Check if id and other fields are returned
        # TODO: Move user retrieval/creation to User document/manager
        # TODO: get_or_create implementation has in fact a race condition, is this a problem?

        username = fb.get('username', fb.get('first_name') + fb.get('last_name'))
        i = 1
        user = ""
        while True:
            try:
                try:
                    user = self.user_class.objects.get(facebook_id=fb.get('id'))
                    user.facebook_token = access_token
                    user.save()
                    break
                except DoesNotExist:
                    user = request.user
                    user.facebook_id = fb.get('id')
                    user.username = username
                    user.first_name = fb.get('first_name')
                    user.last_name = fb.get('last_name')
                    user.email = fb.get('email')
                    user.gender = fb.get('gender')
                    user.facebook_link = fb.get('link')
                    user.facebook_token = access_token
                    user.save()
                    break
            except OperationError, e:
                msg = str(e)
                if 'E11000' in msg and 'duplicate key error' in msg and 'User' in msg:
                    username = fb.get('username', fb.get('first_name') + fb.get('last_name'))
                    username += str(i)
                    i+=1
                    continue
                else:
                    raise

        return user

class TwitterBackend(MongoEngineBackend):
    """
    Twitter authentication.
    """

    def authenticate(self, twitter_token, request):
        twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
        twitter_auth.set_access_token(twitter_token.key, twitter_token.secret)
        api = tweepy.API(twitter_auth)
        twitter_user = api.me()

        username = twitter_user.screen_name
        i = 1
        user = ""
        while True:
            try:
                try:
                    user = self.user_class.objects.get(twitter_id=twitter_user.id)
                    user.twitter_token_key = twitter_token.key
                    user.twitter_token_secret = twitter_token.secret
                    user.save()
                    break
                except DoesNotExist:
                    user = request.user
                    user.twitter_id = twitter_user.id
                    user.username = username
                    user.first_name = twitter_user.name
                    user.twitter_token_key = twitter_token.key
                    user.twitter_token_secret = twitter_token.secret
                    user.twitter_link = "http://twitter.com/#!/" + twitter_user.screen_name
                    user.save()
                    break
            except OperationError, e:
                msg = str(e)
                if 'E11000' in msg and 'duplicate key error' in msg and 'User' in msg:
                    username = twitter_user.screen_name
                    username += str(i)
                    i+=1
                    continue
                else:
                    raise

        return user

def getFacebookData(facebook_token, request):
    """
    This method gets data from Facebook and returns it.
    """

    args = {
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('facebook_callback')),
        'code': facebook_token,
        }

    # Retrieve access token
    url = urllib.urlopen('https://graph.facebook.com/oauth/access_token?%s' % urllib.urlencode(args)).read()
    response = urlparse.parse_qs(url)
    access_token = response['access_token'][-1]

    # Retrieve user's public profile information
    data = urllib.urlopen('https://graph.facebook.com/me?%s' % urllib.urlencode({'access_token': access_token}))
    fb = json.load(data)

    return fb, access_token

def facebookLink(facebook_token=None, request=None):
    """
    Method for linking account with Facebook.
    """

    # Retrieve data
    fb, access_token = getFacebookData(facebook_token, request)

    # Check if user with same facebook_id already exists and deletes him
    try:
        user = models.User.objects.get(facebook_id=fb.get('id'))
        user.delete()
    except DoesNotExist:
        pass

    # Save information to user
    request.user.facebook_id = fb.get('id')
    request.user.facebook_token = access_token
    request.user.facebook_link = fb.get('link')
    request.user.save()

    return None

def twitterLink(twitter_token=None, request=None):
    """
    Method for linking account with Twitter.
    """

    # Retrieve data
    twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
    twitter_auth.set_access_token(twitter_token.key, twitter_token.secret)
    api = tweepy.API(twitter_auth)
    twitter_user = api.me()

    # Check if user with same twitter_id already exists and deletes him
    try:
        user = models.User.objects.get(twitter_id=twitter_user.id)
        user.delete()
    except DoesNotExist:
        pass

    # Save information to user
    request.user.twitter_id = twitter_user.id
    request.user.twitter_token_key = twitter_token.key
    request.user.twitter_token_secret = twitter_token.secret
    request.user.twitter_link = "http://twitter.com/#!/" + twitter_user.screen_name
    request.user.save()

    return None

class LazyUserBackend(MongoEngineBackend):
    def authenticate(self):
        while True:
            try:
                username = LAZYUSER_USERNAME_TEMPLATE % crypto.get_random_string(6)
                user = self.user_class.objects.create(
                    username=username,
                )
                break
            except queryset.OperationError, e:
                msg = str(e)
                if 'E11000' in msg and 'duplicate key error' in msg and 'username' in msg:
                    continue
                raise

        return user
