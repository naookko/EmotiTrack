# WhatsApp DASS-21 Demo Bot

This Flask app hosts a quick WhatsApp Cloud API bot that guides new conversations through the 21 DASS screening questions using interactive reply buttons. Users can only answer by tapping buttons, and the bot delivers the final stress and depression scores with expressive emojis.

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Update `.env` with your WhatsApp Cloud API credentials:
   - `WHATSAPP_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `WHATSAPP_VERIFY_TOKEN`
   - (Optional) `DATABASE_PATH` for the SQLite file (defaults to `whatsapp_bot/bot.sqlite3`)

4. Expose the webhook URL (see the Cloudflare Zero Trust notes below or use `ngrok http 5000`) and register it in the Meta developer dashboard using the verify token.

## Expose the webhook with Cloudflare Zero Trust

Use this path if you created a tunnel from the Cloudflare Zero Trust dashboard and received a one-time service token (for example the command you ran: `cloudflared.exe service install <token>`).

1. Sign in to https://one.dash.cloudflare.com and choose the Zero Trust account linked to your domain.
2. Go to Access > Tunnels, click **Create a tunnel**, name it, and pick **Cloudflared** as the connector type.
3. On the **Install connector** step select Windows and copy the generated command. Run it in an elevated PowerShell window, e.g.:
   ```powershell
   cloudflared.exe service install <token-from-dashboard>
   ```
   This installs the Cloudflared service, places credentials under `%ProgramData%\Cloudflare\cloudflared\`, and registers the tunnel.
4. Back in the tunnel detail page, add a **Public Hostname** that forwards to your bot: set the hostname (e.g. `whatsapp.yourdomain.com`) and service `http://localhost:5000`. Save and wait until the connector shows **Healthy**.
5. Validate reachability: `curl https://whatsapp.yourdomain.com/webhook?hub.mode=subscribe&hub.verify_token=YOUR_VERIFY_TOKEN&hub.challenge=123`. The response should echo the challenge if Cloudflare can reach your app.
6. In the Meta developer dashboard, set the callback URL to `https://whatsapp.yourdomain.com/webhook` and reuse the same verify token from `.env`. Click **Verify and Save**, then subscribe your WhatsApp Business Account to the `messages` field.
7. Keep the Cloudflared service running (check with `Get-Service cloudflared`), start `python app.py`, and send a test message from an approved WhatsApp tester phone.

If you do not own a domain or prefer a temporary tunnel, you can still use ngrok or the `cloudflare_tunnel_setup.sh` helper, which guides you through a quick ephemeral tunnel.

## Project structure

```
whatsapp_bot/
|-- app.py              # local entry point
|-- app_factory.py      # Flask application factory
|-- config.py           # environment loading and settings
|-- constants.py        # questionnaire text and scoring tables
|-- database.py         # SQLite helpers
|-- models.py           # dataclasses shared across services
|-- routes/
|   `-- webhook.py      # webhook endpoints blueprint
`-- services/
    |-- conversation.py # conversation business logic
    `-- messaging.py    # WhatsApp API wrapper
```
## Run locally

```bash
python app.py
```

The app listens on `/:5000` by default and exposes:
- `GET /webhook` for Meta verification
- `POST /webhook` for incoming WhatsApp events
- `GET /health` for a simple health probe

## Conversation Flow

- On the first message, the bot greets the user and sends question 1 with four reply buttons (0-3 scale).
- Only button replies are accepted while the questionnaire is active. Typed responses prompt a reminder to use the buttons.
- After all 21 answers, the bot sends the DASS-21 scores (depression, stress, anxiety) and emojis summarizing stress and depression.
- Users can send `restart` to take the questionnaire again.










