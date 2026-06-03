"""Fenix Engine — shared scoring configuration.

Extracted from score_rank.py so both score_rank.py and ai_score_trends.py
can access the category catalog without circular imports.
"""
from __future__ import annotations

import re

# ── Intent keyword tiers ──────────────────────────────────────────────────────
T1_BUYER = (
    "buy", "price", "cheap", "best", "review", "order", "shop", "deal",
    "discount", "sale", "offer", "coupon", "promo code", "clearance",
    "cash on delivery", "cod", "free shipping", "emi", "in stock",
    "where to buy", "lowest price", "wholesale", "bulk",
    "dropship", "under 500", "under 1000", "₹", "rs.",
    "amazon", "flipkart", "meesho", "myntra", "nykaa", "ajio", "snapdeal",
)
T2_RESEARCH = (
    "alternative to", "similar to", "replacement for", "specs",
    "specifications", "features", "unboxing", "hands on",
    "pros and cons", "is it worth it", "buying guide",
    "top 10", "top 5", "tier list", "ranking", "benchmarks",
    "combo", "kit", "pack", "vs", "comparison",
)
T3_AMBIENT = (
    "wireless", "portable", "new", "latest", "trending", "2026",
    "original", "authentic", "genuine", "refurbished",
    "open box", "warranty", "return policy",
    "flash sale", "limited time", "lightning deal", "restock",
    "pre-order", "launch date", "release date", "near me",
)
NEG = (
    "how to", "tutorial", "diy", "repair", "fix", "not working", "error",
    "broken", "manual", "pdf", "driver download", "free download",
    "arrested", "died", "death", "funeral", "war", "blast", "attack",
    "accident", "protest", "politics", "election",
)

