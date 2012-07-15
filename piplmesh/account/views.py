import json, urllib, urlparse

from django import dispatch, http, shortcuts
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth import views as auth_views
from django.core import urlresolvers
from django.template import loader
from django.views import generic as generic_views
from django.views.generic import simple, edit as edit_views
from django.utils import crypto, timezone, translation
from django.utils.translation import ugettext_lazy as _

from pushserver import signals

from mongoengine import queryset

import tweepy

from piplmesh.account import backends, forms, models

FACEBOOK_SCOPE = 'email'
GOOGLE_SCOPE = 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile'

class FacebookLoginView(edit_views.FormView):
    """ 
    This view authenticates the user via Facebook.
    """

    template_name = 'user/password_check.html'
    form_class = forms.UserCurrentPasswordForm

    def get_form(self, form_class):
        return form_class(self.request.user, **self.get_form_kwargs())

    def get_success_url(self):
        args = {
            'client_id': settings.FACEBOOK_APP_ID,
            'scope': FACEBOOK_SCOPE,
            'redirect_uri': self.request.build_absolute_uri(urlresolvers.reverse('facebook_callback')),
        }
        return 'https://www.facebook.com/dialog/oauth?%s' % urllib.urlencode(args)

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated():
            return http.HttpResponseRedirect(self.get_success_url())
        return super(FacebookLoginView, self).post(request, *args, **kwargs)

class FacebookCallbackView(edit_views.FormView):
    """ 
    Authentication callback. Redirects user to LOGIN_REDIRECT_URL. 
    """

    template_name = 'user/password_change.html'
    form_class = forms.LinkChoiceForm
    choices = (('nothing',""),('overwrite',""),('unlink',""),('unlink_and_overwrite',""))
    fb_token = ""

    def get_form(self, form_class):
        return form_class(self.choices, self.fb_token, **self.get_form_kwargs())

    def get_success_url(self):
        # TODO: Redirect users to the page they initially came from
        return settings.FACEBOOK_LOGIN_REDIRECT

    def form_valid(self, form):
        choice = form.cleaned_data['choice']
        token = form.cleaned_data['token']
        facebook_data = json.load(urllib.urlopen('https://graph.facebook.com/me?%s' % urllib.urlencode({'access_token': token})))

        if choice == 'nothing':
            return super(FacebookCallbackView, self).form_valid(form)
        elif choice == 'unlink' or choice == 'unlink_and_overwrite':
            try:
                user = models.User.objects.get(facebook_profile_data__id=facebook_data.get('id'))
                user.facebook_access_token = None
                user.facebook_profile_data = None
                if user.profile_image == 'facebook':
                    user.profile_image = None
                user.save()
            except queryset.DoesNotExist:
                messages.success(self.request, _("An error occurred while trying to link your account with Facebook."))
                return super(FacebookCallbackView, self).form_valid(form)

        auth.authenticate(facebook_access_token=token, request=self.request)
        messages.success(self.request, _("You have successfully linked your account with Facebook."))
        return super(FacebookCallbackView, self).form_valid(form)

    def get(self, request, *args, **kwargs):
        # TODO: Add security measures to prevent attackers from sending a redirect to this url with a forged 'code' (you can use 'state' parameter to set a random nonce and store it into session)
        # TODO: Check if 'client_id' is same as ours
        if 'code' in request.GET:
            args = {
                'client_id': settings.FACEBOOK_APP_ID,
                'client_secret': settings.FACEBOOK_APP_SECRET,
                'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('facebook_callback')),
                'code': request.GET['code'],
                }

            # Retrieve access token
            response = urlparse.parse_qs(urllib.urlopen('https://graph.facebook.com/oauth/access_token?%s' % urllib.urlencode(args)).read())
            # TODO: Handle error, what if response does not contain access token?
            access_token = response['access_token'][0]
            facebook_data = json.load(urllib.urlopen('https://graph.facebook.com/me?%s' % urllib.urlencode({'access_token': access_token})))
            self.fb_token = access_token

            if request.user.is_authenticated():
                if request.user.facebook_profile_data:
                    if request.user.facebook_profile_data['id'] == facebook_data.get('id'):
                        messages.error(self.request, _("Your account is already linked with Facebook."))
                        return http.HttpResponseRedirect(self.get_success_url())
                    else:
                        try:
                            models.User.objects.get(facebook_profile_data__id=facebook_data.get('id'))
                            self.choices = (('nothing', _("Do nothing")),
                                            ('unlink_and_overwrite', _("Unlink other account and overwrite this account with new information")),
                                )
                            messages.error(self.request, _("There is already one account linked with this Facebook account and your account is already linked with another Facebook account."))
                            return super(FacebookCallbackView, self).get(request, *args, **kwargs)
                        except queryset.DoesNotExist:
                            self.choices=(('nothing', _("Do nothing")),
                                          ('overwrite', _("Overwrite account with new information")),
                                )
                            messages.error(self.request, _("Your account is already linked with another Facebook account."))
                            return super(FacebookCallbackView, self).get(request, *args, **kwargs)
                try:
                    models.User.objects.get(facebook_profile_data__id=facebook_data.get('id'))
                    self.choices=(('nothing', _("Do nothing")),
                                  ('unlink', _("Unlink other account")),
                        )
                    messages.error(self.request, _("There is already one account linked with this Facebook account."))
                    return super(FacebookCallbackView, self).get(request, *args, **kwargs)
                except queryset.DoesNotExist:
                    pass

                auth.authenticate(facebook_access_token=access_token, request=request)
                messages.success(request, _("You have successfully linked your account with Facebook."))
                return http.HttpResponseRedirect(self.get_success_url())

            else:
                user = auth.authenticate(facebook_access_token=access_token, request=request)
                assert user.is_authenticated()
                auth.login(request, user)
                if not user.password:
                    messages.error(request, _("Before proceeding please set up your password."))
                    return shortcuts.redirect('password_create')
                return http.HttpResponseRedirect(self.get_success_url())
        else:
            # TODO: Message user that they have not been logged in because they cancelled the Facebook app
            # TODO: Use information provided by Facebook as to why the login was not successful
            return shortcuts.redirect('home')

