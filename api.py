"""                                     .. 
Jutda Helpdesk - A Django powered ticket tracker for small enterprise.

(c) Copyright 2008 Jutda. All Rights Reserved. See LICENSE for details.

api.py - Wrapper around API calls, and core functions to provide complete
         API to third party applications.

The API documentation can be accessed by visiting http://helpdesk/api/help/ 
(obviously, substitute helpdesk for your Jutda Helpdesk URI), or by reading
through templates/helpdesk/api_help.html.
"""
from datetime import datetime
import simplejson

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import loader, Context
from django import newforms as forms

from helpdesk.lib import send_multipart_mail
from helpdesk.models import Ticket, Queue, FollowUp
from helpdesk.forms import TicketForm

STATUS_OK = 200

STATUS_ERROR = 400
STATUS_ERROR_NOT_FOUND = 404
STATUS_ERROR_PERMISSIONS = 403
STATUS_ERROR_BADMETHOD = 405

def api(request, method):
    if method == 'help':
        """ Regardless of any other paramaters, we provide a help screen
        to the user if they requested one. """
        return render_to_response('helpdesk/api_help.html')

    """
    If the user isn't looking for help, then we enforce a few conditions:
        * The request must be sent via HTTP POST
        * The request must contain a 'user' and 'password' which
          must be valid users
        * The method must match one of the public methods of the API class.
    """
    
    if request.method != 'POST':
        return api_return(STATUS_ERROR_BADMETHOD)
    
    request.user = authenticate(username=request.POST.get('user', False), password=request.POST.get('password'))
    if request.user is None:
        return api_return(STATUS_ERROR_PERMISSIONS)
    
    api = API(request)
    if hasattr(api, 'api_public_%s' % method):
        return getattr(api, 'api_public_%s' % method)()

    return api_return(STATUS_ERROR)


def api_return(status, text='', json=False):
    content_type = 'text/plain'
    if status == STATUS_OK and json:
        content_type = 'text/json'
    
    if text is None:
        if status == STATUS_ERROR:
            text = 'Error'
        elif status == STATUS_ERROR_NOT_FOUND:
            text = 'Resource Not Found'
        elif status == STATUS_ERROR_PERMISSIONS:
            text = 'Invalid username or password'
        elif status == STATUS_ERROR_BADMETHOD:
            text = 'Invalid request method'
        elif status == STATUS_OK:
            text = 'OK'
    r = HttpResponse(status=status, content=text, content_type=content_type)
    
    if status == STATUS_ERROR_BADMETHOD:
        r.Allow = 'POST'
    return r


class API:
    def __init__(self, request):
        self.request = request

    def api_public_create_ticket(self):

        form = TicketForm(self.request.POST)
        form.fields['queue'].choices = [[q.id, q.title] for q in Queue.objects.all()]
        form.fields['assigned_to'].choices = [[u.id, u.username] for u in User.objects.filter(is_active=True)]
        if form.is_valid():
            ticket = form.save(user=self.request.user)
            return api_return(STATUS_OK, "%s" % ticket.id)
        else:
            return api_return(STATUS_ERROR, text=form.errors.as_text())

    
    def api_public_list_queues(self):
        return api_return(STATUS_OK, simplejson.dumps([{"id": "%s" % q.id, "title": "%s" % q.title} for q in Queue.objects.all()]), json=True)
    
    
    def api_public_find_user(self):
        username = self.request.POST.get('username', False)
        try:
            u = User.objects.get(username=username)
            return api_return(STATUS_OK, "%s" % u.id)
        except:
            return api_return(STATUS_ERROR, "Invalid username provided")


    def api_public_delete_ticket(self):
        if not self.request.POST.get('confirm', False):
            return api_return(STATUS_ERROR, "No confirmation provided")

        try:
            ticket = Ticket.objects.get(id=self.request.POST.get('ticket', False))
        except:
            return api_return(STATUS_ERROR, "Invalid ticket ID")

        ticket.delete()
        return api_return(STATUS_OK)
        
    
    def api_public_hold_ticket(self):
        try:
            ticket = Ticket.objects.get(id=self.request.POST.get('ticket', False))
        except:
            return api_return(STATUS_ERROR, "Invalid ticket ID")

        ticket.on_hold = True
        ticket.save()

        return api_return(STATUS_OK)

        
    def api_public_unhold_ticket(self):
        try:
            ticket = Ticket.objects.get(id=self.request.POST.get('ticket', False))
        except:
            return api_return(STATUS_ERROR, "Invalid ticket ID")

        ticket.on_hold = False
        ticket.save()

        return api_return(STATUS_OK)


    def api_public_add_followup(self):
        try:
            ticket = Ticket.objects.get(id=self.request.POST.get('ticket', False))
        except:
            return api_return(STATUS_ERROR, "Invalid ticket ID")

        message = self.request.POST.get('message', None)
        public = self.request.POST.get('public', 'n')

        if public not in ['y', 'n']:
            return api_return(STATUS_ERROR, "Invalid 'public' flag")

        if not message:
            return api_return(STATUS_ERROR, "Blank message")
        
        f = FollowUp(ticket=ticket, date=datetime.now(), comment=message, user=self.request.user, title='Comment Added')
        if public:
            f.public = True
        f.save()
        
        context = {
            'ticket': ticket,
            'queue': ticket.queue,
            'comment': f.comment,
        }

        subject = '%s %s (Updated)' % (ticket.ticket, ticket.title)

        if public and ticket.submitter_email:
            template = 'helpdesk/emails/submitter_updated'
            send_multipart_mail(template, context, subject, ticket.submitter_email, ticket.queue.from_address)
        
        if ticket.queue.updated_ticket_cc:
            template_cc = 'helpdesk/emails/cc_updated'
            send_multipart_mail(template_cc, context, subject, q.updated_ticket_cc, ticket.queue.from_address)
        
        if ticket.assigned_to and self.request.user != ticket.assigned_to:
            template_owner = 'helpdesk/emails/owner_updated'
            send_multipart_mail(template_owner, context, subject, t.assigned_to.email, ticket.queue.from_address)

        ticket.save()

        return api_return(STATUS_OK)


    def api_public_resolve(self):
        try:
            ticket = Ticket.objects.get(id=self.request.POST.get('ticket', False))
        except:
            return api_return(STATUS_ERROR, "Invalid ticket ID")

        resolution = self.request.POST.get('resolution', None)

        if not resolution:
            return api_return(STATUS_ERROR, "Blank resolution")
        
        f = FollowUp(ticket=ticket, date=datetime.now(), comment=resolution, user=self.request.user, title='Resolved', public=True)
        f.save()
        
        context = {
            'ticket': ticket,
            'queue': ticket.queue,
            'resolution': f.comment,
        }
        
        subject = '%s %s (Resolved)' % (ticket.ticket, ticket.title)

        if ticket.submitter_email:
            template = 'helpdesk/emails/submitter_resolved'
            send_multipart_mail(template, context, subject, ticket.submitter_email, ticket.queue.from_address)
        
        if ticket.queue.updated_ticket_cc:
            template_cc = 'helpdesk/emails/cc_resolved'
            send_multipart_mail(template_cc, context, subject, q.updated_ticket_cc, ticket.queue.from_address)
        
        if ticket.assigned_to and self.request.user != ticket.assigned_to:
            template_owner = 'helpdesk/emails/owner_resolved'
            send_multipart_mail(template_owner, context, subject, t.assigned_to.email, ticket.queue.from_address)

        ticket.resoltuion = f.comment
        ticket.status = Ticket.RESOLVED_STATUS

        ticket.save()

        return api_return(STATUS_OK)
