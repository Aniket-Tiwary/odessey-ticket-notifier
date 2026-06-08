import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from html import escape

IST = timezone(timedelta(hours=5, minutes=30))


def get_now_ist():
    return datetime.now(timezone.utc).astimezone(IST)
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


STATE_FILE = os.getenv("STATE_FILE", "ticket_state.json")

CONFIG = {
    "bms_url": os.getenv(
        "BMS_URL", "https://in.bookmyshow.com/movies/pune/the-odyssey/ET00452034"
    ),
    "bms_dates": os.getenv("BMS_DATES", "20260717,20260718,20260719"),
    "bms_theatre": os.getenv("BMS_THEATRE", "Wakad,Westend,Aundh,Millennium"),
    "bms_time": os.getenv("BMS_TIME", ""),
    "bms_format": os.getenv("BMS_FORMAT", "IMAX"),
    "district_urls": os.getenv(
        "DISTRICT_URLS",
        ",".join(
            [
                "https://www.district.in/movies/inox-megaplex-phoenix-mall-of-the-millennium-wakad-in-pune-CD1023543",
                "https://www.district.in/movies/cinepolis-nexus-westend-aundh-pune-in-pune-CD127",
            ]
        ),
    ),
    "district_movie_terms": os.getenv(
        "DISTRICT_MOVIE_TERMS", "the odyssey,odyssey,odessey"
    ),
    "district_format": os.getenv("DISTRICT_FORMAT", "IMAX"),
}

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_TO_EMAIL = os.getenv("RESEND_TO_EMAIL", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
SEND_TEST_EMAIL_ONCE = os.getenv("SEND_TEST_EMAIL_ONCE", "") == "1"

API_URL = (
    "https://in.bookmyshow.com/api/movies-data/v4/"
    "showtimes-by-event/primary-dynamic"
)

AVAIL_STATUS_MAP = {
    "0": "SOLD OUT",
    "1": "ALMOST FULL",
    "2": "FILLING FAST",
    "3": "AVAILABLE",
}

DATE_STYLE_MAP = {
    "date-selected": "BOOKABLE",
    "date-disabled": "NOT_OPEN",
    "date-default": "AVAILABLE",
}

TIME_PERIODS = {
    "morning": (600, 1200),
    "afternoon": (1200, 1600),
    "evening": (1600, 1900),
    "night": (1900, 2400),
}

REGION_MAP = {
    "chennai": ("CHEN", "chennai", "13.056", "80.206", "tf3"),
    "mumbai": ("MUMBAI", "mumbai", "19.076", "72.878", "te7"),
    "delhi-ncr": ("NCR", "delhi-ncr", "28.613", "77.209", "ttn"),
    "delhi": ("NCR", "delhi-ncr", "28.613", "77.209", "ttn"),
    "bengaluru": ("BANG", "bengaluru", "12.972", "77.594", "tdr"),
    "bangalore": ("BANG", "bengaluru", "12.972", "77.594", "tdr"),
    "hyderabad": ("HYD", "hyderabad", "17.385", "78.487", "tep"),
    "kolkata": ("KOLK", "kolkata", "22.573", "88.364", "tun"),
    "pune": ("PUNE", "pune", "18.520", "73.856", "te2"),
    "kochi": ("KOCH", "kochi", "9.932", "76.267", "t9z"),
}


@dataclass
class CatInfo:
    name: str
    price: str
    status: str


@dataclass
class ShowInfo:
    source: str
    venue_code: str
    venue_name: str
    session_id: str
    date_code: str
    time: str
    time_code: str
    screen_attr: str
    categories: list[CatInfo] = field(default_factory=list)


@dataclass
class DateInfo:
    date_code: str
    status: str


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)


@dataclass
class HttpResponse:
    status_code: int
    text: str

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def parse_bms_url(url):
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    result = {"event_code": None, "date_code": None, "region_slug": None}
    for part in parts:
        if re.match(r"^ET\d{8,}$", part, re.IGNORECASE):
            result["event_code"] = part.upper()
        elif re.match(r"^\d{8}$", part):
            result["date_code"] = part
    if "movies" in parts:
        idx = parts.index("movies")
        if idx + 1 < len(parts):
            result["region_slug"] = parts[idx + 1]
    return result


def resolve_region(slug):
    key = (slug or "").lower().strip()
    return REGION_MAP.get(key, (key.upper()[:6], key, "0", "0", ""))


