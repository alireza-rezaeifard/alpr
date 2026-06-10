"""
plate_reference.py
Static reference data for Iranian license plate classification.
Synced with the official plate dataset (Vehicle registration plates of Iran).

Plate structure: [DD][L][DDD][RR]
  DD  = 2-digit prefix (display left)
  L   = 1 series letter
  DDD = 3-digit number
  RR  = 2-digit region code (rightmost, determines province)

Serial format shown on plate: ## X ### - NN
"""

# ---------------------------------------------------------------------------
# Letter → canonical category key
# The DTRB model outputs latin letters (0-9a-z). Both Persian and latin
# equivalents resolve to the same category key so encoding is irrelevant.
# Latin equivalents follow the official transliteration table.
# ---------------------------------------------------------------------------

LETTER_TO_CATEGORY: dict[str, str] = {
    # Private / personal vehicles (black on white)
    "b": "Private",   # ب
    "j": "Private",   # ج
    "d": "Private",   # د
    "s": "Private",   # س
    "l": "Private",   # ل
    "m": "Private",   # م
    "n": "Private",   # ن
    "v": "Private",   # و
    "o": "Private",   # و  (alternative latin for و)
    "u": "Private",   # و  (alternative latin for و)
    "w": "Private",   # و  (alternative latin for و)
    "h": "Private",   # هـ
    "y": "Private",   # ی
    "i": "Private",   # ی  (alternative latin for ی)
    "q": "Private",   # ق
    "r": "Private",   # ر
    "x": "Private",   # خ

    # Taxi (black on yellow) — letter ت, plate also shows English "TAXI"
    "t": "Taxi",       # ت

    # Agricultural (black on yellow)
    "k": "Agricultural",  # ک

    # Government (white on red)
    "a": "Government",   # الف

    # Police / FARAJA (white on dark green)
    "p": "Police",        # پ

    # IRGC (white on dark green)
    "c": "Military_IRGC", # ث  (DTRB maps ث -> c)

    # Army – IRIA (black on light brown)
    "e": "Military_Army", # ش / ه

    # Ministry of Defence (white on light blue)
    "z": "Military_Defence",  # ز

    # General Staff of Armed Forces (white on light blue)
    "f": "Military_GeneralStaff",  # ف

    # Temporary passage / transit (new imports)
    "g": "Temporary_Transit",  # گ

    # Private vehicles of people with disabilities (black on white)
    "ژ": "Disabled",

    # Diplomatic / Consular
    "diplomatic": "Diplomatic",
}

# Persian-letter direct lookup (for plates that arrive in Persian encoding)
PERSIAN_LETTER_TO_CATEGORY: dict[str, str] = {
    "ب": "Private",
    "ج": "Private",
    "د": "Private",
    "س": "Private",
    "ص": "Private",
    "ط": "Private",
    "ق": "Private",
    "ل": "Private",
    "م": "Private",
    "ن": "Private",
    "و": "Private",
    "ه": "Private",
    "ی": "Private",
    "ر": "Private",
    "خ": "Private",
    "ت": "Taxi",          # تاکسی
    "ع": "Public",        # عمومی (public vehicles, yellow)
    "ک": "Agricultural",
    "ا": "Government",
    "پ": "Police",
    "ث": "Military_IRGC",
    "ش": "Military_Army",
    "ز": "Military_Defence",
    "ف": "Military_GeneralStaff",
    "گ": "Temporary_Transit",
    "ژ": "Disabled",
}

# ---------------------------------------------------------------------------
# Category → color scheme (one of: white | yellow | green | red | blue | black)
# Derived from the official plate-type colour table.
# ---------------------------------------------------------------------------

CATEGORY_TO_COLOR: dict[str, str] = {
    "Private":               "white",   # black on white
    "Taxi":                  "yellow",  # black on yellow
    "Public":                "yellow",  # black on yellow
    "Agricultural":          "yellow",  # black on yellow
    "Government":            "red",     # white on red
    "Police":                "green",   # white on dark green
    "Military_IRGC":         "green",   # white on dark green
    "Military_Army":         "black",   # black on light brown
    "Military_Defence":      "blue",    # white on light blue
    "Military_GeneralStaff": "blue",    # white on light blue
    "Temporary_Transit":     "white",
    "Disabled":              "white",   # black on white (with ♿ symbol)
    "Diplomatic":            "black",
    "FreeZone":              "white",   # black on white (Free Zone)
    "FreeZone_Arvand":       "white",   # black on white
    "Unknown":               "white",
}

