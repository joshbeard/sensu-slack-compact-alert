#!/usr/bin/env python
"""
A handler for Sensu Go for sending alerts to Slack in a more compact way than
the official one, as well as other customizations.

Configuration:
  Environment variables (e.g. in a check config):
    SLACK_WEBHOOK_URL   A legacy Slack webhook URL
    SLACK_USERNAME      The username to send the message as
    SLACK_CHANNEL       The Slack channel to send to or a fallback channel.
                        Labels and annotations take precedence.
    ICON_URL            A URL to an icon image to use for the Slack user
    SENSU_BASE_URL      The base URL to the Sensu dashboard to link to. E.g.
                        https://sensu.foo.org/

  Sensu Entity labels or annotations:
    slack_link_command_url: Toggles linking to a URL found in the check output.
    slack_link_command_text: The link title when using slack_link_command_url.

  Slack channels can be configured using a label or annotation.
  In order of precedence:
    slack_channel annotation on entity
    slack-channel annotation on entity
    slack_channel label on entity
    slack-channel label on entity

Authors:
  * Josh Beard - https://joshbeard.me

"""
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
    "sensu_url": os.environ.get('SENSU_BASE_URL'),
    "icon_url": os.environ.get('ICON_URL', 'https://docs.sensu.io/images/sensu-logo-icon-dark@2x.png')
}


def emoji(status):
    """
    List of emojis to map to an event status, using the Sensu/Nagios
    exit code (0=OK, 1=Warning, 2=Critical, 3=Unknown)
    """
    emojis = [
        ':large_green_circle:',
        ':large_yellow_circle:',
        ':red_circle:',
        ':large_purple_circle:'
    ]
    return emojis[status]


def pretty_date(time=False, since=now, relative=True):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    Adapted from
    https://stackoverflow.com/questions/1551382/user-friendly-time-format-in-python/1551394#1551394

    :param time: the timestamp to parse
    :param since: The current time as a datetime object
    :param relative: Boolean toggling to return the time relative. E.g. "x ago"
    :return: returns a string indicating how long ago a specific time was
    """
    if isinstance(time, int):
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
        the_time += " month"
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

    :param history: The Sensu check's history from the event data
    :return: returns a list of the most recent failed checks since the last passing
    """
    history.reverse()
    bad_checks = []
    for i, x in enumerate(history):
        if i == 0 and x['status'] == 0:
            continue

        if x['status'] != 0:
            bad_checks.append(x)
        else:
            break
    return bad_checks


def slack_channel(metadata):
    """
    Find a Slack channel to use in labels, annotations, or an environment
    variable.

    :param metadata: The Sensu event metadata containing labels or annotations
    :return: returns a string with the slack channel to alert to
    """
    if 'annotations' in metadata:
        annotations = metadata['annotations']
        if 'slack_channel' in annotations:
            return annotations['slack_channel']
        if 'slack-channel' in annotations:
            return annotations['slack-channel']

    if 'labels' in metadata:
        labels = metadata['labels']
        if 'slack_channel' in labels:
            return labels['slack_channel']
        if 'slack-channel' in labels:
            return labels['slack-channel']
        return os.environ.get('SLACK_CHANNEL', 'alerts')


def main():
    """Load the Sensu event data (stdin)"""
    data = ""
    for line in sys.stdin.readlines():
        data += "".join(line.strip())
    obj = json.loads(data)

    channel = slack_channel(obj['entity']['metadata'])
    namespace = obj['entity']['metadata']['namespace']
    entity_name = obj['entity']['metadata']['name']
    check_name = obj['check']['metadata']['name']

    output = obj['check']['output']
    output.replace('\n', ' ').replace('\r', '')

    message = emoji(obj['check']['status'])

    # Generate markdown for the entity name in the Slack message
    # This links it to the Sensu dashboard
    message += " " + f"<{config['sensu_url']}/c/~/n/{namespace}/entities/{entity_name}/events|{entity_name}>"

    # Generate markdown for the check name in the Slack message
    # This links it to the Sensu dashboard
    message += " - " + f"<{config['sensu_url']}/c/~/n/{namespace}/events/{entity_name}/{check_name}|{check_name}>"

    # If a URL is in the check command, add a link to it in the Slack message.
    # This is disabled by default and can be enabled per-check by setting a
    # label or annotation called 'slack_link_command_url' to 'True' (bool)
    s = False
    link_text = "(view site)"
    if (
        'labels' in obj['check']['metadata']
        and 'slack_link_command_url' in obj['check']['metadata']['labels']
        and obj['check']['metadata']['labels']['slack_link_command_url'].lower() == "true"
    ):
        s = True
        if 'slack_link_command_text' in obj['check']['metadata']['labels']:
            link_text = obj['check']['metadata']['labels']['slack_link_command_text']
    if (
        'annotations' in obj['check']['metadata']
        and 'slack_link_command_url' in obj['check']['metadata']['annotations']
        and obj['check']['metadata']['annotations']['slack_link_command_url'].lower() == "true"
    ):
        s = True
        if 'slack_link_command_text' in obj['check']['metadata']['annotations']:
            link_text = obj['check']['metadata']['annotations']['slack_link_command_text']

    if (
        s
        and 'https://' in obj['check']['command']
        or 'http://' in obj['check']['command']
    ):
        # Match the first URL in the check command
        check_url = re.findall(
            r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
            obj['check']['command'], re.I)[0]
        # Creates a string like <https://foo/bar|(visit site)>
        message += " <" + check_url + "|" + link_text + ">"

    message += ": " + output.strip()

    logging.debug("raw event data: %s ", str(obj))

    # Post to Slack
    slack = Slack(url=config['webhook_url'])
    slack.post(
        username=config['username'],
        icon_url=config['icon_url'],
        channel=channel,
        text=message,
    )


if __name__ == '__main__':
    main()
