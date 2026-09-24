"""
Controlled vocabularies (enumerations) for the EDU-DEX ``program`` XML schema.

Source of truth: these values were extracted directly from EDU-DEX's own
technical-reference application (https://edudex.nl/edudox/ -> "program" tab),
which exposes its field database as a JSON object (``window.EXvue.dataitems``)
in the browser. That is the same data EDU-DEX's own documentation site renders
from, so it should track the real program.xsd closely -- but XSDs do change,
which is why ``validate.py`` re-downloads and validates against the live XSD
files on every run instead of trusting this file blindly.

If EDU-DEX ever changes an enumeration, the CI validation step will fail
loudly with the real error from the real schema. Fix it here.
"""
from __future__ import annotations

import re

# --- programClassification > programForm ------------------------------------------------
# minOccurs=1, maxOccurs=3 (a program may combine e.g. part-time + evening education)
PROGRAM_FORM = {
    "evening education": "avondonderwijs",
    "part-time": "deeltijd",
    "dual": "duaal",
    "distance learning": "offline zelfstudie (afstandsonderwijs)",
    "e-learning": "online zelfstudie (e-learning)",
    "virtual classroom": "virtual classroom",
    "full-time": "voltijd",
}

# --- programClassification > programLevel  (and programAdmission > requiredLevel) -------
# NLQF/CROHO/CREBO-based level ladder. "none" = courses without a formal level.
PROGRAM_LEVEL = {
    "havo": "havo",
    "hbo": "hbo",
    "associate": "hbo associate degree",
    "bachelor": "hbo bachelor",
    "master": "hbo master",
    "lbo": "lbo",
    "mavo": "mavo",
    "mbo": "mbo",
    "mbo+": "mbo +",
    "mbo niveau 1": "mbo niveau 1",
    "mbo niveau 2": "mbo niveau 2",
    "mbo niveau 3": "mbo niveau 3",
    "mbo niveau 4": "mbo niveau 4",
    "none": "niet van toepassing",
    "PhD": "PhD",
    "post-academic": "post-academisch",
    "post-hbo": "post-hbo",
    "propedeuse": "propedeuse",
    "vbo": "vbo",
    "vmbo": "vmbo",
    "vmbo/mavo": "vmbo/mavo",
    "vwo": "vwo",
    "wo": "wo",
    "academic bachelor": "wo bachelor",
    "academic master": "wo master",
}

# --- programClassification > programType ------------------------------------------------
PROGRAM_TYPE = {
    "coaching": "coaching",
    "conference": "conferentie",
    "document": "document",
    "exam": "examen",
    "lecture": "lecture",
    "educational": "lerarenopleiding",
    "master class": "masterclass",
    "mbo module": "mbo module",
    "regular": "reguliere cursus/opleiding",
    "research": "research-opleiding",
    "internship": "stage",
    "traineeship": "traineeship",
    "training": "training",
    "virtual classroom": "virtual classroom",
    "webinar": "webinar",
    "workshop": "workshop",
    "self study": "zelfstudie",
}

# --- programClassification > degree -------------------------------------------------------
# Large controlled vocabulary of certificate/diploma labels. This is only a
# subset most relevant to executive-education programs; the "none",
# "certificate", "certificate of participation", "testimonial", "diploma",
# "MBA", "DBA" entries cover almost everything VU for Professionals offers.
DEGREE = {
    "none": "geen certificaat of diploma",
    "certificate": "certificaat",
    "certificate of participation": "bewijs van deelname",
    "certificate on request": "certificaat op verzoek",
    "testimonial": "getuigschrift",
    "diploma": "diploma",
    "module certificate": "module certificaat",
    "MBA": "MBA",
    "DBA": "DBA",
    "MSc": "MSc",
    "MA": "MA",
    "LLM": "LLM",
    "PhD": "PhD",
}

# --- programAdmission > applicationType --------------------------------------------------
APPLICATION_TYPE = {
    "individual": "individuele aanmelding",
    "group": "groepsaanmelding",
}

# --- programAdmission > paymentDue -------------------------------------------------------
PAYMENT_DUE = {
    "up-front": "vooraf",
    "installments": "in termijnen",
    "afterwards": "achteraf",
}

# --- programAdmission > startDateDetermination -------------------------------------------
START_DATE_DETERMINATION = {
    "fixed starting date": "vastgestelde startmomenten",
    "agreed starting date": "overeengekomen startdatum",
    "direct start": "directe start",
}