# ── Category configuration ────────────────────────────────────────────────────
# anchors  → high-specificity terms; each match scores +4 + 1.5 × word_count
# keywords → regular terms; each match scores +1
# priority → tie-breaker when two categories score identically
#
CATEGORIES: dict[str, dict] = {
    "electronics": {
        "priority": 10,
        "anchors": {
            "earbuds", "tws", "airpods", "airbuds", "neckband", "true wireless",
            "noise cancelling", "anc headphone", "gaming headset",
            "smartphone", "5g phone", "4g phone", "iphone", "samsung galaxy",
            "android phone", "foldable phone",
            "laptop", "macbook", "chromebook", "gaming laptop", "ultrabook",
            "power bank", "powerbank", "fast charger", "wireless charger",
            "smartwatch", "mi band", "galaxy watch", "fitness tracker",
            "fire tv stick", "android tv", "smart tv",
            "mechanical keyboard", "gaming mouse", "gaming chair", "gaming monitor",
            "router", "wifi extender", "mesh wifi", "wifi 6",
            "graphics card", "gpu", "processor", "cpu", "ssd", "nvme",
            "ram", "ddr5", "ddr4",
            "action camera", "gopro", "security camera", "cctv", "doorbell camera",
            "electric scooter", "ev charger",
            "kindle", "e-reader",
        },
        "keywords": {
            "wireless", "bluetooth", "phone", "usb", "charger",
            "monitor", "cable", "adapter", "tablet", "camera", "speaker",
            "headphone", "keyboard", "mouse", "display", "screen",
            "gaming", "pc", "computer", "drone", "projector", "tv",
            "earphone", "audio", "microphone", "webcam", "led",
            "hard disk", "pendrive", "memory card", "sdcard",
        },
    },
    "fashion": {
        "priority": 8,
        "anchors": {
            "kurta", "saree", "salwar", "dupatta", "lehenga", "churidar",
            "ethnic wear", "western wear", "ootd", "outfit of the day",
            "streetwear", "athleisure", "activewear", "fast fashion",
            "fashion week", "runway look", "kurti set",
        },
        "keywords": {
            "shirt", "dress", "jeans", "sneakers", "sunglasses",
            "t-shirt", "jacket", "shoes", "hoodie", "heels", "wallet",
            "fashion", "style", "clothing", "apparel", "wear", "outfit",
            "boots", "sandals", "cap", "hat", "scarf", "leggings",
            "blouse", "blazer", "trouser", "skirt", "tights",
        },
    },
    "home": {
        "priority": 7,
        "anchors": {
            "air purifier", "water purifier", "ro filter", "air fryer",
            "instant pot", "electric pressure cooker", "induction cooktop",
            "washing machine", "refrigerator", "microwave oven",
            "robot vacuum", "air conditioner", "ceiling fan",
            "smart bulb", "led strip light", "diffuser", "humidifier",
        },
        "keywords": {
            "kitchen", "decor", "organizer", "cleaning", "storage", "fan",
            "cooler", "light", "bottle", "bedsheet", "pillow", "cookware",
            "blender", "mop", "towel", "vacuum", "mixer", "grinder",
            "curtain", "mattress", "furniture", "lamp",
        },
    },
    "fitness": {
        "priority": 7,
        "anchors": {
            "whey protein", "creatine monohydrate", "mass gainer",
            "pre workout", "bcaa", "protein powder", "vegan protein",
            "yoga mat", "resistance band", "gym gloves", "lifting straps",
            "treadmill", "elliptical", "rowing machine", "stationary bike",
            "dumbbells set", "barbell", "pull up bar", "ab roller",
            "foam roller", "massage gun",
        },
        "keywords": {
            "gym", "yoga", "protein", "supplement", "band", "tracker",
            "cycle", "dumbbells", "mat", "creatine", "whey",
            "resistance", "shaker", "massager", "fitness", "workout",
            "exercise", "training", "sports", "running", "weight",
        },
    },
    "beauty": {
        "priority": 8,
        "anchors": {
            "vitamin c serum", "hyaluronic acid", "niacinamide",
            "spf 50", "spf 30", "sunscreen", "retinol", "salicylic acid",
            "hair serum", "hair oil", "scalp treatment",
            "bb cream", "cc cream", "setting powder", "baking powder",
            "lip gloss", "lip liner", "kajal", "eyeliner", "mascara",
            "face pack", "sheet mask", "under eye cream", "eye cream",
            "beard oil", "beard grooming", "hair growth oil",
        },
        "keywords": {
            "skincare", "hair", "serum", "moisturizer", "lipstick",
            "sunscreen", "shampoo", "perfume", "lotion",
            "trimmer", "face wash", "makeup", "cleanser", "toner",
            "conditioner", "cream", "gel", "essence", "mist",
            "nail", "beauty", "glow", "brightening",
        },
    },
    "accessories": {
        "priority": 6,
        "anchors": {
            "phone case", "mobile case", "laptop bag", "laptop sleeve",
            "screen protector", "tempered glass", "phone stand",
            "smartwatch strap", "watch band", "watch strap",
            "camera bag", "tripod", "lens filter", "gimbal",
            "cable organizer", "charging cable", "data cable",
        },
        "keywords": {
            "case", "cover", "stand", "holder", "mount", "strap",
            "sleeve", "skin", "guard", "ring", "grip", "hub", "dock",
            "pouch", "lanyard", "clip", "protector",
        },
    },
    "automotive": {
        "priority": 7,
        "anchors": {
            "dashcam", "dash cam", "car mount", "car charger", "car air purifier",
            "bike helmet", "riding jacket", "riding gloves", "motorbike",
            "tyre inflator", "tyre pressure gauge",
            "jump starter", "car polish", "car wax", "paint protection",
            "seat cover", "steering wheel cover", "car organizer",
        },
        "keywords": {
            "car", "bike", "helmet", "tyre", "wax", "polish",
            "wiper", "gps", "inflator", "coolant",
            "automotive", "vehicle", "driving", "motor",
        },
    },
    "baby_and_kids": {
        "priority": 7,
        "anchors": {
            "baby monitor", "baby carrier", "diaper bag",
            "stroller", "pram", "baby walker", "baby swing",
            "lego set", "action figure", "board game", "card game",
            "fidget spinner", "rubik cube", "slime kit", "kinetic sand",
        },
        "keywords": {
            "toy", "puzzle", "lego", "diaper", "stroller", "wipes",
            "pacifier", "onesie", "rattle", "plush", "scooter",
            "doll", "baby", "kids", "child", "toddler",
            "infant", "newborn", "school", "drawing",
        },
    },
    "pets": {
        "priority": 7,
        "anchors": {
            "dog food", "cat food", "dry kibble", "wet pet food",
            "pet collar", "dog harness", "cat tree", "pet carrier",
            "automatic pet feeder", "aquarium setup", "fish tank",
        },
        "keywords": {
            "dog", "cat", "litter", "treats", "aquarium",
            "grooming", "cage", "harness", "pet", "puppy",
            "kitten", "fish", "bird", "hamster",
        },
    },
    "office_and_stationery": {
        "priority": 6,
        "anchors": {
            "standing desk", "monitor arm", "ergonomic chair",
            "whiteboard", "bulletin board",
            "fountain pen", "gel pen set", "notebook journal", "planner book",
        },
        "keywords": {
            "notebook", "pen", "desk", "chair",
            "printer", "paper", "marker", "folder", "diary",
            "planner", "stapler", "calculator", "ink", "office",
            "stationery", "filing", "binder",
        },
    },
    "health_and_medical": {
        "priority": 8,
        "anchors": {
            "blood pressure monitor", "glucose monitor", "pulse oximeter",
            "electric massager", "neck massager", "back massager",
            "first aid kit", "vitamin d3", "omega 3", "multivitamin",
            "immunity booster", "n95 mask", "surgical mask",
            "pain relief patch", "orthopaedic support",
        },
        "keywords": {
            "thermometer", "vitamins", "mask",
            "sanitizer", "first aid", "scale", "oximeter",
            "braces", "inhaler", "test kit", "health", "medical",
            "medicine", "immune", "digestion",
        },
    },
    "tools_and_hardware": {
        "priority": 6,
        "anchors": {
            "cordless drill", "power drill", "impact driver",
            "angle grinder", "jigsaw", "circular saw",
            "multimeter", "soldering iron", "oscilloscope",
            "toolbox set", "tool kit",
        },
        "keywords": {
            "drill", "screwdriver", "wrench", "saw", "tape",
            "hammer", "screws", "pliers", "ladder",
            "glue", "nails", "hinge", "tools", "hardware",
        },
    },
    "grocery_and_food": {
        "priority": 6,
        "anchors": {
            "cold pressed oil", "organic honey", "protein bar", "energy bar",
            "energy drink", "zero sugar drink", "keto snacks",
            "instant noodles", "ready to eat", "makhana", "roasted makhana",
            "dark chocolate", "mixed nuts", "trail mix", "dried fruits",
        },
        "keywords": {
            "coffee", "tea", "snacks", "chocolate", "dry fruits",
            "oil", "rice", "spices", "honey", "noodles", "sauce",
            "cereal", "pasta", "biscuit", "food", "drink", "beverage",
            "grocery", "organic", "natural",
        },
    },
    # Fan merchandise / event-driven trends (e.g. a team wins → fans buy jerseys).
    # Kept distinct from `fashion` so downstream curation can target merch directly.
    "sports_and_merch": {
        "priority": 9,
        "anchors": {
            "team jersey", "cricket jersey", "football jersey", "fan jersey",
            "ipl jersey", "rcb jersey", "csk jersey", "mi jersey",
            "world cup jersey", "fan merchandise", "fan merch", "official merch",
            "team merchandise", "signed memorabilia", "collectible figure",
            "limited edition drop", "anime figure", "funko pop",
        },
        "keywords": {
            "jersey", "merch", "merchandise", "memorabilia", "collectible",
            "fan", "supporter", "fandom", "poster", "flag", "scarf", "mug",
            "hoodie", "tshirt", "cap", "wristband", "keychain", "sticker",
            "figurine", "trophy", "replica",
        },
    },
}