def fetch_bms(event_code, date_code, region_code, region_slug, lat, lon, geohash):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://in.bookmyshow.com/movies/{region_slug}/buytickets/{event_code}/",
        "x-app-code": "WEB",
        "x-region-code": region_code,
        "x-region-slug": region_slug,
        "x-geohash": geohash,
        "x-latitude": lat,
        "x-longitude": lon,
        "x-location-selection": "manual",
        "x-lsid": "",
        "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }
    params = {
        "eventCode": event_code,
        "dateCode": date_code or "",
        "isDesktop": "true",
        "regionCode": region_code,
        "xLocationShared": "false",
        "memberId": "",
        "lsId": "",
        "subCode": "",
        "lat": lat,
        "lon": lon,
    }
    response = http_get(API_URL, headers=headers, params=params, timeout=20)
    if response.status_code != 200:
        print(f"BMS HTTP {response.status_code} for {date_code or '(default)'}")
        return None
    return response.json()


def parse_movie_info(data):
    info = {"name": "Unknown Movie", "language": ""}
    for widget in data.get("data", {}).get("topStickyWidgets", []):
        if widget.get("type") == "horizontal-text-list":
            for item in widget.get("data", []):
                for row in item.get("leftText", {}).get("data", []):
                    for component in row.get("components", []):
                        text = component.get("text", "")
                        if "•" in text:
                            info["language"] = text.strip()
    bottom_sheet = data.get("data", {}).get("bottomSheetData", {})
    for widget in bottom_sheet.get("format-selector", {}).get("widgets", []):
        if widget.get("type") == "vertical-text-list":
            for item in widget.get("data", []):
                if item.get("styleId") == "bottomsheet-subtitle":
                    info["name"] = item.get("text", info["name"])
    return info


def parse_dates(data):
    dates = []
    for widget in data.get("data", {}).get("topStickyWidgets", []):
        if widget.get("type") != "horizontal-block-list":
            continue
        for item in widget.get("data", []):
            if len(item.get("data", [])) >= 3:
                dates.append(
                    DateInfo(
                        date_code=item.get("id", ""),
                        status=DATE_STYLE_MAP.get(item.get("styleId", ""), "UNKNOWN"),
                    )
                )
    return dates


def parse_shows(data):
    shows = []
    for widget in data.get("data", {}).get("showtimeWidgets", []):
        if widget.get("type") != "groupList":
            continue
        for group in widget.get("data", []):
            if group.get("type") != "venueGroup":
                continue
            for card in group.get("data", []):
                if card.get("type") != "venue-card":
                    continue
                card_data = card.get("additionalData", {})
                venue_name = card_data.get("venueName", "Unknown")
                venue_code = card_data.get("venueCode", "")
                for showtime in card.get("showtimes", []):
                    show_data = showtime.get("additionalData", {})
                    date_code = str(
                        show_data.get("showDateCode", "") or show_data.get("dateCode", "")
                    ).strip()
                    if not date_code and re.match(
                        r"^\d{8}", show_data.get("cutOffDateTime", "")
                    ):
                        date_code = show_data["cutOffDateTime"][:8]
                    show = ShowInfo(
                        source="BookMyShow",
                        venue_code=venue_code,
                        venue_name=venue_name,
                        session_id=show_data.get("sessionId", ""),
                        date_code=date_code,
                        time=showtime.get("title", ""),
                        time_code=show_data.get("showTimeCode", ""),
                        screen_attr=(
                            showtime.get("screenAttr", "")
                            or show_data.get("attributes", "")
                        ),
                    )
                    for category in show_data.get("categories", []):
                        show.categories.append(
                            CatInfo(
                                name=category.get("priceDesc", ""),
                                price=str(category.get("curPrice", "0")),
                                status=str(category.get("availStatus", "")),
                            )
                        )
                    shows.append(show)
    return shows


def filter_bms_shows(shows):
    theatre_terms = split_terms(CONFIG["bms_theatre"])
    periods = split_terms(CONFIG["bms_time"])
    date_codes = set(split_terms(CONFIG["bms_dates"]))
    format_terms = split_terms(CONFIG["bms_format"])

    filtered = []
    for show in shows:
        if theatre_terms and not any(
            term in show.venue_name.lower() for term in theatre_terms
        ):
            continue
        if date_codes and show.date_code and show.date_code not in date_codes:
            continue
        if format_terms and not any(
            term in show.screen_attr.lower() for term in format_terms
        ):
            continue
        if periods and not time_matches(show.time_code, periods):
            continue
        filtered.append(show)
    return filtered


def time_matches(time_code, periods):
    try:
        code = int(time_code)
    except ValueError:
        return False
    for period in periods:
        if period not in TIME_PERIODS:
            continue
        low, high = TIME_PERIODS[period]
        if low <= code < high:
            return True
    return False


