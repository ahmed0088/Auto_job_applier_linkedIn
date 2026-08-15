'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08
'''


###################################################### INDEED SEARCH PREFERENCES ######################################################
'''
This is the FIRST version of Indeed support for this tool - unlike the LinkedIn
flow (which has been battle-tested against real runs), this has not yet been
run against a live account. Expect to hit rough edges; paste the console
output back so they can get fixed.

Your name, resume, salary expectations, and AI settings are NOT duplicated
here - they're shared with the LinkedIn bot. See config/questions.py,
config/personals.py, and config/secrets.py for those. This file only holds
what's specific to searching and applying on Indeed.
'''

# Enter your search terms inside '[ ]' with quotes for each search, separated by
# commas. One search is run per term. Eg: ["Software Engineer", "Python Developer"]
search_terms = ["Software Engineer"]

# Where to search. Indeed accepts a city/state/zip, e.g. "Austin, TX", or "Remote".
# Leave as "" to search everywhere.
search_location = ""

# Only show jobs posted within this many days. 0 = any time. Indeed's own filter
# presets are roughly 1, 3, 7, and 14 days.
days_posted = 7                    # A whole number >= 0

# Search radius in miles from search_location. Ignored if search_location is "".
radius = 25

# Only consider jobs Indeed can apply to without leaving Indeed ("Easily apply").
# Jobs that redirect to an external site are skipped, same as the LinkedIn bot.
easy_apply_only = True             # True or False, Note: True or False are case-sensitive

# Filter by job type, comma-separated. Valid values (must match Indeed's own
# wording): "Full-time", "Part-time", "Contract", "Temporary", "Internship".
# Leave empty to not filter.
job_type = []                      # (multiple select)

# Filter by work setting, comma-separated. Valid values: "Remote", "Hybrid",
# "On-site". Leave empty to not filter. Note: Indeed doesn't expose Hybrid/
# On-site as separate search filters the way LinkedIn does - this is applied as
# a best-effort keyword check against each listing instead of a real filter.
on_site = []                       # (multiple select)


## >>>>>>>>>>> SKIP IRRELEVANT JOBS <<<<<<<<<<<

# Skip a job if its title or description contains any of these words or
# phrases. Case-insensitive. Leave empty as [] to not filter.
bad_words = []

# Skip jobs from these companies entirely. Case-insensitive, must match the
# company name Indeed shows. Leave empty as [] to not filter.
blacklisted_companies = []

# Avoid applying to jobs if their required experience is above your
# current_experience (shared with the LinkedIn bot, see config/search.py).
# Set current_experience to -1 there to ignore this and apply to everything.


## >>>>>>>>>>> RUN BEHAVIOR <<<<<<<<<<<

# Stop after this many applications in one run. 0 = no limit.
max_applications_per_run = 0       # A whole number >= 0

# Once every search term has been used, start over from the first one?
run_non_stop = False               # True or False, Note: True or False are case-sensitive

# Should the tool pause before every submit application to let you check the
# information? Forced to False automatically if run_in_background (see
# config/settings.py) is True.
pause_before_submit = True         # True or False, Note: True or False are case-sensitive

# Should the tool pause if it needs help answering a question? If False, will
# answer randomly instead. Forced to False automatically if run_in_background
# is True.
pause_at_failed_question = True    # True or False, Note: True or False are case-sensitive

# Do you want to overwrite previously-saved answers on Indeed's own application
# form (name, phone, etc. it remembers from your Indeed profile)?
overwrite_previous_answers = False # True or False, Note: True or False are case-sensitive

##


## >>>>>>>>>>> WHERE RESULTS ARE SAVED <<<<<<<<<<<
# Kept separate from the LinkedIn bot's history files so the two never collide.

file_name = "all excels/indeed_applied_applications_history.csv"
failed_file_name = "all excels/indeed_failed_applications_history.csv"
logs_folder_path = "logs/indeed/"

##


############################################################################################################
'''
THANK YOU for using my tool 😊! Wishing you the best in your job hunt 🙌🏻!

Sharing is caring! If you found this tool helpful, please share it with your peers 🥺. Your support keeps this project alive.

Support my work on <PATREON_LINK>. Together, we can help more job seekers.

As an independent developer, I pour my heart and soul into creating tools like this, driven by the genuine desire to make a positive impact.

Your support, whether through donations big or small or simply spreading the word, means the world to me and helps keep this project alive and thriving.

Gratefully yours 🙏🏻,
Sai Vignesh Golla
'''

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################
