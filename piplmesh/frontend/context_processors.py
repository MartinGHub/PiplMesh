from django.conf import settings
from django.contrib import auth

def global_vars(request):
    """
    Adds global context variables to the context.
    """

    return {
        'SEARCH_ENGINE_UNIQUE_ID': settings.SEARCH_ENGINE_UNIQUE_ID,
        'REDIRECT_FIELD_NAME': auth.REDIRECT_FIELD_NAME,
        'REDIRECT_TO': request.POST.get(auth.REDIRECT_FIELD_NAME),
    }