# --- programSchedule > programRun > cost > costType --------------------------------------
COST_TYPE = {
    "tuition fee": "lesgeld",
    "registration fee": "inschrijfgeld",
    "study material": "studiematerialen",
    "certificate": "certificaat/diploma",
    "examination": "examen",
    "excursions": "excursies",
    "location": "locatiekosten (zaalhuur, apparatuur e.d.)",
    "dinner": "diner",
    "lunch": "lunch",
    "accommodation": "verblijf/overnachting",
    "second accommodation": "partnerovernachting",
    "single payment discount": "korting bij betaling in één keer",
    "cost of living": "levensonderhoud",
    "housing": "huisvesting",
    "insurance": "verzekeringen",
    "visa/permit": "visa",
    "coaching": "coaching",
}

# --- cost > VATCode -----------------------------------------------------------------------
VAT_CODE = {
    "1": "geen btw (0%)",
    "2": "btw verlegging (0%)",
    "3": "aankoop goederen laag tarief (9%)",
    "4": "aankoop goederen hoog tarief (21%)",
    "5": "aankoop diensten hoog tarief (21%)",
}

# --- cost > period / studyLoad @period ----------------------------------------------------
PERIOD = {
    "1st year": "1e jaar",
    "day": "dag(en)",
    "program": "gehele opleiding",
    "year": "jaar",
    "month": "maanden",
    "hour": "uur",
    "week": "weken",
}

# --- programCurriculum > instructionMode --------------------------------------------------
INSTRUCTION_MODE = {
    "classroom teaching": "klassikaal les",
    "blended learning": "blended learning",
    "case study": "case studies",
    "coaching": "coaching",
    "group discussion": "groepsdiscussie",
    "group assignment": "groepsopdracht",
    "individual guidance": "individuele begeleiding",
    "individual assignment": "individuele opdracht",
    "literature study": "literatuurstudie",
    "project": "project",
    "seminar": "seminar",
    "self study": "zelfstudie",
    "thesis": None,
    "virtual classroom": "virtual classroom",
    "webinar": "webinar",
    "working group": "werkgroepen",
    "workshop": "workshop",
    "training": "training",
    "internship": "stage",
    "excursion": "excursie",
    "home study": "thuisstudie",
}

# ---------------------------------------------------------------------------------------
# Heuristic Dutch-text -> EDU-DEX-code lookups used by scrape.py / xmlgen.py when turning
# free text found on a VU course page into a controlled-vocabulary value. These are NOT
# from EDU-DEX; they are our own best-guess mapping and MUST be reviewed per program the
# first time a program is added (see config/overrides.yaml). Anything not matched falls
# back to a safe default and is flagged in the "needs_review" report.
# ---------------------------------------------------------------------------------------

VU_FORM_TEXT_TO_CODE = {
    "klassikaal": "part-time",  # VU's "klassikaal, deeltijd" executive-ed programs are part-time in EDU-DEX's sense
    "online": "e-learning",
    "blended": "part-time",
    "virtual classroom": "virtual classroom",
    "voltijd": "full-time",
    "deeltijd": "part-time",
    "duaal": "dual",
    "avond": "evening education",
    # English equivalents -- NOTE (2026-09-22): this table previously had no
    # English entries at all, so an English page's own form text (e.g. the
    # new "technical study details" USP-bar duration line, "4+ years
    # (part-time)" -- see scrape.py's _parse_usp_bar) could never actually
    # MATCH here; it happened to still come out right by falling through to
    # DEFAULT_PROGRAM_FORM ("part-time"), but silently flagged for review as
    # an unverified guess even when the page said so in plain English.
    "part-time": "part-time",
    "full-time": "full-time",
}

VU_TYPE_TEXT_TO_CODE = {
    "leergang": "regular",
    "opleiding": "regular",
    "cursus": "regular",
    "training": "training",
    "module": "regular",
    "masterclass": "master class",
    "workshop": "workshop",
    "webinar": "webinar",
    "congres": "conference",
    "conferentie": "conference",
    "traineeship": "traineeship",
    "mba": "regular",
    "pre-master": "regular",
    "phd": "research",
}

# Default when nothing else can be inferred; deliberately conservative.
DEFAULT_PROGRAM_FORM = "part-time"
DEFAULT_PROGRAM_TYPE = "regular"
DEFAULT_DEGREE = "certificate of participation"
DEFAULT_APPLICATION_TYPE = "individual"
DEFAULT_PAYMENT_DUE = "installments"
DEFAULT_START_DATE_DETERMINATION = "fixed starting date"

