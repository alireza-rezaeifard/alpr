"""
plate_reference.py
Static reference data for Iranian license plate classification.
Sources: Vehicle registration plates of Iran (Wikipedia, content rephrased for compliance).

Plate structure: [DD][L][DDD][RR]
  DD  = 2-digit prefix (display left)
  L   = 1 series letter
  DDD = 3-digit number
  RR  = 2-digit region code (rightmost, determines province)
"""

# ---------------------------------------------------------------------------
# Letter → canonical category key
# The DTRB model outputs latin letters. Both Persian and latin equivalents
# resolve to the same category key so encoding is irrelevant.
# ---------------------------------------------------------------------------

LETTER_TO_CATEGORY: dict[str, str] = {
    # Private / personal vehicles (white plates, black text)
    "b": "Private",   # ب
    "j": "Private",   # ج
    "d": "Private",   # د
    "s": "Private",   # س
    "l": "Private",   # ل
    "m": "Private",   # م
    "n": "Private",   # ن
    "v": "Private",   # و  (maps o/u/v/w -> و in DTRB)
    "o": "Private",   # و  (alternative latin for و)
    "u": "Private",   # و  (alternative latin for و)
    "w": "Private",   # و  (alternative latin for و)
    "h": "Private",   # ه
    "y": "Private",   # ی
    "i": "Private",   # ی  (alternative latin for ی)
    "q": "Private",   # ق
    "r": "Private",   # ر
    "x": "Private",   # خ

    # Taxi / public transport (yellow plates, black text)
    "t": "Taxi",       # ت

    # Agricultural (yellow plates)
    "k": "Agricultural",  # ک

    # Government (red plates, white text)
    "a": "Government",   # ا / الف

    # Police / FARAJA (green plates, white text)
    "p": "Police",        # پ

    # Military – IRGC (green plates)
    "c": "Military_IRGC", # ث  (DTRB maps ث -> c)

    # Military – Army (black plates, light text)
    "e": "Military_Army", # ه  (also Private; Army uses specific series – treated by context)

    # Military – Ministry of Defence (blue plates)
    "z": "Military_Defence",  # ز

    # Military – General Staff (blue plates)
    "f": "Military_GeneralStaff",  # ف

    # Temporary / Transit
    "g": "Temporary_Transit",  # گ

    # Disabled (light-blue plates, blue icon)
    # Disabled plates use special ژ letter; DTRB has no direct equivalent,
    # stored as the Persian key below.
    "ژ": "Disabled",

    # Diplomatic / Political (black plates, gold text)
    # D-series / تشریفات; stored as special markers
    "diplomatic": "Diplomatic",
}

# Persian-letter direct lookup (for plates that come in Persian encoding)
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
    "ت": "Taxi",
    "ع": "Taxi",       # also public/ع (yellow)
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
# ---------------------------------------------------------------------------

CATEGORY_TO_COLOR: dict[str, str] = {
    "Private":              "white",
    "Taxi":                 "yellow",
    "Agricultural":         "yellow",
    "Government":           "red",
    "Police":               "green",
    "Military_IRGC":        "green",
    "Military_Army":        "black",
    "Military_Defence":     "blue",
    "Military_GeneralStaff": "blue",
    "Temporary_Transit":    "white",
    "Disabled":             "blue",
    "Diplomatic":           "black",
    "FreeZone_Arvand":      "white",
    "Unknown":              "white",
}

# Category → human-readable display name
CATEGORY_DISPLAY: dict[str, str] = {
    "Private":              "شخصی (Private)",
    "Taxi":                 "تاکسی / عمومی (Taxi / Public)",
    "Agricultural":         "کشاورزی (Agricultural)",
    "Government":           "دولتی (Government)",
    "Police":               "انتظامی (Police / FARAJA)",
    "Military_IRGC":        "سپاه پاسداران (Military – IRGC)",
    "Military_Army":        "ارتش (Military – Army)",
    "Military_Defence":     "وزارت دفاع (Military – MoD)",
    "Military_GeneralStaff": "ستاد کل (Military – General Staff)",
    "Temporary_Transit":    "تعبوری / موقت (Temporary / Transit)",
    "Disabled":             "معلولین (Disabled)",
    "Diplomatic":           "سیاسی / دیپلماتیک (Diplomatic)",
    "FreeZone_Arvand":      "منطقه آزاد (Free Zone / Arvand)",
    "Unknown":              "نامشخص (Unknown)",
}

# ---------------------------------------------------------------------------
# Free-zone markers (5-digit numeric format; no series letter)
# ---------------------------------------------------------------------------

