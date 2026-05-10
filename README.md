# BandGeek

A background daemon that monitors Ticketmaster for concert announcements and emails you the moment tickets become available.

## Pipeline

1. User provides artist, location, and poll interval
2. Bot launches as a background daemon and begins polling Ticketmaster on the given interval
3. Each poll queries the Ticketmaster Discovery API which returns deeply nested JSON. The response is normalized to extract only what's useful — show date and time, venue info, ticket price if published, supporting acts, sale status, and a direct URL to buy tickets. Results are then filtered to only keep events where the artist appears by name (as headliner or support) and the venue matches the given location
4. Each event is run through a state machine — if the status has changed (unknown to presale, or anything to onsale), an email alert fires
5. If nothing has changed — no new announcements, no status transitions — the bot simply sleeps for the interval and goes back to polling indefinitely until something changes. The only time it breaks out of this cycle is when a presale is detected and a public on-sale date is known
    - Only then would the bot sleep directly until the exact moment general sale goes live, skipping all intermediate polling cycles entirely.
    - On wake-up, the bot polls once and fires the second alert.

## Setup

Create a `.env` file in the project root with atleast these secrets:

```
TICKETMASTER_KEY=your_ticketmaster_api_key
SMTP_FROM=your_email@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_EMAIL=recipient@email.com
```

Install dependencies:

```
pip install -r requirements.txt
```

## Usage

```
python3 bandgeek.py
```

You will be prompted for artist, location, poll interval (defaults to 60s), and alert email. The bot launches as a background daemon and logs to `bandgeek.log`.

Alternatively, pass arguments directly:

```
python3 bandgeek.py --artist "Black Country, New Road" --location "Philadelphia" --interval 60 --email you@email.com
```

Unique PIDs will be provided for everytime you run the bot to track different artists. To stop all running bots:

```
pkill -f bandgeek.py
```

## Files

| File | Description |
|------|-------------|
| `bandgeek.py` | Main daemon, FSM, polling loop, scheduled sleep |
| `cli.py` | Argument parsing, daemonization, slug generation |
| `ticketmaster.py` | Ticketmaster API wrapper and event extraction |
| `alerts.py` | Email alert formatting and delivery |
| `config.py` | Environment variable loading |
| `fetch_raw_json.py` | Debug tool,  dumps raw and extracted API response to JSON |
