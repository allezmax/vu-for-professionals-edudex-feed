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
DEFAULT_PROGRAM_LEVEL = "post-hbo"  # most VU-for-Professionals executive education sits here
DEFAULT_DEGREE = "certificate of participation"
DEFAULT_APPLICATION_TYPE = "individual"
DEFAULT_PAYMENT_DUE = "up-front"
DEFAULT_START_DATE_DETERMINATION = "fixed starting date"


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