class FacebookUnlinkView(generic_views.RedirectView):
    """
    This view unlinks account with Facebook.
    """

    permanent = False
    # TODO: Redirect users to the page they initially came from
    url = urlresolvers.reverse_lazy('home')

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated():
            return shortcuts.redirect('login')
        if not request.user.facebook_profile_data:
            messages.error(self.request, _("Your account is not yet linked with Facebook."))
        else:
            request.user.facebook_access_token = None
            request.user.facebook_profile_data = None
            if request.user.profile_image == 'facebook':
                request.user.profile_image = None
            request.user.save()
        return super(FacebookUnlinkView, self).get(request, *args, **kwargs)


class TwitterLoginView(edit_views.FormView):
    """
    This view authenticates the user via Twitter.
    """

    template_name = 'user/password_check.html'
    form_class = forms.UserCurrentPasswordForm

    def get_form(self, form_class):
        return form_class(self.request.user, **self.get_form_kwargs())

    def get_success_url(self):
        twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET, self.request.build_absolute_uri(urlresolvers.reverse('twitter_callback')))

    def get_redirect_url(self, **kwargs):
        twitter_auth = tweepy.OAuthHandler(
            settings.TWITTER_CONSUMER_KEY,
            settings.TWITTER_CONSUMER_SECRET,
            self.request.build_absolute_uri(urlresolvers.reverse('twitter_callback')),
        )

        redirect_url = twitter_auth.get_authorization_url(signin_with_twitter=True)
        self.request.session['request_token'] = twitter_auth.request_token
        return redirect_url

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated():
            return http.HttpResponseRedirect(self.get_success_url())
        return super(TwitterLoginView, self).post(request, *args, **kwargs)

class TwitterCallbackView(generic_views.RedirectView):
    """
    Authentication callback. Redirects user to TWITTER_LOGIN_REDIRECT.
    """

    permanent = False
    # TODO: Redirect users to the page they initially came from
    url = settings.TWITTER_LOGIN_REDIRECT

    def get(self, request, *args, **kwargs):
        if 'oauth_verifier' in request.GET:
            oauth_verifier = request.GET['oauth_verifier']
            twitter_auth = tweepy.OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
            request_token = request.session.pop('request_token')
            assert request_token.key == request.GET['oauth_token']
            twitter_auth.set_request_token(request_token.key, request_token.secret)
            twitter_auth.get_access_token(verifier=oauth_verifier)

            if request.user.is_authenticated():
                if request.user.twitter_id:
                    messages.error(self.request, _("Your account is already linked with Twitter."))
                else:
                    backends.twitterLink(twitter_token=twitter_auth.access_token, request=request)
                    messages.success(request, _("You have successfully linked your account with Twitter."))
            else:
                user = auth.authenticate(twitter_token=twitter_auth.access_token, request=request)
                assert user.is_authenticated()
                auth.login(request, user)
                if not user.password:
                    messages.error(request, _("Before proceeding please set up your password."))
                    return shortcuts.redirect('password_create')


            user = auth.authenticate(twitter_access_token=twitter_auth.access_token, request=request)
            assert user.is_authenticated()

            auth.login(request, user)


            return super(TwitterCallbackView, self).get(request, *args, **kwargs)
        else:
            # TODO: Message user that they have not been logged in because they cancelled the twitter app
            # TODO: Use information provided from twitter as to why the login was not successful
            return super(TwitterCallbackView, self).get(request, *args, **kwargs)