def check_bookmyshow():
    parsed = parse_bms_url(CONFIG["bms_url"])
    if not parsed["event_code"] or not parsed["region_slug"]:
        raise ValueError("Invalid BMS_URL. Could not extract event code and region.")

    region_code, region_slug, lat, lon, geohash = resolve_region(parsed["region_slug"])
    raw_dates = split_terms(CONFIG["bms_dates"])
    date_list = raw_dates or ([parsed["date_code"]] if parsed["date_code"] else [""])

    all_shows = []
    all_dates = []
    movie_info = {"name": "Unknown Movie", "language": ""}

    for date_code in date_list:
        data = fetch_bms(
            parsed["event_code"], date_code, region_code, region_slug, lat, lon, geohash
        )
        if not data:
            continue
        if movie_info["name"] == "Unknown Movie":
            movie_info = parse_movie_info(data)
        all_dates.extend(parse_dates(data))
        all_shows.extend(parse_shows(data))

    filtered = filter_bms_shows(all_shows)
    return movie_info, filtered, all_dates


def check_district():
    urls = split_terms(CONFIG["district_urls"], lower=False)
    movie_terms = split_terms(CONFIG["district_movie_terms"])
    format_terms = split_terms(CONFIG["district_format"])
    results = {}

    for url in urls:
        response = http_get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        lines = extract_text_lines(response.text)
        normalized_lines = [line.lower() for line in lines]
        venue = first_heading(lines) or url
        windows = target_windows(lines, normalized_lines, movie_terms)
        joined = "\n".join(windows).lower()
        available = bool(windows) and all(term in joined for term in format_terms)
        digest = sha256("\n".join(windows)) if windows else ""
        results[url] = {
            "source": "District",
            "venue": venue,
            "url": url,
            "available": available,
            "hash": digest,
            "summary": windows[:18],
        }
    return results


def extract_text_lines(html):
    parser = TextExtractor()
    parser.feed(html)
    lines = []
    for part in parser.parts:
        cleaned = re.sub(r"\s+", " ", part).strip()
        if cleaned and cleaned not in lines:
            lines.append(cleaned)
    return lines


def first_heading(lines):
    for line in lines:
        if "pune" in line.lower() and len(line) > 10:
            return line.lstrip("# ").strip()
    return ""


def target_windows(lines, normalized_lines, movie_terms):
    windows = []
    for idx, line in enumerate(normalized_lines):
        if any(term in line for term in movie_terms):
            windows.extend(lines[idx : idx + 28])
    return dedupe(windows)


def build_bms_state(shows, dates):
    show_state = {}
    for show in shows:
        for category in show.categories or [CatInfo("", "", "")]:
            key = "|".join(
                [
                    show.source,
                    show.venue_code,
                    show.session_id,
                    show.date_code,
                    category.name,
                ]
            )
            show_state[key] = {
                "source": show.source,
                "venue": show.venue_name,
                "time": show.time,
                "date": show.date_code,
                "format": show.screen_attr,
                "cat": category.name,
                "price": category.price,
                "status": category.status,
            }
    return {
        "shows": show_state,
        "dates": {date.date_code: date.status for date in dates},
    }


def detect_bms_changes(old_state, new_state):
    changes = []
    old_shows = old_state.get("shows", {})
    new_shows = new_state.get("shows", {})

    if not old_state and new_shows:
        changes.append(f"BookMyShow: {len(new_shows)} matching show category row(s) found.")

    for key in sorted(set(new_shows) - set(old_shows)):
        show = new_shows[key]
        changes.append(
            "BookMyShow NEW: "
            f"{show['venue']} {show['time']} [{show['date']}] "
            f"{show['format']} {show['cat']} Rs.{show['price']}"
        )

    for key, new_show in new_shows.items():
        old_show = old_shows.get(key)
        if old_show and old_show["status"] == "0" and new_show["status"] != "0":
            changes.append(
                "BookMyShow BACK: "
                f"{new_show['venue']} {new_show['time']} [{new_show['date']}] "
                f"{AVAIL_STATUS_MAP.get(new_show['status'], 'UNKNOWN')}"
            )

    old_dates = old_state.get("dates", {})
    new_dates = new_state.get("dates", {})
    for date_code, status in new_dates.items():
        if old_dates.get(date_code) == "NOT_OPEN" and status in ("BOOKABLE", "AVAILABLE"):
            changes.append(f"BookMyShow date opened: {date_code}")

    return changes