FREE_ZONE_PREFIXES: dict[str, str] = {
    "22": "منطقه آزاد ارونداروند (Arvand Free Zone)",
    "44": "منطقه آزاد انزلی (Anzali Free Zone)",
    "55": "منطقه آزاد ارس (Aras Free Zone)",
    "66": "منطقه آزاد کیش (Kish Free Zone)",
    "77": "منطقه آزاد ماکو (Maku Free Zone)",
    "88": "منطقه آزاد چابهار (Chabahar Free Zone)",
    "99": "منطقه آزاد قشم (Qeshm Free Zone)",
}

# ---------------------------------------------------------------------------
# Region code → province / region name  (2-digit string)
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
    "55": "تهران (Tehran)",
    "66": "تهران (Tehran)",
    "77": "تهران (Tehran)",
    "88": "تهران (Tehran)",
    "99": "تهران (Tehran)",
    # Alborz
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
    # Khuzestan
    "14": "خوزستان (Khuzestan)",
    "24": "خوزستان (Khuzestan)",
    "34": "خوزستان (Khuzestan)",
    # East Azerbaijan
    "15": "آذربایجان شرقی (East Azerbaijan)",
    "25": "آذربایجان شرقی (East Azerbaijan)",
    "35": "آذربایجان شرقی (East Azerbaijan)",
    # West Azerbaijan
    "17": "آذربایجان غربی (West Azerbaijan)",
    "27": "آذربایجان غربی (West Azerbaijan)",
    "37": "آذربایجان غربی (West Azerbaijan)",
    # Qom
    "16": "قم (Qom)",
    "26": "قم (Qom)",
    # Gilan
    "18": "گیلان (Gilan)",
    "28": "گیلان (Gilan)",
    "48": "گیلان (Gilan)",
    # Mazandaran
    "19": "مازندران (Mazandaran)",
    "29": "مازندران (Mazandaran)",
    "39": "مازندران (Mazandaran)",
    "49": "مازندران (Mazandaran)",
    # Kerman
    "45": "کرمان (Kerman)",
    "56": "کرمان (Kerman)",
    "75": "کرمان (Kerman)",
    # Khorasan North
    "31": "خراسان شمالی (North Khorasan)",
    # Khorasan South
    "41": "خراسان جنوبی (South Khorasan)",
    "51": "خراسان جنوبی (South Khorasan)",
    # Kermanshah
    "46": "کرمانشاه (Kermanshah)",
    "57": "کرمانشاه (Kermanshah)",
    # Lorestan
    "47": "لرستان (Lorestan)",
    "58": "لرستان (Lorestan)",
    # Hamadan
    "52": "همدان (Hamadan)",
    "62": "همدان (Hamadan)",
    # Golestan
    "54": "گلستان (Golestan)",
    "64": "گلستان (Golestan)",
    # Semnan
    "59": "سمنان (Semnan)",
    "69": "سمنان (Semnan)",
    # Yazd
    "61": "یزد (Yazd)",
    "71": "یزد (Yazd)",
    # Chaharmahal and Bakhtiari
    "72": "چهارمحال و بختیاری (Chaharmahal and Bakhtiari)",
    # Zanjan
    "79": "زنجان (Zanjan)",
    "89": "زنجان (Zanjan)",
    # Sistan and Baluchestan
    "81": "سیستان و بلوچستان (Sistan and Baluchestan)",
    "91": "سیستان و بلوچستان (Sistan and Baluchestan)",
    # Bushehr
    "82": "بوشهر (Bushehr)",
    "92": "بوشهر (Bushehr)",
    # Ilam
    "84": "ایلام (Ilam)",
    "98": "ایلام (Ilam)",
    # Kurdistan
    "85": "کردستان (Kurdistan)",
    "95": "کردستان (Kurdistan)",
    # Kohgiluyeh and Boyer-Ahmad
    "86": "کهگیلویه و بویراحمد (Kohgiluyeh and Boyer-Ahmad)",
    "96": "کهگیلویه و بویراحمد (Kohgiluyeh and Boyer-Ahmad)",
    # North Khorasan
    "87": "خراسان شمالی (North Khorasan)",
    "97": "خراسان شمالی (North Khorasan)",
    # Ardabil
    "76": "اردبیل (Ardabil)",
    "65": "اردبیل (Ardabil)",
    # Markazi
    "60": "مرکزی (Markazi)",
    "70": "مرکزی (Markazi)",
    # Hormozgan
    "80": "هرمزگان (Hormozgan)",
    "90": "هرمزگان (Hormozgan)",
}
