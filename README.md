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

## Send to a WhatsApp group with WAHA

The official Cloud API only reaches individuals and business-created groups.
To post in a group or a community you are a member of, the only route is an
unofficial WhatsApp Web client. [WAHA](https://waha.devlike.pro) packages one
behind a REST API, in a container. It is against the WhatsApp terms and a
number can get banned: use a second number, never your main one.

WAHA runs as a Serverless container next to the function, one instance kept
alive (the session lives in memory, there is no persistent storage: a restart
means a new QR scan):

```sh
export OVH_CLOUD_PROJECT=<project id>
export WAHA_API_KEY=$(uuidgen | tr -d -)
scripts/deploy-waha.sh                      # prints the container URL
```

Then:

1. Open `<waha url>/dashboard` (user `admin`, password `WAHA_API_KEY`), start
   the session `default`, scan the QR code from the phone (Linked devices).
   The API does the same: `POST /api/sessions {"name": "default"}` then
   `GET /api/default/auth/qr` (a PNG), until `GET /api/sessions/default`
   says `WORKING`.
2. Find the group id: `GET /api/default/groups` with the `X-Api-Key` header.
   Ids end with `@g.us`.
3. Point the function at WAHA. Apprise's JSON plugin renames its `message`
   key to `text`, adds `chatId` and `session`, drops its own keys and sends
   the API key as a header:

```
NOTIFY_URLS="jsons://<waha host>/api/sendText?:message=text&:chatId=<group id>@g.us&:session=default&:version&:type&:title&+X-Api-Key=<WAHA_API_KEY>"
```

WAHA expects `{"session", "chatId", "text"}` on `POST /api/sendText`. The
title is dropped because WhatsApp has no title field; put it in the body if
needed. Several destinations still work: `NOTIFY_URLS="jsons://...,slack://..."`.

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
