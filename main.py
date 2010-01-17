import os
import hashlib
import base64
import urllib
import logging
import feedparser
from google.appengine.api import xmpp
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext.webapp import xmpp_handlers
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import urlfetch


SUPERFEEDR_LOGIN = ""
SUPERFEEDR_PASSWORD = ""

##
# the function that sends subscriptions/unsubscriptions to Superfeedr
def superfeedr(mode, subscription):
  post_data = {
      'hub.mode' : mode,
      'hub.callback' : "http://notifixlite.appspot.com/hubbub/" + subscription.key().name(),
      'hub.topic' : subscription.feed, 
      'hub.verify' : 'sync',
      'hub.verify_token' : '',
  }
  base64string = base64.encodestring('%s:%s' % (SUPERFEEDR_LOGIN, SUPERFEEDR_PASSWORD))[:-1]
  form_data = urllib.urlencode(post_data)
  result = urlfetch.fetch(url="http://superfeedr.com/hubbub",
                  payload=form_data,
                  method=urlfetch.POST,
                  headers={"Authorization": "Basic "+ base64string, 'Content-Type': 'application/x-www-form-urlencoded'},
                  deadline=10)
  logging.info('Result of %s to %s => %s (%d)',mode, subscription.feed, result.content, result.status_code )
  
  return result


##
# The subscription model that matches a feed and a jid.
class Subscription(db.Model):
  feed = db.LinkProperty(required=True)
  jid = db.StringProperty(required=True)
  created_at = db.DateTimeProperty(required=True, auto_now_add=True)

##
# The web app interface
class MainPage(webapp.RequestHandler):
  
  def Render(self, template_file, template_values = {}):
     path = os.path.join(os.path.dirname(__file__), 'templates', template_file)
     self.response.out.write(template.render(path, template_values))
  
  def get(self):
    self.Render("index.html")

##
# The HubbubSusbcriber
class HubbubSubscriber(webapp.RequestHandler):

  ##
  # Called upon notification
  def post(self, feed_sekret):
    subscription = Subscription.get_by_key_name(feed_sekret)
    if(subscription == None):
      self.response.set_status(404)
      self.response.out.write("Sorry, no feed."); 
      
    else:
      body = self.request.body.decode('utf-8')
      data = feedparser.parse(self.request.body)
      
      logging.info('Found %d entries in %s', len(data.entries), subscription.feed)
    
      for entry in data.entries:
        link = entry.get('link', '')
        title = entry.get('title', '')
        logging.info('Found entry with title = "%s", '
                   'link = "%s"',
                   title, link)
        user_address = subscription.jid
        msg = title + "\n" + link
        status_code = xmpp.send_message(user_address, msg)
          
      self.response.set_status(200)
      self.response.out.write("Aight. Saved."); 
  
  def get(self, feed_sekret):
    self.response.out.write(self.request.get('hub.challenge'))
    self.response.set_status(200)
  
##
# The XMPP App interface
class XMPPHandler(xmpp_handlers.CommandHandler):
  
  # Asking to subscribe to a feed
  def subscribe_command(self, message=None):
    message = xmpp.Message(self.request.POST)
    subscriber = message.sender.rpartition("/")[0]
    subscription = Subscription(key_name=hashlib.sha224(message.arg + subscriber).hexdigest(), feed=message.arg, jid=subscriber)
    result = superfeedr("subscribe", subscription)
    if result.status_code == 204:
      subscription.put() # saves the subscription
      message.reply("Well done! You're subscribed to " + message.arg)
    else:
      message.reply("Sorry, couldn't susbcribe to " + message.arg)
    
  ##
  # Asking to unsubscribe to a feed
  def unsubscribe_command(self, message=None):
    message = xmpp.Message(self.request.POST)
    subscriber = message.sender.rpartition("/")[0]
    subscription = Subscription.get_by_key_name(hashlib.sha224(message.arg + subscriber).hexdigest())
    result = superfeedr("unsubscribe", subscription)
    subscription.delete() # saves the subscription
    message.reply("Well done! You're not subscribed anymore to " + message.arg)

  ##
  # List subscriptions by page
  # 10/page
  # page default to 1
  def ls_command(self, page_index=1, message=None):
    message = xmpp.Message(self.request.POST)
    subscriber = message.sender.rpartition("/")[0]
    query = Subscription.all().filter("jid =",subscriber).order("-created_at")
    count = query.count()
    if count%10 == 0:
      pages_count = count/10
    else:
      pages_count = count/10 + 1
    page_index = min(page_index, pages_count)
    offset = (page_index - 1) * 10 
    subscriptions = query.fetch(10, offset)
    if not subscriptions:
      message.reply("Seems you subscribed nothing yet. Type\n  /subscribe http://superfeedr.com/dummy.xml\nto play around.")
    else:
      message.reply("Your have %d subscriptions in total: page %d/%d \n" % (count,page_index,pages_count))
      feed_list = [s.feed for s in subscriptions]
      message.reply("\n".join(feed_list))

  ##
  # Asking for help
  def hello_command(self, message=None):
    message = xmpp.Message(self.request.POST)
    message.reply("Oh, Hai! Notifixlite is a small app to help you subscribe to your favorite feeds and get their updates via IM. It's powered by Superfeedr (http://superfeedr.com) and its magic powers!. ")
    message.reply("Make it better : http://github.com/superfeedr/notifixlight.")
    message.reply("For more info, type /help.")
  
  ##
  # Asking for help
  def help_command(self, message=None):
    message = xmpp.Message(self.request.POST)
    help_msg = "It's not even alpha ready, but you could play with following commands:\n"
          +"/hello\n about me\n"
	  +"/subscribe <url>\n/unsubscribe <url>\n  subscribe or unsubscribe to a feed\n"
	  +"/ls <page_index>\n  list subscriptions history\n"
	  +"/help\n  print help info\n"
    message.reply(help_msg)
  
  ##
  # All other commants
  def unhandled_command(self, message=None):
    message = xmpp.Message(self.request.POST)
    message.reply("Please, type /help for help.")
  
  ##
  # Sent for any message.
  def text_message(self, message=None):
    message = xmpp.Message(self.request.POST)
    message.reply("Echooooo (when you're done playing, type /help) > " + message.body)

application = webapp.WSGIApplication([('/_ah/xmpp/message/chat/', XMPPHandler), ('/', MainPage), ('/hubbub/(.*)', HubbubSubscriber)],debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
  
