"""Compares two street lines the way a statement and NetSuite write them
differently: "508 HIGHWAY 35" and "508 State Route 35 North", "181 S Main St"
and "181 South Main St", "1072 N BRITAIN AVE" and "1072 New Britain Ave".

The house number has to be the same. Then, for a numbered route (Highway 35,
Route 35, Hwy 35, State Route 35 N), the route number has to be the same;
otherwise the street names have to agree once suffixes (St, Ave, Road, ...),
directions and single letters are set aside, the shorter name's words all
found in the longer's -- a word counting as found when it is equal or
spelled almost the same.
"""
import re
from difflib import SequenceMatcher

from src.validation.shop_list import normalize_text

_HOUSE_NUMBER_RE = re.compile(r"^(\d+)[a-z]?$")
_ROUTE_WORDS = {"hwy", "highway", "route", "rte", "rt", "sr"}
# Words that say what kind of street it is or which side of it, not which one.
_SET_ASIDE = {
    "street", "st", "avenue", "ave", "road", "rd", "pike", "drive", "dr", "lane", "ln", "boulevard", "blvd",
    "court", "ct", "way", "place", "pl", "parkway", "pkwy", "trail", "trl", "circle", "cir", "terrace", "ter",
    "square", "sq", "unit", "suite", "ste", "north", "south", "east", "west", "ne", "nw", "se", "sw",
    "state", "us",
}
_WORD_SIMILARITY = 0.85


def parse_street(street) -> tuple:
    """(house number, route number, name words) of a street line; "" for a
    part it does not have. Name words are what is left after the house number,
    suffixes, directions and single letters."""
    words = normalize_text(street).split()
    number = ""
    if words and _HOUSE_NUMBER_RE.match(words[0]):
        number = _HOUSE_NUMBER_RE.match(words[0]).group(1)
        words = words[1:]
    route = ""
    for index, word in enumerate(words[:-1]):
        if word in _ROUTE_WORDS and words[index + 1].isdigit():
            route = words[index + 1]
            break
    name_words = [w for w in words if w not in _SET_ASIDE and w not in _ROUTE_WORDS and len(w) > 1]
    return number, route, name_words


def _same_word(a: str, b: str) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= _WORD_SIMILARITY


def _names_agree(a: list, b: list) -> bool:
    shorter, longer = sorted((a, b), key=len)
    return bool(shorter) and all(any(_same_word(word, other) for other in longer) for word in shorter)


def same_street(a, b) -> bool:
    """True when two street lines name the same address."""
    number_a, route_a, name_a = parse_street(a)
    number_b, route_b, name_b = parse_street(b)
    if not number_a or number_a != number_b:
        return False
    if route_a or route_b:
        return route_a == route_b
    return _names_agree(name_a, name_b)
