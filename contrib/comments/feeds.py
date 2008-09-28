from django.conf import settings
from django.contrib.syndication.feeds import Feed
from django.contrib.sites.models import Site
from django.contrib import comments

class LatestCommentFeed(Feed):
    """Feed of latest comments on the current site."""

    def title(self):
        if not hasattr(self, '_site'):
            self._site = Site.objects.get_current()
        return u"%s comments" % self._site.name

    def link(self):
        if not hasattr(self, '_site'):
            self._site = Site.objects.get_current()
        return "http://%s/" % (self._site.domain)

    def description(self):
        if not hasattr(self, '_site'):
            self._site = Site.objects.get_current()
        return u"Latest comments on %s" % self._site.name

    def items(self):
        qs = comments.get_model().objects.filter(
            site__pk = settings.SITE_ID,
            is_public = True,
            is_removed = False,
        )
        if getattr(settings, 'COMMENTS_BANNED_USERS_GROUP', None):
            where = ['user_id NOT IN (SELECT user_id FROM auth_users_group WHERE group_id = %s)']
            params = [settings.COMMENTS_BANNED_USERS_GROUP]
            qs = qs.extra(where=where, params=params)
        return qs.order_by('-submit_date')[:40]
        
    def item_pubdate(self, item):
        return item.submit_date
