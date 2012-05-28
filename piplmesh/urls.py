from django.conf import settings
from django.conf.urls.defaults import patterns, include, url

from tastypie import api

from piplmesh.account import models, views as account_views
from piplmesh.api import resources
from piplmesh.frontend import views as frontend_views

v1_api = api.Api(api_name='v1')
v1_api.register(resources.UserResource())
v1_api.register(resources.PostResource())

js_info_dict = {
    'packages': (
        'django.conf',
        'piplmesh.frontend',
    ),
}

urlpatterns = patterns('',
    url('^$', frontend_views.HomeView.as_view(), name='home'),

    url(r'^search/', frontend_views.SearchView.as_view(), name='search'),
    url(r'^i18n/', include('django.conf.urls.i18n')),
    url(r'^jsi18n/$', 'django.views.i18n.javascript_catalog', js_info_dict),
    url(r'^passthrough/', include('pushserver.urls')),

    # Registration, login, logout
    url(r'^register/$', account_views.RegistrationView.as_view(), name='registration'),
    url(r'^login/$', 'django.contrib.auth.views.login', {'template_name': 'user/login.html'}, name='login'),
    url(r'^logout/$', account_views.logout, name='logout'),

    # Facebook
    url(r'^facebook/login/$', account_views.FacebookLoginView.as_view(), name='facebook_login'),
    url(r'^facebook/callback/$', account_views.FacebookCallbackView.as_view(), name='facebook_callback'),
    url(r'^facebook/linkAccount/$', account_views.FacebookLinkView.as_view(), name='facebook_link'),
    url(r'^facebook/linkAccountCallback/$', account_views.FacebookLinkCallbackView.as_view(), name='facebook_link_callback'),
    url(r'^facebook/unlinkAccount/$', account_views.FacebookUnlinkView.as_view(), name='facebook_unlink'),

    # Twitter
    url(r'^twitter/login/$', account_views.TwitterLoginView.as_view(), name='twitter_login'),
    url(r'^twitter/callback/$', account_views.TwitterCallbackView.as_view(), name='twitter_callback'),

    # Profile, Account
    url(r'^user/(?P<username>' + models.USERNAME_REGEX + ')/$', frontend_views.UserView.as_view(), name='user'),
    url(r'^account/$', account_views.AccountChangeView.as_view(), name='account'),
    url(r'^account/password/change/$', account_views.PasswordChangeView.as_view(), name='password_change'),
    url(r'^account/password/create/$', account_views.PasswordCreateView.as_view(), name='password_create'),

    # RESTful API
    url(r'^api/', include(v1_api.urls)),
)

handler403 = frontend_views.forbidden_view
handler404 = 'django.views.defaults.page_not_found'
handler500 = 'django.views.defaults.server_error'

if getattr(settings, 'DEBUG', False):
    urlpatterns += patterns('',
        (r'^403/$', handler403),
        (r'^404/$', handler404),
        (r'^500/$', handler500),
    )