def detect_district_changes(old_state, new_state):
    changes = []
    for url, current in new_state.items():
        previous = old_state.get(url, {})
        if current["available"] and not previous.get("available"):
            changes.append(f"District AVAILABLE: {current['venue']} - {url}")
        elif (
            current["available"]
            and previous.get("available")
            and current["hash"] != previous.get("hash")
        ):
            changes.append(f"District CHANGED: {current['venue']} - {url}")
    return changes


def send_email(subject, changes, bms_shows, district_state):
    if not RESEND_API_KEY or not RESEND_TO_EMAIL:
        print("Skipping email: RESEND_API_KEY or RESEND_TO_EMAIL is missing.")
        return False

    now = get_now_ist().strftime("%d %b %Y, %I:%M %p")
    plain = [subject, f"Checked at: {now}", "", "Changes:"]
    plain.extend(f"- {change}" for change in changes)
    plain.append("")
    plain.append("BookMyShow matches:")
    for show in bms_shows:
        cats = ", ".join(
            f"{cat.name} Rs.{cat.price} ({AVAIL_STATUS_MAP.get(cat.status, 'UNKNOWN')})"
            for cat in show.categories
        )
        plain.append(
            f"- {show.venue_name} {show.time} [{show.date_code}] {show.screen_attr}: {cats}"
        )
    plain.append("")
    plain.append("District matches:")
    for item in district_state.values():
        if item["available"]:
            plain.append(f"- {item['venue']}: {item['url']}")

    html = "<br>".join(escape(line) for line in plain)
    response = http_post_json(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM_EMAIL,
            "to": [RESEND_TO_EMAIL],
            "subject": subject,
            "text": "\n".join(plain),
            "html": html,
        },
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Resend failed: {response.status_code} {response.text}")
    print(f"Email sent to {RESEND_TO_EMAIL}")
    return True


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def http_get(url, headers=None, params=None, timeout=20):
    if params:
        from urllib.parse import urlencode

        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"
    request = Request(url, headers=headers or {}, method="GET")
    return open_request(request, timeout)


def http_post_json(url, headers=None, json=None, timeout=20):
    body = ({} if json is None else json)
    data = __import__("json").dumps(body).encode("utf-8")
    request = Request(url, data=data, headers=headers or {}, method="POST")
    return open_request(request, timeout)


def open_request(request, timeout):
    if not request.has_header("User-agent"):
        request.add_header(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        )
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status_code=response.status,
                text=response.read().decode("utf-8", errors="replace"),
            )
    except HTTPError as error:
        return HttpResponse(
            status_code=error.code,
            text=error.read().decode("utf-8", errors="replace"),
        )
    except URLError as error:
        raise RuntimeError(f"Network request failed: {error.reason}") from error


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def split_terms(value, lower=True):
    terms = [term.strip() for term in value.split(",") if term.strip()]
    return [term.lower() for term in terms] if lower else terms


def sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dedupe(values):
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def main():
    print(f"[{get_now_ist().isoformat(timespec='seconds')}] Ticket checker")
    old_state = load_state()

    movie_info, bms_shows, bms_dates = check_bookmyshow()
    district_state = check_district()

    new_state = {
        "bookmyshow": build_bms_state(bms_shows, bms_dates),
        "district": district_state,
        "test_email_sent": old_state.get("test_email_sent", False),
        "last_checked_at": get_now_ist().isoformat(timespec='seconds'),
    }

    changes = []
    changes.extend(
        detect_bms_changes(old_state.get("bookmyshow", {}), new_state["bookmyshow"])
    )
    changes.extend(detect_district_changes(old_state.get("district", {}), district_state))

    print(f"BookMyShow matching shows: {len(bms_shows)}")
    print(
        "District available pages: "
        f"{sum(1 for item in district_state.values() if item['available'])}"
    )

    if changes:
        subject = f"Ticket Alert: {movie_info.get('name', 'The Odyssey')} - {len(changes)} change(s)"
        for change in changes:
            print(change)
        send_email(subject, changes, bms_shows, district_state)
    else:
        print("No changes.")

    if SEND_TEST_EMAIL_ONCE and not new_state["test_email_sent"]:
        sent = send_email(
            "Test Email: The Odyssey ticket notifier is working",
            [
                "This is a one-time test email from the GitHub Actions ticket notifier.",
                "Future scheduled runs will not send this test email again unless ticket_state.json is reset.",
            ],
            bms_shows,
            district_state,
        )
        if sent:
            new_state["test_email_sent"] = True
            print("One-time test email sent and recorded in state.")

    save_state(new_state)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
