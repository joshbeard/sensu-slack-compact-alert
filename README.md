# Compact Sensu Slack Handler

This is a [Sensu handler](https://docs.sensu.io/sensu-go/latest/observability-pipeline/observe-process/handlers/) for sending messages to Slack.

It's written in Python and uses the
[jspaleta/sensu-python-runtime](https://bonsai.sensu.io/assets/jspaleta/sensu-python-runtime) runtime.

While Sensu [provides](https://bonsai.sensu.io/assets/sensu/sensu-slack-handler) a Slack handler,
its messages take up too much space. This handler intends to be more condensed and provide more useful information.

## Build and Deploy

The [`src/`](src) directory structure is setup for Sensu to function properly. This is done according to the [sensu-python-runtime example](https://github.com/jspaleta/sensu-python-runtime).

The dependencies are installed to a `lib/` sub-directory via `pip install -r requirements.txt --target lib`. The entire directory is then compressed and uploaded to Artifactory.

```shell
cd src
pip install -r requirements.txt --target lib
tar -cvzf ../sensu-slack-alert.tar.gz .
shasum -a 512 sensu-slack-alert.tar.gz
```

Finally, a [_handler_ configuration](example/handler-slack.yml) is created to _use_ the handler.

NOTE: This uses the legacy [Slack webhooks](https://api.slack.com/legacy/custom-integrations)
because it's much simpler and possible to send messages to any channel, including private ones.

## Usage

Provide a Sensu handler configuration:

See the [example handler config](example/handler-slack.yml).

This uses the deprecated Slack incoming webhooks because it makes it easy to
send notices to any (private or open) channel specified without having to run a
bot or join channels.

## Slack Channels

Slack channels may be set in a variety of ways. In order of precedence:

* `slack_channel` annotation on entity
* `slack-channel` annotation on entity
* `slack_channel` label on entity
* `slack-channel` label on entity
* `SLACK_CHANNEL` environment variable

## Resources

[Token substitution](https://docs.sensu.io/sensu-go/latest/observability-pipeline/observe-schedule/checks/#check-token-substitution)
is not available in handler configurations due to security concerns (e.g. having a generic web check with the url as
a variable set by an annotation or label), which is why this
handler parses those annotations and labels directly.

See <https://github.com/sensu/sensu-go/issues/2528> for more information.
