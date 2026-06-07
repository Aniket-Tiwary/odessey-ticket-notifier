# The Odyssey Pune Ticket Notifier

Email-only monitor for Christopher Nolan's `The Odyssey` across:

- BookMyShow
- District
- INOX/PVR Megaplex Phoenix Mall of the Millennium, Wakad
- Cinepolis Nexus Westend Mall, Aundh

The BookMyShow side uses the public showtimes API, inspired by
`aviiciii/bms-ticket-notifier`. The District side fetches the public theatre
pages and watches for a target movie + format window.

## Setup

```sh
cp config.example.env .env
```

Export the values from `.env`, or set them in GitHub Actions secrets/variables.

```sh
python3 main.py
```

For Resend email alerts:

```sh
export RESEND_API_KEY="re_..."
export RESEND_FROM_EMAIL="onboarding@resend.dev"
export RESEND_TO_EMAIL="you@example.com"
```

## Useful Defaults

```sh
export BMS_URL="https://in.bookmyshow.com/movies/pune/the-odyssey/ET00452034"
export BMS_DATES="20260717,20260718,20260719"
export BMS_THEATRE="Wakad,Westend,Aundh,Millennium"
export BMS_FORMAT="IMAX"
export DISTRICT_FORMAT="IMAX"
```

`ticket_state.json` is written after each run. Alerts are sent only when a new
matching BookMyShow show appears, a BMS date opens, a sold-out BMS category comes
back, or a District target page newly contains `The Odyssey` + `IMAX`.

## Scheduling

GitHub Actions is included at `.github/workflows/ticket-checker.yml` and runs
every 15 minutes. Configure these repository secrets:

```text
RESEND_API_KEY
RESEND_FROM_EMAIL
RESEND_TO_EMAIL
```

Configure these repository variables:

```text
BMS_URL
BMS_DATES
BMS_THEATRE
BMS_FORMAT
BMS_TIME
DISTRICT_URLS
DISTRICT_MOVIE_TERMS
DISTRICT_FORMAT
SEND_TEST_EMAIL_ONCE
```

To test Resend delivery once, set this repository variable:

```text
SEND_TEST_EMAIL_ONCE=1
```

Run the workflow manually. If the email sends successfully, the script records
`test_email_sent: true` in `ticket_state.json`, so scheduled runs do not keep
sending test emails.

For a local/VPS cron job every 5 minutes:

```cron
*/5 * * * * cd /Users/aniket/Documents/Codex/2026-06-08/i-want-to-setup-an-alarm && python3 main.py
```

Keep polling modest and avoid login/CAPTCHA/payment automation.