class TwitterUnlinkView(generic_views.RedirectView):
    """
    This view unlinks account with Twitter.
    """

    permanent = False
    # TODO: Redirect users to the page they initially came from
    url = settings.TWITTER_LOGIN_REDIRECT

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated():
            return shortcuts.redirect('login')
        if not request.user.twitter_profile_data:
            messages.error(self.request, _("Your account is not yet linked with Twitter."))
        else:
            request.user.twitter_profile_data = None
            request.user.twitter_access_token = None
            request.user.save()
            if request.user.profile_image == 'twitter':
                request.user.profile_image = None
            request.user.save()
        return super(TwitterUnlinkView, self).get(request, *args, **kwargs)

class GoogleLoginView(generic_views.RedirectView):
    """
    This view authenticates the user via Google.
    """

    permanent = False

    def get_redirect_url(self, **kwargs):
        args = {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'scope': GOOGLE_SCOPE,
            'redirect_uri': self.request.build_absolute_uri(urlresolvers.reverse('google_callback')),
            'response_type': 'code',
            'access_type': 'online',
            'approval_prompt': 'auto',
        }
        return 'https://accounts.google.com/o/oauth2/auth?%s' % urllib.urlencode(args)

class GoogleCallbackView(generic_views.RedirectView):
    """
    Authentication callback. Redirects user to GOOGLE_REDIRECT_URL.
    """

    url = settings.GOOGLE_LOGIN_REDIRECT

    def get(self, request, *args, **kwargs):
        # TODO: Add security measures to prevent attackers from sending a redirect to this url with a forged 'code' (you can use 'state' parameter to set a random nonce and store it into session)

        if 'code' in request.GET:
            args = {
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('google_callback')),
                'code': request.GET['code'],
                'grant_type': 'authorization_code',
            }

            response = json.load(urllib.urlopen('https://accounts.google.com/o/oauth2/token', urllib.urlencode(args)))
            # TODO: Handle error, what if response does not contain access token?
            access_token = response['access_token']

            user = auth.authenticate(google_access_token=access_token, request=request)
            assert user.is_authenticated()

            auth.login(request, user)

            return super(GoogleCallbackView, self).get(request, *args, **kwargs)
        else:
            # TODO: Message user that they have not been logged in because they cancelled the Google app
            # TODO: Use information provided from Google as to why the login was not successful
            return super(GoogleCallbackView, self).get(request, *args, **kwargs)

class FoursquareLoginView(generic_views.RedirectView):
    """
    This view authenticates the user via Foursquare.
    """

    permanent = False

    def get_redirect_url(self, **kwargs):
        args = {
            'client_id': settings.FOURSQUARE_CLIENT_ID,
            'redirect_uri': self.request.build_absolute_uri(urlresolvers.reverse('foursquare_callback')),
            'response_type': 'code',
        }
        return 'https://foursquare.com/oauth2/authenticate?%s' % urllib.urlencode(args)

class FoursquareCallbackView(generic_views.RedirectView):
    """
    Authentication callback. Redirects user to LOGIN_REDIRECT_URL.
    """

    permanent = False
    # TODO: Redirect users to the page they initially came from
    url = settings.FOURSQUARE_LOGIN_REDIRECT

    def get(self, request, *args, **kwargs):
        if 'code' in request.GET:
            args = {
                'client_id': settings.FOURSQUARE_CLIENT_ID,
                'client_secret': settings.FOURSQUARE_CLIENT_SECRET,
                'redirect_uri': request.build_absolute_uri(urlresolvers.reverse('foursquare_callback')),
                'code': request.GET['code'],
                'grant_type': 'authorization_code',
            }

            response = json.load(urllib.urlopen('https://foursquare.com/oauth2/access_token', urllib.urlencode(args)))
            # TODO: Handle error, what if response does not contain access token?
            access_token = response['access_token']

            user = auth.authenticate(foursquare_access_token=access_token, request=request)
            assert user.is_authenticated()

            auth.login(request, user)

            return super(FoursquareCallbackView, self).get(request, *args, **kwargs)
        else:
            # TODO: Message user that they have not been logged in because they cancelled the foursquare app
            # TODO: Use information provided from foursquare as to why the login was not successful
            return super(FoursquareCallbackView, self).get(request, *args, **kwargs)