# --- programClassification > programLevel guessing ----------------------------------------
# Per VU (2026-09-08): "our parttime MScs are academic masters, our phds are PhD and
# most other programs are post-academic. Only if you find clear indication that
# post-hbo should be used, use it. Flag when doubt." -- so post-hbo is intentionally
# NOT a default; it is only ever used when a program's own title/text says so
# explicitly. When we can't tell anything at all about a program (no title/heading/
# description text to even look at), fall back to "none" rather than guessing a level
# ("Use the fallback 'none'" -- VU, 2026-09-08).
LEVEL_KEYWORDS: list[tuple[str, str]] = [
    ("phd", "PhD"),
    ("doctoral", "PhD"),
    ("promotietraject", "PhD"),
    ("msc", "academic master"),
    ("master of science", "academic master"),
    ("post-hbo", "post-hbo"),
    ("post hbo", "post-hbo"),
]
DEFAULT_PROGRAM_LEVEL_KNOWN_CATEGORY = "post-academic"  # VU for Professionals' general offering
DEFAULT_PROGRAM_LEVEL = "none"  # true last-resort: we don't even know enough to guess


# --- shared keyword-matching precision guards ----------------------------------------------
# Both guessers above scan free text for short controlled-vocabulary abbreviations
# ("msc", "mba", "dba", "phd", ...). A plain substring check matches those inside
# ordinary words too often to trust (see guess_degree's docstring for the real
# "feedback" -> "dba" collision found live 2026-09-11), so matches require a
# non-alphanumeric (or string-boundary) character on both sides.
_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _keyword_present(needle: str, haystack: str) -> bool:
    pattern = _KEYWORD_PATTERN_CACHE.get(needle)
    if pattern is None:
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])")
        _KEYWORD_PATTERN_CACHE[needle] = pattern
    return pattern.search(haystack) is not None


# Cues that a nearby degree keyword describes a person's own academic
# background (a faculty/lecturer bio) rather than the credential this
# program awards its students -- confirmed live 2026-09-11 on the Parttime
# MSc Marketing page, whose curriculum text names a lecturer's own "PhD
# (2001) in Marketing" in a bio paragraph.
#
# UPDATE 2026-09-22 (Max, reviewing the Sept 18 export): reconfirmed with two
# more concrete cases, both docent bios under "Executive Master in Coaching"
# and "Digital Innovation & Transformation" / "Data- en AI-gedreven Sturing"
# (the latter two share the same lecturer bio block, Dr. Marijn Plomp, reused
# across several programme pages). Neither was caught by the cue list below
# as it stood:
#   - "Ze heeft als coach en mentor vele executives, (PhD) studenten en
#     klanten kunnen helpen..." -- uses "Ze" (the common informal Dutch
#     "she"), not "zij", which wasn't in the cue list at all.
#   - "Marjan is door Ashridge Hult geaccrediteerd als executive coach in
#     2015 (MSc)..." -- names the person by her first name instead of a
#     pronoun, so no pronoun cue could ever have caught it; "geaccrediteerd"
#     (accredited) is the actual tell here -- a credential someone is
#     *accredited with*, not one the programme awards its students.
#   - "Marijn heeft een PhD in Information Systems aan de Universiteit
#     Utrecht, op basis van zijn proefschrift..." -- uses "zijn" (his),
#     likewise absent from the cue list ("hij" was there, "zijn" wasn't).
# Added "ze", "zijn", "geaccrediteerd" and "accredited" below. "zijn" is also
# the ordinary Dutch verb "to be" (extremely common), so this will drop a lot
# of unrelated sentences from the body-text scan too -- that's fine here:
# this text is a last-resort keyword guess that's always flagged for human
# review anyway (see guess_degree's docstring), so being more willing to drop
# a sentence only ever makes the guess MORE conservative, never wrong in a
# new way; the worst case is falling through to the safe
# "certificate of participation" default instead of finding a real keyword.
_BIO_CUE_RE = re.compile(
    # A trailing \b after a literal "." never matches when followed by a space
    # (both sides are non-word characters) -- confirmed live 2026-09-11 on "Het
    # nieuwe Three Lines Model", whose "...onder leiding van prof. dr. ir
    # Frederique Six MBA." was only half-filtered: "prof." matched (its "."
    # is optional, so the engine backs off to bare "prof" for a valid trailing
    # boundary) but "dr." did not, letting "MBA" leak through as this course's
    # own degree. So the period-abbreviation cues below skip the trailing \b
    # entirely -- the literal period already rules out matching inside an
    # ordinary word ("professioneel" has no period after "prof").
    r"\b(hij|zij|ze|zijn|hem|haar|docent|hoogleraar|onderzoeker|promoveerde|behaalde|"
    r"professor|lecturer|researcher|holds a|received (his|her)|his phd|her phd|"
    r"geaccrediteerd|accredited)\b"
    r"|\bprof\.|\bdr\.",
    re.IGNORECASE,
)