# Category → human-readable display name (Persian + English)
CATEGORY_DISPLAY: dict[str, str] = {
    "Private":               "شخصی (Private)",
    "Taxi":                  "تاکسی (Taxi)",
    "Public":                "عمومی (Public)",
    "Agricultural":          "کشاورزی (Agricultural)",
    "Government":            "دولتی (Government)",
    "Police":                "انتظامی (Police / FARAJA)",
    "Military_IRGC":         "سپاه پاسداران (IRGC)",
    "Military_Army":         "ارتش (Army – IRIA)",
    "Military_Defence":      "وزارت دفاع (Ministry of Defence)",
    "Military_GeneralStaff": "ستاد کل (General Staff)",
    "Temporary_Transit":     "گذر موقت (Temporary / Transit)",
    "Disabled":              "معلولین و جانبازان (Disabled)",
    "Diplomatic":            "سیاسی / دیپلماتیک (Diplomatic)",
    "FreeZone":              "منطقه آزاد (Free Zone)",
    "FreeZone_Arvand":       "منطقه آزاد (Free Zone)",
    "Unknown":               "نامشخص (Unknown)",
}

# ---------------------------------------------------------------------------
# Free-zone markers (5-digit numeric format; no series letter)
# ---------------------------------------------------------------------------

FREE_ZONE_PREFIXES: dict[str, str] = {
    "10": "منطقه آزاد اروند (Arvand Free Zone)",
    "11": "منطقه آزاد اروند (Arvand Free Zone)",
    "20": "منطقه آزاد انزلی (Anzali Free Zone)",
    "22": "منطقه آزاد اروند (Arvand Free Zone)",
    "30": "منطقه آزاد ارس (Aras Free Zone)",
    "33": "منطقه آزاد ارس (Aras Free Zone)",
    "40": "منطقه آزاد کیش (Kish Free Zone)",
    "44": "منطقه آزاد انزلی (Anzali Free Zone)",
    "50": "منطقه آزاد ماکو (Maku Free Zone)",
    "55": "منطقه آزاد ارس (Aras Free Zone)",
    "60": "منطقه آزاد چابهار (Chabahar Free Zone)",
    "66": "منطقه آزاد کیش (Kish Free Zone)",
    "70": "منطقه آزاد قشم (Qeshm Free Zone)",
    "77": "منطقه آزاد ماکو (Maku Free Zone)",
    "80": "منطقه آزاد قصرشیرین (Qasr-e Shirin Free Zone)",
    "88": "منطقه آزاد چابهار (Chabahar Free Zone)",
    "90": "منطقه آزاد مازندران (Mazandaran Free Zone)",
    "99": "منطقه آزاد قشم (Qeshm Free Zone)",
}

# ---------------------------------------------------------------------------
# Region code → province / region name (2-digit string)
# Synced with the official province_codes allocation table.
# Codes 39, 70, 80, 90 are not allocated and are intentionally absent.
# ---------------------------------------------------------------------------

