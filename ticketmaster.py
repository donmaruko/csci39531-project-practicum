"""
Ticketmaster Discovery API Documentation Reference
https://developer.ticketmaster.com/products-and-docs/apis/discovery-manual/v2/

Endpoint
  GET /discovery/v2/events                    Search Events

Query parameters
  apikey                                      authentication
  keyword                                     artist name search term
  classificationName                          "music" genre filter
  startDateTime                               exclude events before this datetime (ISO 8601)
  size                                        results per page (50)

Response fields
  id, name, url                               event identity
  dates.start.localDate                       event date
  dates.start.localTime                       show start time
  dates.timezone                              show timezone
  dates.status.code                           sale status (onsale, offsale, …)
  sales.public.startDateTime                  public on-sale window open
  priceRanges[].currency                      ticket currency
  priceRanges[].min                           minimum ticket price
  _embedded.events[]                          event result list
  _embedded.venues[0].name                    venue name
  _embedded.venues[0].city.name               venue city
  _embedded.venues[0].state.name              venue state
  _embedded.venues[0].address.line1           venue street address
  _embedded.venues[0].capacity                venue capacity
  _embedded.attractions[0]                    headliner
  _embedded.attractions[1:]                   support acts
  _embedded.attractions[].name                 attraction name (headliner + support)
  _embedded.attractions[0].externalLinks      headliner social/web links
"""
import requests
from datetime import datetime, timezone

from config import TICKETMASTER_KEY



def _city_matches(event, location):
    """
    @param event: normalized event dict from _extract_event
    @param location: user-provided city string
    @return: True if location matches the event's city or state (case-insensitive substring check)
    """
    loc = location.lower()
    city = event["city"].lower()
    state = event.get("state", "").lower()
    return loc in city or city in loc or (state and (loc in state or state in loc))

def _artist_matches(raw, artist):
    """
    @param raw: a single raw event dict as returned by the Ticketmaster API
    @param artist: artist name string to match against
    @return: True if the artist name appears as a contiguous phrase in the event name
             or any attraction (headliner or support)
    """
    artist_lower = artist.lower()
    if artist_lower in raw["name"].lower():
        return True
    attractions = raw.get("_embedded", {}).get("attractions", [])
    return any(artist_lower in a.get("name", "").lower() for a in attractions)

def get_events(artist, location):
    """
    @param artist: artist name to search for on Ticketmaster
    @param location: user-provided location string (city, borough, or metro area)
    @pre: TICKETMASTER_KEY is set in the environment
    @return: list of upcoming normalized event dicts matching artist and location, sorted by date
    @throw: requests.HTTPError if the API returns a non-2xx status
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    resp = requests.get(
        "https://app.ticketmaster.com/discovery/v2/events",  # TM: GET /discovery/v2/events
        params={
            "keyword": artist,                                    # TM: keyword
            "classificationName": "music",                        # TM: classificationName
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),  # TM: startDateTime
            "size": 50,                                           # TM: size
            "apikey": TICKETMASTER_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    raw_events = resp.json().get("_embedded", {}).get("events", [])  # TM: _embedded.events[]
    events = [
        ev for raw in raw_events
        if _artist_matches(raw, artist)
        for ev in [_extract_event(raw)]
        if ev and _city_matches(ev, location) and ev["date"] >= today
    ]
    events.sort(key=lambda ev: ev["date"])
    return events


def _extract_event(raw):
    """
    @param raw: a single raw event dict as returned by the Ticketmaster API
    @pre: raw is a non-empty dict representing one event with all its info
    @return: a normalized event dict with keys (id, name, date, effective_status,
             venue, city, url, price, show_time, support, capacity, presale_label, pub_start_dt),
             or None if the event is missing required fields
    """

    # try/except so a single malformed event dict skips as None instead of crashing the poll cycle
    try:
        venue = raw["_embedded"]["venues"][0]  # TM: _embedded.venues[0]

        # price is only presented if Ticketmaster has published ticket prices, null otherwise
        p = next(iter(raw.get("priceRanges", [])), None)  # TM: priceRanges[]
        price_str = f"from {p.get('currency', '')} {p['min']:,.2f}" if p and p.get("min") is not None else None  # TM: priceRanges[].currency, priceRanges[].min

        show_time = raw["dates"]["start"].get("localTime")  # TM: dates.start.localTime

        # attractions[0] is the headliner, everything after is support
        attractions = raw.get("_embedded", {}).get("attractions", [])  # TM: _embedded.attractions[]
        support_acts = [a["name"] for a in attractions[1:] if "name" in a]  # TM: attractions[1:].name

        # social links for the headliner only
        ext = attractions[0].get("externalLinks", {}) if attractions else {}  # TM: attractions[0].externalLinks
        social = {k: v[0]["url"] for k, v in ext.items() if v and v[0].get("url")}

        capacity = venue.get("capacity")                    # TM: venues[0].capacity
        show_timezone = raw["dates"].get("timezone")        # TM: dates.timezone
        address = venue.get("address", {}).get("line1")     # TM: venues[0].address.line1
        state = venue.get("state", {}).get("name", "")      # TM: venues[0].state.name

        # presale detection via Ticketmaster marking presale events as offsale, so the only way to
        # distinguish them is a future public on-sale date in sales.public.startDateTime
        pub_start_raw = raw.get("sales", {}).get("public", {}).get("startDateTime", "")  # TM: sales.public.startDateTime
        presale_label = None
        pub_start_dt = None
        if pub_start_raw and len(pub_start_raw) >= 16:
            if pub_start_raw[:10] > datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                presale_label = datetime.strptime(pub_start_raw[:16], "%Y-%m-%dT%H:%M").strftime("%b %d, %Y")
                pub_start_dt = datetime.strptime(pub_start_raw[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)

        api_status = raw["dates"]["status"]["code"]  # TM: dates.status.code
        # relabel offsale to presale so the FSM can treat it as its own state
        effective_status = "presale" if (api_status == "offsale" and presale_label) else api_status

        return {
            "id": raw["id"],                              # TM: id
            "name": raw["name"],                          # TM: name
            "date": raw["dates"]["start"]["localDate"],   # TM: dates.start.localDate
            "effective_status": effective_status,
            "venue": venue["name"],                       # TM: venues[0].name
            "city": venue["city"]["name"],                # TM: venues[0].city.name
            "url": raw["url"],                            # TM: url
            "price": price_str,
            "show_time": show_time,
            "support": support_acts,
            "capacity": capacity,
            "presale_label": presale_label,
            "pub_start_dt": pub_start_dt,
            "timezone": show_timezone,
            "address": address,
            "state": state,
            "social": social,
        }
    except (KeyError, IndexError):
        return None