# Title abbreviations that can appear standalone, immediately before a
# capitalized name, e.g. "Dr. Marijn Plomp" -- see the BUG FOUND note inside
# _sentences_without_bio_cues below for why these need special handling.
_TITLE_ABBREV_RE = re.compile(r"\b(prof|dr|ir|mr|drs|ing)\.$", re.IGNORECASE)


def _sentences_without_bio_cues(text: str) -> str:
    """Drop sentences that read as a person's own academic-background bio
    before the degree body-text keyword fallback searches what's left.

    Splits only where a sentence-ending punctuation mark is followed by a
    capital letter, not on every ". " -- confirmed live 2026-09-11 that a
    plain ". "-split breaks Dutch "prof. dr. ir <Name> <degree>" titles
    apart (each abbreviation's own period looks like a sentence end), which
    orphaned the actual bio cue ("prof."/"dr.") from the degree mention that
    followed it on "Het nieuwe Three Lines Model" ("...onder leiding van
    prof. dr. ir Frederique Six MBA."), letting "MBA" leak through as if it
    were the course's own degree. Requiring a capital letter after the
    whitespace keeps that whole title in one sentence with its cue.

    BUG FOUND 2026-09-22: that fix isn't enough for a STANDALONE title
    abbreviation immediately followed by a name -- "Dr. Marijn Plomp" (its
    own short line/paragraph introducing a docent bio) -- because the split
    condition (period, then whitespace, then a capital letter) is exactly
    what "Dr. Marijn" looks like too, so it gets cut into its own fragment
    the same way a real sentence boundary would. Confirmed live on Digital
    Innovation & Transformation's and Data- en AI-gedreven Sturing's /inhoud
    pages, both of which introduce the same reused lecturer bio with a
    standalone "Dr. Marijn Plomp" line right before "Marijn heeft een PhD in
    Information Systems...": once "Dr." was split off into its own fragment,
    the sentence stating his PhD had no bio cue left in it at all, and "PhD"
    leaked through as if it were this course's own awarded degree. Fix: merge
    a fragment that ends in a bare title abbreviation back onto the sentence
    that immediately follows it before running the bio-cue filter, rather
    than trying to stop them from splitting apart in the first place (the
    "capital letter follows" condition above still has to stay, since that's
    what keeps "prof. dr. ir Name" together when nothing else does).
    """
    if not text:
        return text
    raw_sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\u00c0-\u00de])", text)
    sentences: list[str] = []
    for s in raw_sentences:
        if sentences and _TITLE_ABBREV_RE.search(sentences[-1].strip()):
            sentences[-1] = sentences[-1] + " " + s
        else:
            sentences.append(s)
    return " ".join(s for s in sentences if not _BIO_CUE_RE.search(s))


def guess_program_level(text: str) -> tuple[str, bool]:
    """Best-effort EDU-DEX programLevel from a program's title/heading/description.

    Returns (code, needs_review). needs_review=True flags a guess for a human to
    confirm -- level is high-stakes enough that VU asked to be shown every guess,
    even the considered "post-academic" default, not just outright unknowns.
    """
    t = (text or "").lower()
    for needle, code in LEVEL_KEYWORDS:
        if _keyword_present(needle, t):
            return code, False  # explicit textual indication, no need to flag
    if t.strip():
        return DEFAULT_PROGRAM_LEVEL_KNOWN_CATEGORY, True
    return DEFAULT_PROGRAM_LEVEL, True


# --- programClassification > degree guessing -----------------------------------------------
# Per Max (2026-09-10): NOT every program ends in a plain certificate of participation --
# PhDs obviously finish with a PhD, and VU runs a growing number of (part-time/executive)
# MSc programs. Defaulting every program to "certificate of participation" was flatly wrong
# for those. Some newer-template course pages state the awarded credential explicitly in a
# "Diploma:"/"Titels:" (or "Degree:"/"Titles:") fact bullet on their "in het kort"/"at a
# glance" list (e.g. "Diploma: MSc", "Titels: MSc, EMFC, Register Controller (RC)") -- that's
# checked first since it's an explicit statement, not a guess. Most VU for Professionals
# short courses genuinely only award a certificate of participation, so that stays the
# fallback default (flagged for review, same as before) rather than being replaced by a
# keyword guess when nothing points elsewhere.
DEGREE_KEYWORDS: list[tuple[str, str]] = [
    ("phd", "PhD"),
    ("doctoral", "PhD"),
    ("promotietraject", "PhD"),
    ("msc", "MSc"),
    ("master of science", "MSc"),
    ("mba", "MBA"),
    ("dba", "DBA"),
    ("llm", "LLM"),
    ("master of laws", "LLM"),
    ("master of arts", "MA"),
]