# ── Hard exclusion zones ──────────────────────────────────────────────────────
# If ANY trigger term appears in the topic+tags haystack, those categories are
# completely removed from consideration regardless of keyword matches.
TOPIC_EXCLUSIONS: dict[str, set[str]] = {
    # Electronic product anchors exclude lifestyle/food categories
    "earbuds": {"fashion", "home", "grocery_and_food", "beauty", "pets"},
    "tws": {"fashion", "home", "grocery_and_food", "beauty"},
    "airpods": {"fashion", "home", "grocery_and_food", "beauty"},
    "neckband": {"fashion", "home", "grocery_and_food"},
    "smartphone": {"fashion", "home", "beauty", "grocery_and_food"},
    "laptop": {"fashion", "home", "beauty", "grocery_and_food"},
    "powerbank": {"fashion", "home", "beauty", "grocery_and_food"},
    "power bank": {"fashion", "home", "beauty", "grocery_and_food"},
    # Fashion anchors exclude electronics
    "kurta": {"electronics", "automotive", "tools_and_hardware"},
    "saree": {"electronics", "automotive", "tools_and_hardware"},
    "lehenga": {"electronics", "automotive", "tools_and_hardware"},
    "dress": {"electronics", "automotive", "tools_and_hardware"},
    # Food/fitness
    "recipe": {"electronics", "fashion", "automotive", "tools_and_hardware"},
    "protein powder": {"fashion", "automotive", "tools_and_hardware", "office_and_stationery"},
    # Entertainment — prevent media titles from mapping to product categories
    "cricket match": {"electronics", "beauty", "grocery_and_food"},
    "ipl 2026": {"electronics", "beauty", "grocery_and_food"},
    # Fan merch — a "jersey"/"merch" topic is apparel-adjacent, not electronics/food
    "jersey": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
    "merchandise": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
    "fan merch": {"electronics", "grocery_and_food", "tools_and_hardware", "automotive"},
}

STOPWORDS = frozenset({
    "a", "an", "the", "in", "of", "for", "with", "is", "are", "was", "were",
    "and", "or", "on", "at", "to", "by", "from",
})

# ── Shared helpers ────────────────────────────────────────────────────────────
_WORD_SPLIT_RE = re.compile(r"\W+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_words(text: str) -> set[str]:
    return {w for w in _WORD_SPLIT_RE.split(text.lower())
            if w and w not in STOPWORDS}


def normalize_topic(title: str) -> str:
    return _PUNCT_RE.sub("", title.lower()).strip()
