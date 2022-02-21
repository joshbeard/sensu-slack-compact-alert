#!/usr/bin/env python
import logging
import os
import re
import sys
import json
from datetime import datetime
from slack_webhook import Slack

now = datetime.now()

config = {
    "webhook_url": os.environ.get('SLACK_WEBHOOK_URL'),
    "username": os.environ.get('SLACK_USERNAME', 'Sensu'),
    "sensu_url": os.environ.get('SENSU_BASE_URL')
}

"""
List of emojis to map to an event status, using the Sensu/Nagios
exit code (0=OK, 1=Warning, 2=Critical, 3=Unknown)
"""
emoji = [
    ':large_green_circle:',
    ':large_yellow_circle:',
    ':red_circle:',
    ':large_purple_circle:'
]

def pretty_date(time=False, since=now, relative=True):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    Adapted from https://stackoverflow.com/questions/1551382/user-friendly-time-format-in-python/1551394#1551394
    """
    if type(time) is int:
        diff = since - datetime.fromtimestamp(time)
    elif isinstance(time, datetime):
        diff = since - time
    elif not time:
        diff = 0
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        if second_diff < 10:
            the_time = str(second_diff)
            if relative:
                the_time = "just now"
            else:
                the_time += " seconds"
            return the_time
        if second_diff < 60:
            the_time = str(second_diff)
            if relative:
                the_time = "seconds ago"
            else:
                the_time += " seconds"
            return the_time
        if second_diff < 120:
            the_time = str(second_diff)
            if relative:
                the_time = "a minute ago"
            else:
                the_time += " seconds"
            return the_time
        if second_diff < 3600:
            the_time = str(second_diff // 60)
            the_time += " minute"
            if (second_diff // 60) > 1:
                the_time += "s"
            if relative:
                the_time += " ago"
            return the_time
        if second_diff < 7200:
            the_time = str(second_diff // 60)
            if relative:
                the_time += "an hour ago"
            else:
                the_time += " minute"
                if (second_diff // 6) > 1:
                    the_time += "s"
            return the_time
        if second_diff < 86400:
            the_time = str(second_diff // 3600)
            the_time += " hour"
            if (second_diff // 3600) > 1:
                the_time += "s"
            if relative:
                the_time += " ago"
            return the_time
    if day_diff == 1:
        the_time = str(second_diff // 3600)
        the_time += " hour"
        if (second_diff // 3600) > 1:
            the_time += "s"
        if relative:
            the_time = "Yesterday"
        return the_time
    if day_diff < 7:
        the_time = str(day_diff)
        if relative:
            the_time = " days ago"
        else:
            the_time += " days"
        return the_time
    if day_diff < 31:
        the_time = str(day_diff // 7)
        the_time += " week"
        if (day_diff // 7) > 1:
            the_time += "s"
        if relative:
            the_time += " ago"
        return the_time
    if day_diff < 365:
        the_time = str(day_diff // 30)
        the_time + " month"
        if (day_diff // 30) > 1:
            the_time += "s"
        if relative:
            the_time += " ago"
        return the_time
    if day_diff >= 365:
        the_time = str(day_diff // 365)
        the_time += " year"
        if (day_diff // 365) > 1:
            the_time += "s"
        if relative:
            the_time += " ago"
        return the_time

def parse_history(history):
    """
    Parse event history to determine the delta between the previous (bad) status
    and when it first began.
    This returns a list of the previous failed checks since the last OK
    """
    history.reverse()
    bad_checks = []
    for i, x in enumerate(history):
        if i == 0 and x['status'] == 0:
            continue

        if x['status'] is not 0:
            bad_checks.append(x)
        else:
            break
    return(bad_checks)

def main():
    """
    Load the Sensu event data (stdin)
    """
    data = ""
    for line in sys.stdin.readlines():
        data += "".join(line.strip())
    obj = json.loads(data)

    """
    Parse the history to display how long a check has been in its status or previous status
    """
    time_text = ""
    if 'history' in obj['check']:
        for i, hist in enumerate(obj['check']['history']):
            if i == 0:
                if int(hist['status']) is 0:
                    continue
            bad_history = parse_history(obj['check']['history'])
            if len(bad_history) > 1:
                bad_first = datetime.fromtimestamp(bad_history[-1]['executed'])
                bad_last = datetime.fromtimestamp(bad_history[0]['executed'])
                duration = str(pretty_date(bad_first, bad_last, False))
                if obj['check']['status'] is 0:
                    print("was alerting for " + duration)
                    time_text = "Alerted for " + duration
                else:
                    time_text = "Alerting for " + duration

    output = obj['check']['output']
    output.replace('\n', ' ').replace('\r', '')

    """
    Generate markdown for the entity name in the Slack message
    This links it to the Sensu dashboard
    """
    entity_text = "<" + config['sensu_url'] \
        + "/c/~/n/" + obj['entity']['metadata']['namespace'] \
        + "/entities/" + obj['entity']['metadata']['name'] \
        + "/events|" + obj['entity']['metadata']['name']  + ">"

    """
    Generate markdown for the check name in the Slack message
    This links it to the Sensu dashboard
    """
    check_text = "<" \
        + config['sensu_url'] \
        + "/c/~/n/" + obj['entity']['metadata']['namespace'] \
        + "/events/" + obj['entity']['metadata']['name'] \
        + "/" + obj['check']['metadata']['name'] \
        + "|" + obj['check']['metadata']['name'] + ">"

    """
    If a URL is in the check command, add a link to it in the Slack message.
    This is disabled by default and can be enabled per-check by setting a
    label or annotation called 'slack_show_command_url' to 'True' (bool)
    """
    check_command_urls = False
    if 'labels' in obj['check']['metadata']:
        if 'slack_show_command_url' in obj['check']['metadata']['labels']:
            if obj['check']['metadata']['labels']['slack_show_command_url'].lower() == "true":
                check_command_urls = True
    if 'annotations' in obj['check']['metadata']:
        if 'slack_show_command_url' in obj['check']['metadata']['annotations']:
            if obj['check']['metadata']['annotations']['slack_show_command_url'].lower() == "true":
                check_command_urls = True

    if check_command_urls:
        if 'https://' in obj['check']['command'] or 'http://' in obj['check']['command']:
            check_url = re.findall(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", obj['check']['command'], re.I)[0]
            # Creates a string like <https://foo/bar|(visit site)>
            check_text += " <" + check_url + "|" + "(view site)>"

    """
    Produce the Slack message
    """
    message = emoji[obj['check']['status']] + " " + entity_text + " - " + check_text + ": " + output.strip() + "; " + time_text

    logging.debug("raw event data: %s " % str(obj))

    """
    Find a Slack channel to use in labels, annotations, or an environment
    variable.
    """
    if 'labels' in obj['entity']['metadata']:
        labels = obj['entity']['metadata']['labels']
        if 'slack_channel' in labels:
            channel = labels['slack_channel']
        elif 'slack-channel' in labels:
            channel = labels['slack-channel']
        else:
            channel = os.environ.get('SLACK_CHANNEL', 'alerts')

    if 'annotations' in obj['entity']['metadata']:
        annotations = obj['entity']['metadata']['annotations']
        if 'slack_channel' in annotations:
            channel = annotations['slack_channel']
        elif 'slack-channel' in annotations:
            channel = annotations['slack-channel']

    """
    Post to Slack
    """
    slack = Slack(url=config['webhook_url'])
    slack.post(
        username=config['username'],
        icon_url="https://docs.sensu.io/images/sensu-logo-icon-dark@2x.png",
        channel=channel,
        text=message,
    )

if __name__ == '__main__':
    main()