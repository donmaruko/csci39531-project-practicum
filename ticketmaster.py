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
  _embedded.events[]                          event result list
  _embedded.venues[0].name                    venue name
  _embedded.venues[0].city.name               venue city
  _embedded.venues[0].state.name              venue state
  _embedded.venues[0].address.line1           venue street address
  _embedded.attractions[0]                    headliner
  _embedded.attractions[1:]                   support acts
  _embedded.attractions[].name                 attraction name (headliner + support)
  _embedded.attractions[0].externalLinks      headliner social/web links
"""
import logging
import requests
from datetime import datetime, timezone

from config import TICKETMASTER_KEY

log = logging.getLogger(__name__)



def _parse_future_dt(raw_str):
    """
    @param raw_str: ISO 8601 datetime string, possibly empty or malformed
    @return: (label, dt) where label is "Mon DD, YYYY" and dt is a UTC-aware datetime,
             or (None, None) if raw_str is absent, malformed, or not in the future
    """
    try:
        sale_dt = datetime.strptime(raw_str[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        if sale_dt > datetime.now(timezone.utc):
            return sale_dt.strftime("%b %d, %Y"), sale_dt
    except (IndexError, KeyError, ValueError):
        pass
    return None, None

def _city_matches(event, location):
    """
    @param event: normalized event dict from _extract_event
    @param location: user-provided city string
    @return: True if location matches the event's city or state (case-insensitive substring check)
    """
    location_lower = location.lower()
    city = event["city"].lower()
    state = event.get("state", "").lower()
    return location_lower in city or city in location_lower or (state and (location_lower in state or state in location_lower))

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
    return any(artist_lower in attraction.get("name", "").lower() for attraction in attractions)

def get_events(artist, location):
    """
    @param artist: artist name to search for on Ticketmaster
    @param location: user-provided location string (city, borough, or metro area)
    @pre: TICKETMASTER_KEY is set in the environment
    @return: list of upcoming normalized event dicts matching artist and location, sorted by date (up to 50)
    @throw: requests.HTTPError if the API returns a non-2xx status
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    response = requests.get(
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
    response.raise_for_status()
    raw_events = response.json().get("_embedded", {}).get("events", [])  # TM: _embedded.events[]
    events = [
        event for raw in raw_events
        if _artist_matches(raw, artist)
        for event in [_extract_event(raw)]
        if event and _city_matches(event, location) and event["date"] >= today
    ]
    events.sort(key=lambda event: event["date"])
    return events

def _extract_event(raw):
    """
    @param raw: a single raw event dict as returned by the Ticketmaster API
    @pre: raw is a non-empty dict representing one event with all its info
    @return: a normalized event dict with keys (id, name, date, effective_status,
             venue, city, url, price, show_time, support, capacity, pub_sale_label, pub_start_dt),
             or None if the event is missing required fields
    """

    # try/except so a single malformed event dict skips as None instead of crashing the poll cycle
    try:
        venue = raw["_embedded"]["venues"][0]  # TM: _embedded.venues[0]

        show_time = raw["dates"]["start"].get("localTime")  # TM: dates.start.localTime

        # attractions[0] is the headliner, everything after is support
        attractions = raw.get("_embedded", {}).get("attractions", [])  # TM: _embedded.attractions[]
        support_acts = [attraction["name"] for attraction in attractions[1:] if "name" in attraction]  # TM: attractions[1:].name

        # social links for the headliner only
        external_links = attractions[0].get("externalLinks", {}) if attractions else {}  # TM: attractions[0].externalLinks
        social = {platform: links[0]["url"] for platform, links in external_links.items() if links and links[0].get("url")}

        show_timezone = raw["dates"].get("timezone")        # TM: dates.timezone
        address = venue.get("address", {}).get("line1")     # TM: venues[0].address.line1
        state = venue.get("state", {}).get("name", "")      # TM: venues[0].state.name

        # presale detection via Ticketmaster marking presale events as offsale, so the only way to
        # distinguish them is a future public on-sale date in sales.public.startDateTime
        pub_start_raw = raw.get("sales", {}).get("public", {}).get("startDateTime") or ""  # TM: sales.public.startDateTime
        pub_sale_label, pub_sale_dt = _parse_future_dt(pub_start_raw)

        presales = raw.get("sales", {}).get("presales", [])
        presale_start_raw = presales[0].get("startDateTime", "") if presales else ""  # TM: sales.presales[0].startDateTime
        presale_label, presale_dt = _parse_future_dt(presale_start_raw)

        api_status = raw["dates"]["status"]["code"]  # TM: dates.status.code
        # relabel offsale to presale so the FSM can treat it as its own state
        effective_status = "presale" if (api_status == "offsale" and pub_sale_label) else api_status

        return {
            "id": raw["id"],                              # TM: id
            "name": raw["name"],                          # TM: name
            "date": raw["dates"]["start"]["localDate"],   # TM: dates.start.localDate
            "effective_status": effective_status,
            "venue": venue["name"],                       # TM: venues[0].name
            "city": venue["city"]["name"],                # TM: venues[0].city.name
            "url": raw["url"],                            # TM: url
            "show_time": show_time,
            "support": support_acts,
            "pub_sale_label": pub_sale_label,
            "pub_sale_dt": pub_sale_dt,
            "presale_label": presale_label,
            "presale_dt": presale_dt,
            "timezone": show_timezone,
            "address": address,
            "state": state,
            "social": social,
        }
    except (KeyError, IndexError) as e:
        log.warning("failed to extract event (skipping): %s | raw id=%s", e, raw.get("id"))
        return None