class RegistrationView(edit_views.FormView):
    """
    This view checks if form data are valid, saves new user.

    New user is authenticated, logged in and redirected to home page.
    """

    template_name = 'user/registration.html'
    # TODO: Redirect users to the page they initially came from
    success_url = urlresolvers.reverse_lazy('home')
    form_class = forms.RegistrationForm

    def form_valid(self, form):

        user = self.request.user
        user.username = form.cleaned_data['username']
        user.first_name = form.cleaned_data['first_name']
        user.last_name = form.cleaned_data['last_name']
        user.email = form.cleaned_data['email']
        user.gender = form.cleaned_data['gender'] or None
        user.birthdate = form.cleaned_data['birthdate']
        user.set_password(form.cleaned_data['password2'])
        user.lazyuser_username = False
        user.save()

        # We update user with authentication data
        newuser = auth.authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password2'])
        assert newuser is not None, form.cleaned_data['username']
        auth.login(self.request, newuser)
        messages.success(self.request, _("Registration has been successful."))
        return super(RegistrationView, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            return simple.redirect_to(request, url=self.get_success_url(), permanent=False)
        return super(RegistrationView, self).dispatch(request, *args, **kwargs)

class AccountChangeView(edit_views.FormView):
    """
    This view displays form for updating user account. It checks if all fields are valid and updates it.
    """

    template_name = 'user/account.html'
    form_class = forms.AccountChangeForm
    success_url = urlresolvers.reverse_lazy('account')

    def form_valid(self, form):
        user = self.request.user

        user.first_name=form.cleaned_data['first_name']
        user.last_name=form.cleaned_data['last_name']
        user.email=form.cleaned_data['email']
        user.gender=form.cleaned_data['gender'] or None
        user.birthdate=form.cleaned_data['birthdate']
        user.profile_image=form.cleaned_data['profile_image']

        user.save()
        messages.success(self.request, _("Your account has been successfully updated."))
        return super(AccountChangeView, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.password:
            messages.error(request, _("Before proceeding to your account page, you must set up your password."))
            return shortcuts.redirect('password_create')
        return super(AccountChangeView, self).dispatch(request, *args, **kwargs)

    def get_form(self, form_class):
        return form_class(self.request.user, **self.get_form_kwargs())

    def get_initial(self):
        return {
            'first_name': self.request.user.first_name,
            'last_name': self.request.user.last_name,
            'email': self.request.user.email,
            'gender': self.request.user.gender,
            'birthdate': self.request.user.birthdate,
            'profile_image': self.request.user.profile_image,
        }

class PasswordCreateView(edit_views.FormView):
    """
    This view displays form for creating password.
    """

    template_name = 'user/password_create.html'
    form_class = forms.UserPasswordForm
    success_url = urlresolvers.reverse_lazy('account')

    def form_valid(self, form):
        self.request.user.set_password(form.cleaned_data['password1'])
        messages.success(self.request, _("You have successfully set your password."))
        return super(PasswordCreateView, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if request.user.password:
            messages.error(request, _("You already have password set."))
            return shortcuts.redirect('home')
        return super(PasswordCreateView, self).dispatch(request, *args, **kwargs)

class PasswordChangeView(edit_views.FormView):
    """
    This view displays form for changing password.
    """

    template_name = 'user/password_change.html'
    form_class = forms.PasswordChangeForm
    success_url = urlresolvers.reverse_lazy('account')

    def form_valid(self, form):
        self.request.user.set_password(form.cleaned_data['password1'])
        messages.success(self.request, _("Your password has been successfully changed."))
        return super(PasswordChangeView, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        # TODO: Is this really the correct check? What is user is logged through third-party authentication, but still does not have current password - is not then changing password the same as registration?
        if not request.user.is_authenticated():
            return shortcuts.redirect('login')
        return super(PasswordChangeView, self).dispatch(request, *args, **kwargs)

    def get_form(self, form_class):
        return form_class(self.request.user, **self.get_form_kwargs())

class EmailConfirmationSendToken(edit_views.FormView):
    template_name = 'user/email_confirmation_send_token.html'
    form_class = forms.EmailConfirmationSendTokenForm
    success_url = urlresolvers.reverse_lazy('account')

    def form_valid(self, form):
        user = self.request.user

        confirmation_token = crypto.get_random_string(20)
        context = {
            'CONFIRMATION_TOKEN_VALIDITY': models.CONFIRMATION_TOKEN_VALIDITY,
            'EMAIL_SUBJECT_PREFIX': settings.EMAIL_SUBJECT_PREFIX,
            'SITE_NAME': settings.SITE_NAME,
            'confirmation_token': confirmation_token,
            'email_address': user.email,
            'request': self.request,
            'user': user,
        }

        subject = loader.render_to_string('user/confirmation_email_subject.txt', context)
        # Email subject *must not* contain newlines
        subject = ''.join(subject.splitlines())
        email = loader.render_to_string('user/confirmation_email.txt', context)

        user.email_confirmation_token = models.EmailConfirmationToken(value=confirmation_token)
        user.save()
        user.email_user(subject, email)

        messages.success(self.request, _("Confirmation e-mail has been sent to your e-mail address."))
        return super(EmailConfirmationSendToken, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        # TODO: Allow e-mail address confirmation only if user has e-mail address defined
        return super(EmailConfirmationSendToken, self).dispatch(request, *args, **kwargs)

class EmailConfirmationProcessToken(generic_views.FormView):
    template_name = 'user/email_confirmation_process_token.html'
    form_class = forms.EmailConfirmationProcessTokenForm
    success_url = urlresolvers.reverse_lazy('account')

    def form_valid(self, form):
        user = self.request.user
        user.email_confirmed = True
        user.save()
        messages.success(self.request, _("You have successfully confirmed your e-mail address."))
        return super(EmailConfirmationProcessToken, self).form_valid(form)

    def get_initial(self):
        return {
            'confirmation_token': self.kwargs.get('confirmation_token'),
        }

    def dispatch(self, request, *args, **kwargs):
        # TODO: Allow e-mail address confirmation only if user has e-mail address defined
        # TODO: Check if currently logged in user is the same as the user requested the confirmation
        return super(EmailConfirmationProcessToken, self).dispatch(request, *args, **kwargs)

    def get_form(self, form_class):
        return form_class(self.request.user, **self.get_form_kwargs())

def logout(request):
    """
    After user logouts, redirect her back to the page she came from.
    """

    if request.method != 'POST':
        return http.HttpResponseBadRequest()

    url = request.POST.get(auth.REDIRECT_FIELD_NAME)
    return auth_views.logout_then_login(request, url)

def set_language(request):
    """
    Redirect to a given url while setting the chosen language in the user
    setting. The url and the language code need to be specified in the request
    parameters.

    Since this view changes how the user will see the rest of the site, it must
    only be accessed as a POST request. If called as a GET request, it will
    redirect to the page in the request (the 'next' parameter) without changing
    any state.
    """

    next = request.REQUEST.get('next', None)
    if not next:
        next = request.META.get('HTTP_REFERER', None)
    if not next:
        next = '/'
    response = http.HttpResponseRedirect(next)
    if request.method == 'POST':
        lang_code = request.POST.get('language', None)
        if lang_code and translation.check_for_language(lang_code):
            # We reload to make sure user object is recent
            request.user.reload()
            request.user.language = lang_code
            request.user.save()
    return response

@dispatch.receiver(signals.channel_subscribe)
def process_channel_subscribe(sender, request, channel_id, **kwargs):
    request.user.update(
        push__connections={
            'http_if_none_match': request.META['HTTP_IF_NONE_MATCH'],
            'http_if_modified_since': request.META['HTTP_IF_MODIFIED_SINCE'],
            'channel_id': channel_id,
        }
    )

@dispatch.receiver(signals.channel_unsubscribe)
def process_channel_unsubscribe(sender, request, channel_id, **kwargs):
    models.User.objects(
        id=request.user.id,
        connections__http_if_none_match=request.META['HTTP_IF_NONE_MATCH'],
        connections__http_if_modified_since=request.META['HTTP_IF_MODIFIED_SINCE'],
        connections__channel_id=channel_id,
    ).update_one(unset__connections__S=1)

    request.user.update(
        pull__connections=None,
        set__connection_last_unsubscribe=timezone.now(),
    )
