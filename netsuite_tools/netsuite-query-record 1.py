import argparse
import json
import os

import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth1

load_dotenv()

account_id = os.environ["ACCOUNT_ID"]
consumer_key = os.environ["CONSUMER_KEY"]
consumer_secret = os.environ["CONSUMER_SECRET"]
token_id = os.environ["TOKEN_ID"]
token_secret = os.environ["TOKEN_SECRET"]

url = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest/query/v1/suiteql"

auth = OAuth1(
    consumer_key,
    client_secret=consumer_secret,
    resource_owner_key=token_id,
    resource_owner_secret=token_secret,
    signature_method="HMAC-SHA256",
    realm=account_id,
)

parser = argparse.ArgumentParser(description="Inspect a single NetSuite record type via SuiteQL.")
parser.add_argument("table", help="Record type / table name, e.g. vendorbill")
parser.add_argument("--id", dest="record_id", help="Fetch this specific internal ID instead of sample rows")
parser.add_argument("--limit", type=int, default=5, help="Number of sample rows when --id is not given (default 5)")
parser.add_argument("--where", help="Extra WHERE clause (without the WHERE keyword)")
args = parser.parse_args()

if args.record_id:
    query = f"SELECT * FROM {args.table} WHERE id = {args.record_id}"
elif args.where:
    query = f"SELECT * FROM {args.table} WHERE {args.where} FETCH FIRST {args.limit} ROWS ONLY"
else:
    query = f"SELECT * FROM {args.table} FETCH FIRST {args.limit} ROWS ONLY"

print(f"Query: {query}\n")

resp = requests.post(
    url,
    auth=auth,
    headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "transient",
    },
    json={"q": query},
    timeout=30,
)

print("HTTP Status:", resp.status_code)

try:
    data = resp.json()
except ValueError:
    print(resp.text)
    raise SystemExit(1)

if resp.status_code != 200:
    print(json.dumps(data, indent=2))
    raise SystemExit(1)

items = data.get("items", [])
print(f"Rows returned: {len(items)}\n")

if items:
    columns = list(items[0].keys())
    print(f"Columns ({len(columns)}): {', '.join(columns)}\n")

print(json.dumps(items, indent=2))
