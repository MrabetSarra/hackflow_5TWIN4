#!/bin/sh
set -u

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  printf '%s\n' 'Usage: scripts/smoke_test.sh <BASE_URL>' >&2
  exit 2
fi

BASE_URL=${1%/}
case "$BASE_URL" in
  http://*|https://*) ;;
  *) printf '%s\n' 'BASE_URL must start with http:// or https://.' >&2; exit 2 ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  printf '%s\n' 'curl is required to run the smoke checks.' >&2
  exit 2
fi

TEMP_DIR=${TMPDIR:-/tmp}
HEADERS=$(mktemp "${TEMP_DIR%/}/hackflow-smoke-headers.XXXXXX") || exit 2
BODY=$(mktemp "${TEMP_DIR%/}/hackflow-smoke-body.XXXXXX") || {
  rm -f "$HEADERS"
  exit 2
}
trap 'rm -f "$HEADERS" "$BODY"' 0 HUP INT TERM

failures=0

pass() {
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1"
  failures=$((failures + 1))
}

request() {
  request_url=$1
  shift
  HTTP_STATUS=$(curl --silent --show-error --connect-timeout 10 --max-time 20 \
    --dump-header "$HEADERS" --output "$BODY" --write-out '%{http_code}' \
    "$@" "$request_url")
}

request "$BASE_URL/healthz/" || HTTP_STATUS=000
if [ "$HTTP_STATUS" = '200' ]; then
  pass '/healthz/ returns HTTP 200'
else
  fail "/healthz/ returned HTTP ${HTTP_STATUS:-000}, expected 200"
fi

request "$BASE_URL/smoke-test-page-that-does-not-exist/" || HTTP_STATUS=000
if [ "$HTTP_STATUS" = '404' ] \
  && grep -Fqi 'Page not found' "$BODY" \
  && ! grep -Eiq 'Traceback|Exception Value|DEBUG[[:space:]]*=[[:space:]]*True|Django tried these URL patterns' "$BODY"; then
  pass 'Unknown URL returns the custom 404 page without debug details'
else
  fail "Unknown URL returned HTTP ${HTTP_STATUS:-000} or exposed debug details"
fi

request "$BASE_URL/student/" || HTTP_STATUS=000
case "$HTTP_STATUS" in
  3??)
    if grep -Eiq '^Location:[[:space:]]*[^[:space:]]*login' "$HEADERS"; then
      pass 'Anonymous GET /student/ redirects to login'
    else
      fail 'Anonymous GET /student/ redirected somewhere other than login'
    fi
    ;;
  *) fail "Anonymous GET /student/ returned HTTP ${HTTP_STATUS:-000}, expected a login redirect" ;;
esac

request "$BASE_URL/student/" --request POST --data 'smoke_test=1' || HTTP_STATUS=000
if [ "$HTTP_STATUS" = '403' ]; then
  pass 'POST without a CSRF token returns HTTP 403'
else
  fail "POST without a CSRF token returned HTTP ${HTTP_STATUS:-000}, expected 403"
fi

request "$BASE_URL/" || HTTP_STATUS=000
if grep -Eiq '^X-Content-Type-Options:[[:space:]]*nosniff([[:space:]]|$)' "$HEADERS"; then
  pass 'X-Content-Type-Options: nosniff is present'
else
  fail 'X-Content-Type-Options: nosniff is missing'
fi
if grep -Eiq '^X-Frame-Options:[[:space:]]*(DENY|SAMEORIGIN)([[:space:]]|$)' "$HEADERS"; then
  pass 'X-Frame-Options is present'
else
  fail 'X-Frame-Options is missing'
fi
case "$BASE_URL" in
  https://*)
    if grep -Eiq '^Strict-Transport-Security:[[:space:]]*[^[:space:]]+' "$HEADERS"; then
      pass 'Strict-Transport-Security is present over HTTPS'
    else
      fail 'Strict-Transport-Security is missing over HTTPS'
    fi
    ;;
  *) printf '%s\n' 'SKIP HSTS check: BASE_URL is not HTTPS.' ;;
esac

for private_path in \
  '/media/private_media/' \
  '/media/.repository-data/' \
  '/media/private-probe.txt' \
  '/private_media/private-probe.txt' \
  '/.repository-data/private-probe.txt' \
  '/repositories/private-probe.txt'; do
  request "$BASE_URL$private_path" || HTTP_STATUS=000
  case "$HTTP_STATUS" in
    2*) fail "Private path is publicly accessible: $private_path" ;;
    3??|4??) pass "Private path is not publicly accessible: $private_path" ;;
    *) fail "Could not verify private path protection: $private_path (HTTP ${HTTP_STATUS:-000})" ;;
  esac
done

for private_path in \
  '/media/../private_media/private-probe.txt' \
  '/media/../.repository-data/private-probe.txt'; do
  request "$BASE_URL$private_path" --path-as-is || HTTP_STATUS=000
  case "$HTTP_STATUS" in
    2*) fail "A media path exposed private storage: $private_path" ;;
    3??|4??) pass "Media path cannot reach private storage: $private_path" ;;
    *) fail "Could not verify media path protection: $private_path (HTTP ${HTTP_STATUS:-000})" ;;
  esac
done

HOME_RESULT=$(curl --silent --show-error --connect-timeout 10 --max-time 20 \
  --dump-header "$HEADERS" --output "$BODY" \
  --write-out '%{http_code} %{time_total}' "$BASE_URL/")
curl_result=$?
if [ "$curl_result" -eq 0 ]; then
  HOME_STATUS=${HOME_RESULT%% *}
  HOME_TIME=${HOME_RESULT#* }
  case "$HOME_STATUS" in
    2??|3??) pass "Home page response time: ${HOME_TIME}s (HTTP $HOME_STATUS)" ;;
    *) fail "Home page returned HTTP $HOME_STATUS after ${HOME_TIME}s" ;;
  esac
else
  fail 'Home page request failed before a response time could be measured'
fi

if [ "$failures" -gt 0 ]; then
  printf 'Smoke test failed: %s check(s) failed.\n' "$failures"
  exit 1
fi

printf '%s\n' 'All smoke checks passed.'