REGION_CODE_TO_PROVINCE: dict[str, str] = {
    # Tehran City
    "10": "تهران (Tehran)",
    "11": "تهران (Tehran)",
    "20": "تهران (Tehran)",
    "22": "تهران (Tehran)",
    "33": "تهران (Tehran)",
    "40": "تهران (Tehran)",
    "44": "تهران (Tehran)",
    "50": "تهران (Tehran)",
    "55": "تهران (Tehran)",
    "60": "تهران (Tehran)",
    "66": "تهران (Tehran)",
    "77": "تهران (Tehran)",
    "88": "تهران (Tehran)",
    "99": "تهران (Tehran)",
    # Tehran / Alborz
    "21": "البرز (Alborz)",
    "30": "البرز (Alborz)",
    "38": "البرز (Alborz)",
    "68": "البرز (Alborz)",
    "78": "البرز (Alborz)",
    # Razavi Khorasan
    "12": "خراسان رضوی (Razavi Khorasan)",
    "32": "خراسان رضوی (Razavi Khorasan)",
    "36": "خراسان رضوی (Razavi Khorasan)",
    "42": "خراسان رضوی (Razavi Khorasan)",
    "74": "خراسان رضوی (Razavi Khorasan)",
    # Isfahan
    "13": "اصفهان (Isfahan)",
    "23": "اصفهان (Isfahan)",
    "43": "اصفهان (Isfahan)",
    "53": "اصفهان (Isfahan)",
    "67": "اصفهان (Isfahan)",
    # Fars
    "63": "فارس (Fars)",
    "73": "فارس (Fars)",
    "83": "فارس (Fars)",
    "93": "فارس (Fars)",
    # Mazandaran
    "62": "مازندران (Mazandaran)",
    "72": "مازندران (Mazandaran)",
    "82": "مازندران (Mazandaran)",
    "92": "مازندران (Mazandaran)",
    # Khuzestan
    "14": "خوزستان (Khuzestan)",
    "24": "خوزستان (Khuzestan)",
    "34": "خوزستان (Khuzestan)",
    # Gilan
    "46": "گیلان (Gilan)",
    "56": "گیلان (Gilan)",
    "76": "گیلان (Gilan)",
    # Kermanshah
    "19": "کرمانشاه (Kermanshah)",
    "29": "کرمانشاه (Kermanshah)",
    # Lorestan
    "31": "لرستان (Lorestan)",
    "41": "لرستان (Lorestan)",
    # North Khorasan
    "26": "خراسان شمالی (North Khorasan)",
    # South Khorasan
    "52": "خراسان جنوبی (South Khorasan)",
    # Bushehr
    "48": "بوشهر (Bushehr)",
    "58": "بوشهر (Bushehr)",
    # Golestan
    "59": "گلستان (Golestan)",
    "69": "گلستان (Golestan)",
    # Chaharmahal and Bakhtiari
    "71": "چهارمحال و بختیاری (Chaharmahal and Bakhtiari)",
    "81": "چهارمحال و بختیاری (Chaharmahal and Bakhtiari)",
    # Hormozgan
    "84": "هرمزگان (Hormozgan)",
    "94": "هرمزگان (Hormozgan)",
    # Qazvin
    "79": "قزوین (Qazvin)",
    "89": "قزوین (Qazvin)",
    # Markazi
    "47": "مرکزی (Markazi)",
    "57": "مرکزی (Markazi)",
    # Zanjan
    "87": "زنجان (Zanjan)",
    "97": "زنجان (Zanjan)",
    # Hamadan
    "18": "همدان (Hamadan)",
    "28": "همدان (Hamadan)",
    # East Azerbaijan
    "15": "آذربایجان شرقی (East Azerbaijan)",
    "25": "آذربایجان شرقی (East Azerbaijan)",
    "35": "آذربایجان شرقی (East Azerbaijan)",
    # West Azerbaijan
    "17": "آذربایجان غربی (West Azerbaijan)",
    "27": "آذربایجان غربی (West Azerbaijan)",
    "37": "آذربایجان غربی (West Azerbaijan)",
    # Sistan and Baluchestan
    "85": "سیستان و بلوچستان (Sistan and Baluchestan)",
    "95": "سیستان و بلوچستان (Sistan and Baluchestan)",
    # Yazd
    "54": "یزد (Yazd)",
    "64": "یزد (Yazd)",
    # Semnan
    "86": "سمنان (Semnan)",
    "96": "سمنان (Semnan)",
    # Kerman
    "45": "کرمان (Kerman)",
    "65": "کرمان (Kerman)",
    "75": "کرمان (Kerman)",
    # Kohgiluyeh and Boyer-Ahmad
    "49": "کهگیلویه و بویراحمد (Kohgiluyeh and Boyer-Ahmad)",
    # Qom
    "16": "قم (Qom)",
    # Kurdistan
    "51": "کردستان (Kurdistan)",
    "61": "کردستان (Kurdistan)",
    # Ilam
    "98": "ایلام (Ilam)",
    # Ardabil
    "91": "اردبیل (Ardabil)",
}
