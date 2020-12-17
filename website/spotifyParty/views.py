from django.shortcuts import render

from .models import PartySession


def index(request):
    if request.method == 'POST':
        submitted_session_code = request.POST.get('session_code')
        active_party_session = PartySession.objects.filter(session_code=submitted_session_code)
        if active_party_session:
            return render(request, 'index.html', {'error_msg': 'Your PartySession was found in the database. Unfortunately live Sessions are not yet implemented'})
        return render(request, 'index.html', {'error_msg': 'Sorry, no matching PartySession was found.'})
    return render(request, 'index.html', {'error_msg': ''})


def settings(request):
    pass


# view to be implemented with DjangoChannels
def party_session(request):
    pass
