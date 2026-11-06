"""
location_lookup.py

Maps the customer location extracted from a statement onto the canonical name
of a VIVE shop in config/vive_shops.json (src/validation/shop_list.py), so
billing_location holds the same names NetSuite uses ("Coleman's", not
"Auburn, ME"). Three signals are tried, in order:

  1. name   -- the shop name (or a known alias, config/location_mapping.json)
               in shop_or_entity / billing_location: an exact whole-word
               match, else a close (fuzzy) one
  2. phone  -- the customer phone number
  3. street -- the street line of the customer address(es), against the
               shop's address in NetSuite (src/validation/street_match.py)
  4. city   -- the city and state of the customer address(es)

Shops whose names start the same way ("Middletown" / "Middletown - NJ") are a
family: a name that only reaches the shorter one is checked against the phone
and the city+state before it is accepted.

The SOURCE of a result is returned alongside it (resolve_billing_location()'s
second value) and stored in document_intake_log.billing_location_source, so a
mapped name is never indistinguishable from an unmapped extraction:

  "name_match" / "fuzzy_match" / "phone_match" / "street_match" / "city_match"
              -- mapped to a shop
  "ambiguous" -- the name fits several shops of one family and nothing else
                 says which; needs review
  "conflict"  -- two signals pointed at different shops; needs review
  "unmapped"  -- no signal found a shop; the extracted value is kept as-is
  "invoice_match" -- set later, not here: a statement left ambiguous, in
              conflict or unmapped takes the location of its matched NetSuite
              bills (src/validation/invoice_location.py)
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from src.validation.shop_list import (all_shops, by_city, by_name, by_phone, is_alias, name_forms, normalize_place,
                                      normalize_state, normalize_text, shop_details)
from src.validation.street_match import same_street

logger = logging.getLogger(__name__)

SOURCE_NAME = "name_match"
SOURCE_FUZZY = "fuzzy_match"
SOURCE_PHONE = "phone_match"
SOURCE_STREET = "street_match"
SOURCE_CITY = "city_match"
SOURCE_AMBIGUOUS = "ambiguous"
SOURCE_CONFLICT = "conflict"
SOURCE_UNMAPPED = "unmapped"
SOURCE_INVOICE = "invoice_match"

MAPPED_SOURCES = (SOURCE_NAME, SOURCE_FUZZY, SOURCE_PHONE, SOURCE_STREET, SOURCE_CITY, SOURCE_INVOICE)

# A close match needs this similarity, beating the next-best shop by the
# margin; names shorter than the minimum (Acme, Lund, NEK) must match exactly,
# since a near-miss on four letters is as likely another word as a typo.
FUZZY_CUTOFF = 0.86
FUZZY_MARGIN = 0.05
FUZZY_MIN_NAME_LENGTH = 6

_CITY_STATE_RE = re.compile(r"^(?P<city>.*?)[,\s]+(?P<state>[A-Za-z]{2})$")
_ZIP_RE = re.compile(r"[\s,]*\b\d{5}(?:-\d{4})?\s*$")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _first_text(value) -> Optional[str]:
    """Normalizes the list-shaped shop_or_entity format this codebase uses
    (see adapter.py / claude_sonnet_client.py's vendor_metadata) into a
    single string, or returns None if empty."""
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value else None


def _split_city_state(address) -> tuple:
    city, state = _split_place(address)
    return (city, "") if state.strip().lower() in ("us", "usa") else (city, state)   # a country is no state


def _split_place(address) -> tuple:
    """("Mechanic Falls", "ME") from "Mechanic Falls, ME", "MECHANIC FALLS ME",
    "scarborough, Maine" or "NATICK, MA 01760" (a zip is dropped), or from a
    {"city": ..., "state": ...} dict. A bare "AVENEL" is a city with no
    state; ("", "") when there is nothing."""
    if isinstance(address, dict):
        return str(address.get("city") or ""), _ZIP_RE.sub("", str(address.get("state") or ""))
    text = _ZIP_RE.sub("", str(address or "").strip())
    if "," in text:
        city, _, state = text.rpartition(",")
        return city.strip(), state.strip()
    match = _CITY_STATE_RE.match(text)
    return (match.group("city"), match.group("state")) if match else (text, "")


def _named_in(text) -> tuple:
    """(shop, form) for the shop whose whole-word name (or alias) appears in
    `text`, and the form that was found. The longest form wins ("Clarks
    Summit" over "Clark's", "Prestige - NH" over "Prestige"); a tie between
    different shops is no match."""
    padded = f" {normalize_text(text)} "
    hits = [(form, shop) for form, shop in name_forms() if f" {form} " in padded]
    if not hits:
        return None, None
    longest = max(len(name) for name, _ in hits)
    top = {shop["name"]: (shop, name) for name, shop in hits if len(name) == longest}
    return next(iter(top.values())) if len(top) == 1 else (None, None)


def _shop_named_in(text) -> Optional[dict]:
    return _named_in(text)[0]


def _shop_named_by_alias(text) -> Optional[dict]:
    """The shop an alias in `text` names. An alias is a hand-picked pairing
    ("Bernatche" is the Bangor shop), so unlike a shop's own name it is
    trusted over a city that points elsewhere."""
    shop, form = _named_in(text)
    return shop if shop and is_alias(form) else None


# Words that say what a business is, not which shop: dropped from the
# statement's text and from the shops' names before they are compared, so
# "Vive Collision Maine Coll" and "Maine Collision" both come down to "maine".
_FILLER_WORDS = frozenset(("vive", "collision", "dba", "of", "the", "auto", "body", "autobody", "center", "llc", "opco"))


def _name_tokens(text) -> list:
    """The significant words of a shop text: parentheticals ("(W60)"),
    _FILLER_WORDS and a cut-off "collision" ("Coll", "Colli") removed."""
    cleaned = normalize_text(_PARENTHETICAL_RE.sub(" ", str(text or "")))
    return [word for word in cleaned.split()
            if word not in _FILLER_WORDS and not (len(word) >= 4 and "collision".startswith(word))]


def _best_similarity(name: str, tokens: list) -> float:
    """The highest similarity between a shop name and any run of the text's
    words about as long as the name."""
    size = len(name.split())
    best = 0.0
    for length in {max(1, size - 1), size, size + 1}:
        for start in range(len(tokens) - length + 1):
            window = " ".join(tokens[start:start + length])
            best = max(best, SequenceMatcher(None, name, window).ratio())
    return best


def _shop_close_to(text) -> Optional[dict]:
    """The one shop whose name `text` nearly contains (a typo, an OCR slip),
    or None when no shop is close enough or the best two are too alike to
    tell apart."""
    tokens = _name_tokens(text)
    scored = []
    for shop in all_shops():
        name = " ".join(_name_tokens(shop["name"]))
        if len(name) < FUZZY_MIN_NAME_LENGTH:
            continue
        score = _best_similarity(name, tokens)
        if score >= FUZZY_CUTOFF:
            scored.append((score, shop))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MARGIN):
        return None
    return scored[0][1]


ABBREVIATION_MIN_LENGTH = 5     # a lone word; after a matching word, 4 is enough


def _shop_abbreviated_by(text) -> Optional[dict]:
    """The one shop whose significant name the text ends with, whole or cut
    short: "Maine", "Maine Coll", "Maine Colli" and "Lyndh" are "Maine
    Collision" and "Lyndhurst". The words before the last must be the shop's
    own, the last a prefix of the next word and at least
    ABBREVIATION_MIN_LENGTH long (one less after a matching word: "Main" alone
    is a street, "Maine Coll" is not). The longest run of words wins; two
    shops that fit is no match."""
    tokens = _name_tokens(text)
    same = {shop["name"]: shop for shop in all_shops() if tokens and _name_tokens(shop["name"]) == tokens}
    if same:        # the whole text is the shop's significant name ("J.A.S. Autobody")
        return next(iter(same.values())) if len(same) == 1 else None
    found = {}      # words matched -> {shop name: shop}
    for shop in all_shops():
        words = _name_tokens(shop["name"])
        for size in range(1, min(len(words), len(tokens)) + 1):
            run = tokens[-size:]
            if (run[:-1] == words[:size - 1] and len(run[-1]) >= ABBREVIATION_MIN_LENGTH - (size > 1)
                    and words[size - 1].startswith(run[-1])):
                found.setdefault(size, {})[shop["name"]] = shop
    best = found[max(found)] if found else {}
    return next(iter(best.values())) if len(best) == 1 else None


def _longer_of_family(a, b) -> Optional[dict]:
    """Of two shops where one's name starts the other's ("Middletown" and
    "Middletown - NJ"), the more specific one; None if they are not family."""
    for shorter, longer in ((a, b), (b, a)):
        if longer["name"] != shorter["name"] and longer in _family(shorter):
            return longer
    return None


def _match_by_name(printed_location, shop_or_entity) -> tuple:
    """Step 1: (shop, source) or (None, None). shop_or_entity may carry the
    name inside a longer string ("VIVE COLLISION - RP BELL"); billing_location
    only counts when it IS a shop name, because a city such as "Bangor, ME"
    is not a name match. A close match is tried only when no exact one is."""
    entity_text = _first_text(shop_or_entity)
    from_entity = _shop_named_in(entity_text)
    from_location = by_name(printed_location) if printed_location else None
    if from_entity and from_location and from_entity["name"] != from_location["name"]:
        exact = _longer_of_family(from_entity, from_location)
        if not exact:
            return None, None
    else:
        exact = from_entity or from_location
    if exact:
        return exact, SOURCE_NAME
    close = (_shop_close_to(entity_text) or _shop_abbreviated_by(entity_text)) if entity_text else None
    return (close, SOURCE_FUZZY) if close else (None, None)


def _family(shop) -> list:
    """The shop plus every shop whose name starts with its name as whole
    words: Middletown -> [Middletown, Middletown - NJ]."""
    prefix = normalize_text(shop["name"])
    return [other for other in all_shops()
            if normalize_text(other["name"]) == prefix or normalize_text(other["name"]).startswith(prefix + " ")]


def _address_fits_family(family, printed_location, addresses) -> bool:
    """True when a customer address is at one of the family's shops: its street
    is the shop's street, or its city and state are the shop's. Shops that
    share an address (Noaker's and Noaker's Truck Shop) fit together."""
    for address in [printed_location, *(addresses or [])]:
        street = address.get("street") if isinstance(address, dict) else None
        city, state = _split_city_state(address)
        in_city = [member for member in family if city and member in by_city(city, state)]
        # A city named without its state fits only if the family's shops in
        # it are all in one state (Middletown is in RI and NJ: no fit).
        pinned = bool(state) or len({normalize_state(member.get("state")) for member in in_city}) == 1
        for member in family:
            at_street = bool(street) and bool(member.get("street")) and same_street(street, member["street"])
            at_city = member in in_city and pinned
            if (at_street or at_city) and _address_place_agrees(address, member):
                return True
    return False


def _settle_family(shop, phone_shop, place_shop, family_place=False) -> Optional[dict]:
    """The shop to use when the name reached `shop`: the phone's or the
    street's/city's shop if it is in the same family (that is how Middletown
    becomes Middletown - NJ). Failing that, `shop` itself when another signal
    exists, or when the address is at the family's own address and several of
    its shops share it (the text names `shop`, not a longer family member).
    None -- ambiguous -- when no signal places it in the family."""
    family = _family(shop)
    if len(family) == 1:
        return shop
    names = {member["name"] for member in family}
    for signal in (phone_shop, place_shop):
        if signal and signal["name"] in names:
            return signal
    return shop if family_place else (shop if shop["name"] in FAMILY_DEFAULTS else None)


# Shops to take when a name, city or street fits several shops of one family and
# nothing says which (Noaker's and Noaker's Truck Shop share an address).
FAMILY_DEFAULTS = ("Noaker's",)
_STREET_START_RE = re.compile(r"^\d+\s+\S")


def _family_default(found) -> Optional[dict]:
    """The default shop when `found` (several shops) are one family whose base
    shop is in FAMILY_DEFAULTS, else None."""
    for name in FAMILY_DEFAULTS:
        base = by_name(name)
        if base and all(shop in _family(base) for shop in found):
            return base
    return None


def _match_by_city(printed_location, addresses, shop_text=None) -> Optional[dict]:
    """Step 3. Exactly one shop across all the customer addresses is a match;
    a city shared by several shops (Bangor) or addresses pointing at
    different shops is not. The words left of the shop text once the filler is
    gone count as one more place ("Vive Collision of South Orange"), but only
    when they name a city and nothing else."""
    shops = []
    for address in [printed_location, *(addresses or [])]:
        city, state = _split_city_state(address)
        found = by_city(city, state) if city else []
        if len(found) > 1 and _family_default(found):
            found = [_family_default(found)]
        if len(found) == 1 and found[0] not in shops:
            shops.append(found[0])
        elif len(found) > 1:
            return None
    if len(shops) == 1:
        return shops[0]
    if shops or not shop_text:
        return None
    found = by_city(" ".join(_name_tokens(shop_text)), None)
    return (found if len(found) == 1 else [_family_default(found)] if found and _family_default(found) else [None])[0]


def _address_place_agrees(address, shop) -> bool:
    """False when an address names a city or state that is not the shop's --
    the same house number on a street in another town is not the same place."""
    city, state = _split_city_state(address)
    if city and shop.get("city") and normalize_place(city) != normalize_place(shop["city"]):
        return False
    return not (state and shop.get("state") and normalize_state(state) != normalize_state(shop["state"]))


def _match_by_street(addresses) -> Optional[dict]:
    """Step 3. Exactly one shop whose NetSuite street is the same address as
    one of the customer addresses' street lines; two shops at one address
    (Noaker's and Noaker's Truck Shop) or addresses pointing at different
    shops is no match."""
    shops = []
    for address in addresses or []:
        street = address.get("street") if isinstance(address, dict) else None
        if not street:
            continue
        found = [shop for shop in all_shops()
                 if shop.get("street") and same_street(street, shop["street"]) and _address_place_agrees(address, shop)]
        if len(found) > 1:
            found = [_family_default(found)] if _family_default(found) else found
        if len(found) > 1:
            return None
        if found and found[0] not in shops:
            shops.append(found[0])
    return shops[0] if len(shops) == 1 else None


def _decide(signals: list, ambiguous: bool, printed_location) -> tuple:
    """(location, source) from the (source, shop) signals that found a shop.
    Unmapped, ambiguous and conflict keep the extracted value unchanged."""
    found = [(source, shop) for source, shop in signals if shop]
    if not found:
        return printed_location or None, SOURCE_AMBIGUOUS if ambiguous else SOURCE_UNMAPPED
    if any(shop["name"] != found[0][1]["name"] for _, shop in found):
        return printed_location or None, SOURCE_CONFLICT
    return found[0][1]["name"], found[0][0]


def _with_street_location(printed_location, addresses):
    """`addresses`, plus the extracted location when it is itself a street
    ("2302 LUCAS TPKE"), which extraction sometimes returns."""
    if isinstance(printed_location, str) and _STREET_START_RE.match(printed_location.strip()):
        return [*(addresses or []), {"street": printed_location.strip()}]
    return addresses


def resolve_billing_location(printed_location, shop_or_entity, phone=None, addresses=None):
    """Returns (location, source). A mapped result is the shop's canonical
    name; for "unmapped", "ambiguous" and "conflict" the extracted value is
    returned unchanged so nothing is lost, and the source tells review it is
    not a verified shop."""
    aliased = _shop_named_by_alias(_first_text(shop_or_entity))
    # An alias outranks a city, but not a street address: "M3" is Highway 35
    # or South Main, and its street says which.
    addresses = _with_street_location(printed_location, addresses)
    street_elsewhere = _match_by_street(addresses)
    if aliased and not (street_elsewhere and street_elsewhere["name"] != aliased["name"]):
        logger.info("billing_location %s: extracted=%r shop_or_entity=%r -> %r (alias)",
                    SOURCE_NAME, printed_location, shop_or_entity, aliased["name"])
        return aliased["name"], SOURCE_NAME
    if aliased:     # its street is at another shop: the name alone cannot say which
        return printed_location or None, SOURCE_CONFLICT
    name_shop, name_source = _match_by_name(printed_location, shop_or_entity)
    phone_shop = by_phone(phone) if phone else None
    street_shop = _match_by_street(addresses)
    city_shop = _match_by_city(printed_location, addresses, _first_text(shop_or_entity))
    ambiguous = False
    if name_shop:
        settled = _settle_family(name_shop, phone_shop, street_shop or city_shop,
                                 _address_fits_family(_family(name_shop), printed_location, addresses))
        ambiguous = settled is None
        name_shop = settled
    # In order, each only when the one before found nothing: the name (its own
    # family settled by phone/street/city), then the address signals -- never
    # a city overriding a name. Anything left is for the bill fallback.
    if name_shop:
        location, source = name_shop["name"], name_source
    elif ambiguous:
        location, source = printed_location or None, SOURCE_AMBIGUOUS
    else:
        location, source = _decide(
            [(SOURCE_PHONE, phone_shop), (SOURCE_STREET, street_shop), (SOURCE_CITY, city_shop)],
            False, printed_location)
    # The extracted value is overwritten by a mapped name and not stored
    # anywhere else, so what came in is logged here.
    level = logger.info if source in MAPPED_SOURCES else logger.warning
    level("billing_location %s: extracted=%r shop_or_entity=%r phone=%r addresses=%r -> %r",
          source, printed_location, shop_or_entity, phone, addresses, location)
    return location, source


def apply_location(vendor_meta: dict, resolve=resolve_billing_location) -> dict:
    """Maps vendor_meta's customer location onto a shop and writes the result
    back into vendor_meta: billing_location (the shop name when mapped, else
    the extracted value), billing_location_source, billing_location_extracted
    (what extraction returned), and shop_phone / shop_city / shop_state from
    the shop list (None unless the location was mapped to a shop). Where the
    extracted value is already recorded it is kept, so running this twice on
    the same metadata does not replace it with the mapped name. `resolve` is
    passed by the callers (resolve_billing_location, as they have imported
    it) so a test can substitute it."""
    extracted = vendor_meta.get("billing_location_extracted", vendor_meta.get("billing_location"))
    location, source = resolve(
        extracted, vendor_meta.get("shop_or_entity"),
        phone=vendor_meta.get("customer_phone"), addresses=vendor_meta.get("customer_addresses"))
    details = (shop_details(location) if source in MAPPED_SOURCES else None) or {}
    vendor_meta.update({
        "billing_location_extracted": extracted,
        "billing_location": location,
        "billing_location_source": source,
        "shop_phone": details.get("phone"),
        "shop_city": details.get("city"),
        "shop_state": details.get("state"),
    })
    return vendor_meta