def guess_degree(explicit_value: str, text: str) -> tuple[str, bool]:
    """Best-effort EDU-DEX ``degree`` from an explicit "Diploma"/"Titels" fact bullet
    first (if the page states one), else a keyword guess over title/heading/description
    text, else the "certificate of participation" default.

    Returns (code, needs_review) -- needs_review=False ONLY for an explicit fact
    bullet match, since that's the program stating its own credential outright.
    Every other outcome is flagged, including a body-text keyword match, even
    though the resulting code is often still correct -- see below for why that
    guess isn't trusted the same way guess_program_level's keyword match is.

    Three rounds of precision problems, all confirmed live 2026-09-11 spot-
    checking the full catalog after the degree-defaulting fix, converged on
    that decision:

    1. Word-boundary matching (``_keyword_present``), not a plain substring
       check -- "Escaperoom Het Huis van Toezicht" was tagged "DBA" because
       its testimonials mention "feedback", which contains the literal
       substring "dba" (fee-D-B-Ack).
    2. Faculty-bio sentence filtering (``_sentences_without_bio_cues``) --
       "Parttime Master of Science in Marketing" was tagged "PhD" because its
       curriculum page names a lecturer's own "PhD (2001) in Marketing", and
       "phd" sorts before "msc"/"master of science" in DEGREE_KEYWORDS.
    3. Even after both of those, "Executive Master in Coaching" still came
       out wrong two different ways from its own coaches' bios: "...vele
       executives, (PhD) studenten en klanten..." (PhD as a type of client
       she coaches, not a credential at all) and "...in 2015 (MSc)..." (an
       accreditation the COACH holds, not what this programme awards) --
       neither reads as a bio sentence in the way #2's guard looks for.

    Rather than keep chasing every new phrasing body text can throw at this
    (a body page's free-form paragraphs -- testimonials, staff bios, client
    descriptions -- are an open-ended source of unrelated keyword mentions,
    unlike the short structured "Diploma"/"Titels" bullet), a body-text match
    is kept as a reasonable best guess but always flagged for a human to
    confirm, the same conservative stance guess_program_level already takes
    on its own considered "post-academic" default.
    """
    explicit = (explicit_value or "").lower()
    for needle, code in DEGREE_KEYWORDS:
        if _keyword_present(needle, explicit):
            return code, False
    # NOTE (2026-09-22): a generic "u ontvangt een diploma" ("you'll receive
    # a diploma") statement -- no MSc/MBA/etc qualifier at all -- is also an
    # explicit statement, just a plainer one than the abbreviations above.
    # Confirmed live on Besturen van Filantropische Fondsen's "Diploma"
    # accordion section ("Je ontvangt na afloop van de opleiding een
    # diploma."), a newer page-template variant (see scrape.py's
    # _parse_accordion_facts) that previously had no degree signal at all and
    # fell all the way to the certificate-of-participation default. Checked
    # only against the explicit fact bullet, not body text -- "diploma" on
    # its own is too generic a word to trust as a body-text keyword guess.
    if _keyword_present("diploma", explicit):
        return "diploma", False
    t = _sentences_without_bio_cues(text or "").lower()
    for needle, code in DEGREE_KEYWORDS:
        if _keyword_present(needle, t):
            return code, True
    return DEFAULT_DEGREE, True


# --- programContacts fallback ---------------------------------------------------------------
# Per VU (2026-09-08): the feed editor (m.merz@vu.nl) builds the feed but is never a
# contact person for students/programs. When a program page has no scraped contact,
# use this named fallback instead of the institute's technical editor address.
FALLBACK_CONTACT_NAME = "René Hulsink"
FALLBACK_CONTACT_EMAIL = "professionals@vu.nl"


def normalize_enum(value: str, table: dict, default: str) -> tuple[str, bool]:
    """Best-effort map of a free-text Dutch value onto an EDU-DEX enum code.

    Returns (code, matched) where matched=False means the default was used
    and this program should be flagged for manual review.
    """
    if not value:
        return default, False
    v = value.strip().lower()
    for needle, code in table.items():
        if needle in v:
            return code, True
    return default, False
