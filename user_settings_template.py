# =============================================================
# user_settings_template.py — COPY THIS FILE TO user_settings.py
#
# Steps:
#   1. Copy this file:  cp user_settings_template.py user_settings.py
#   2. Fill in your API keys and customise the sections below.
#   3. Never commit user_settings.py — it is listed in .gitignore.
#
# Any value set in user_settings.py overrides the default in config.py.
# =============================================================


# ── API KEYS ──────────────────────────────────────────────────
# IEEE:   Free registration at https://developer.ieee.org/
#         Key can take up to 24 h to activate after registration.
IEEE_API_KEY   = ""

# Scopus: Register at https://dev.elsevier.com/
#         Requires an active institutional (university) subscription
#         and access from the university network or VPN.
SCOPUS_API_KEY = ""

# PubMed: Optional free key at https://www.ncbi.nlm.nih.gov/account/
#         Without key: 3 requests/sec  |  With key: 10 requests/sec
PUBMED_API_KEY = ""

# ArXiv:  No API key required — works out of the box.


# ── DATE RANGE ───────────────────────────────────────────────
START_YEAR = 2020
END_YEAR   = 2025


# ── MAX RESULTS ───────────────────────────────────────────────
# Maximum papers to retrieve per database per run.
# Set to a large number (e.g. 10000) to retrieve everything available.
MAX_RESULTS = 100


# ── SEARCH FIELDS ────────────────────────────────────────────
# Control which parts of a paper are searched in every database.
# Set True to include a field, False to exclude it.
#
# all_fields=True  → searches everything each database indexes
#                    (overrides the individual flags below)
# all_fields=False → only the fields explicitly set to True are searched
SEARCH_FIELDS = {
    "all_fields": False,   # True = search everything (ignores title/abstract/keywords below)
    "title":      True,
    "abstract":   True,
    "keywords":   True,
}


# ── SEARCH QUERY ─────────────────────────────────────────────
# Structure: list of groups.
#   • Terms INSIDE a group are combined with  OR
#   • Groups are combined with               AND
#
# Example below searches for:
#   ("deep learning" OR "machine learning" OR "neural network" OR "artificial intelligence")
#   AND ("healthcare" OR "clinical" OR "medical")
#   AND ("prediction" OR "diagnosis" OR "prognosis" OR "detection")
#
# Replace with your own topics.
QUERY_GROUPS = [
    [
        "deep learning", "machine learning", "neural network", "artificial intelligence",
    ],
    [
        "healthcare", "clinical", "medical",
    ],
    [
        "prediction", "diagnosis", "prognosis", "detection",
    ],
]


# ── CATEGORIZATION DIMENSIONS ────────────────────────────────
# Each top-level key becomes a column in the output CSV.
# Each inner key is a label; its list contains the keywords
# (lowercase) to look for in a paper's title + abstract.
# The FIRST matching label wins — order matters.
# Papers that match nothing get the label "Unclassified".
#
# Add, rename, or remove dimensions and categories freely.
#
# Used by categorize.py / generate_report.py for ALL fetched papers
# in papers.csv (before screening) — a separate, manually-maintained
# keyword system. It is independent of categorize_xlsx.py, which
# categorizes only Include papers via the LLM (see CATEGORY_DISCOVERY
# below).
CATEGORIZATION_DIMENSIONS = {
    "clinical_application": {
        "Medical Imaging":    ["imaging", "radiology", "mri", "ct scan"],
        "Disease Prediction": ["prediction", "prognosis", "mortality", "risk"],
        "Clinical NLP":       ["nlp", "clinical notes", "text mining"],
        "Drug & Treatment":   ["drug", "treatment", "therapy", "medication"],
        "Patient Monitoring": ["monitoring", "wearable", "icu", "vital sign"],
        "Genomics":           ["genomic", "genetics", "sequencing", "biomarker"],
        "General Clinical":   ["clinical", "patient", "healthcare", "medical"],
    },
    "ml_method": {
        "Deep Learning":          ["deep learning", "neural network", "transformer"],
        "Large Language Model":   ["llm", "gpt", "bert", "foundation model"],
        "Classical ML":           ["random forest", "svm", "gradient boosting"],
        "Federated Learning":     ["federated learning", "privacy-preserving"],
        "Reinforcement Learning": ["reinforcement learning", "q-learning"],
        "General ML / AI":        ["machine learning", "artificial intelligence"],
    },
    "data_type": {
        "Medical Imaging Data": ["image", "scan", "segmentation"],
        "EHR / Structured":     ["ehr", "electronic health record", "tabular"],
        "Clinical Text":        ["clinical note", "discharge summary", "free text"],
        "Wearable / Signal":    ["wearable", "ecg", "eeg", "time series"],
        "Multi-modal":          ["multimodal", "fusion", "heterogeneous"],
    },
}

# ── CATEGORY DISCOVERY (categorize_xlsx.py, pass 2) ──────────
# categorize_xlsx.py first asks the model for a short free-text label per
# paper for each column below. Then, for each column listed here, it merges
# all the distinct labels it collected into at most N broader categories.
# Columns not listed here keep their free-text labels as-is.
CATEGORY_DISCOVERY = {
    "healthcare_type":       10,
    "trustworthiness_type":  5,
    "agentic_part":          5,
}
