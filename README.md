# serverless-fn-notify

A Python 3.12 function for the OVHcloud Serverless alpha: a web page that
sends a notification to WhatsApp (or Slack, Teams, email, PagerDuty, a
webhook...) through [Apprise](https://github.com/caronc/apprise).

It is the shape of the "notification template" the alpha needs while the
platform has no Topics (SNS-like) service: the function formats the message,
drops duplicates, retries briefly, and lets Apprise talk to the destination.
The destination is configuration, not code: one secret, `NOTIFY_URLS`, holds
one or more Apprise URLs. Change the URL, redeploy nothing, and the same
function reaches another service.

It follows the platform starter `function-python3.12-hello`: the handler is
`main` in `user.py`, takes no argument, runs inside Flask and returns JSON or
a Flask `Response`. One dependency, pinned in `requirements.txt`.

## What it does

| Request | Answer |
|---|---|
| `GET /` | The demo page: a form, the configured destinations (secrets masked), the last answer |
| `GET /?format=json` | Status: destinations, Apprise version and import time, instance counters |
| `POST /` with `{"id", "title", "body"}` | Sends the message, answers with the per-destination result |
| `POST /` with a CloudEvent | Same, after turning the event into a readable message (what an Events Rule would post) |

A message id (or the CloudEvent `id`) seen twice by the same instance is
ignored: `{"deduplicated": true}`. Each destination gets `NOTIFY_RETRIES`
attempts (default 2). The answer is `502` when a destination failed, so a
caller or a Rule can retry.

## Try it locally in two minutes

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt flask
python3 scripts/receiver.py 9999 &                       # a local stand-in for WhatsApp
NOTIFY_URLS="json://localhost:9999/hook" python3 user.py  # the function on :8080
open http://localhost:8080/
```

Click "Send": the receiver prints the message. Click "Send as a CloudEvent":
the same handler formats an instance-created event. Click "Send the same id
again": the duplicate is ignored. Stop the receiver and send again: two
attempts, then `502`.

## Send to WhatsApp

Only `NOTIFY_URLS` changes. Two routes, both free for a demo:

| Route | URL | Setup |
|---|---|---|
| Meta WhatsApp Cloud API | `whatsapp://TOKEN@PHONE_ID/33612345678` | developers.facebook.com: create an app, add the WhatsApp product, take the test number's Phone number ID and an access token, register your own phone as a test recipient. The first message to a recipient must be a template: `whatsapp://hello_world:TOKEN@PHONE_ID/33612345678`. Once the recipient has replied to the test number, plain text works for 24 hours |
| Twilio WhatsApp sandbox | `twilio://ACCOUNT_SID:AUTH_TOKEN@14155238886/w:33612345678` | twilio.com: free trial, open the WhatsApp sandbox, send its "join" word from your phone, use the sandbox number as the source. The `w:` prefix routes the target through WhatsApp |

Several destinations at once: `NOTIFY_URLS="whatsapp://...,slack://...,mailto://..."`.
Other services and their URL formats: the Apprise wiki lists more than 100.

`NOTIFY_URLS` carries tokens: it is a platform secret, and the function only
ever prints the masked form (`url(privacy=True)`).

## Deploy on the platform

```sh
export OVH_CLOUD_PROJECT=<project id>
export NOTIFY_URLS="whatsapp://TOKEN@PHONE_ID/33612345678"
scripts/deploy.sh main
```

The script uses `~/.ovh.conf` (profile `serverless-alpha`) and the deploy
tooling of the podinfo-sls repository cloned next to this one. `spec.json` is
the readable `targetSpec`; `deploy/function.json` is the templated payload the
script renders. The repository must be public on GitHub: the platform clones
the ref.

## Configuration

| Variable | Default | Role |
|---|---|---|
| `NOTIFY_URLS` | unset | Secret. Comma-separated Apprise URLs. Nothing is delivered without it |
| `NOTIFY_TITLE` | `OVHcloud Serverless` | Default title, and title prefix for CloudEvents |
| `NOTIFY_RETRIES` | `2` | Attempts per destination, 0.5 s then 1 s between them |
| `NOTIFY_CORS_ORIGIN` | `*` | `Access-Control-Allow-Origin`, for a page hosted elsewhere |
| `NOTIFY_RELEASE` | `dev` | Set by the deploy script, reported in the status |

## Why Apprise here, and what it does not do

Apprise absorbs the per-service API details (Slack, Teams, email, SMS
providers, PagerDuty, WhatsApp...) and their churn, behind one URL
convention. That is why one template replaces five. It is pure Python
(BSD-2-Clause), and the import costs a few hundred milliseconds on a cold
start: `appriseImportMs` in the status shows the real figure on the platform.

It does not do the parts that belong to the template: turning an event into a
message, ignoring a redelivered id, retrying. And it has no plugin for the
OVHcloud SMS or email APIs: those would be written by hand, or contributed
upstream. When Topics exist, `_send` becomes "publish on the Topic" and the
subscriptions move there; the rest of this function does not change.
