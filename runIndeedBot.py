'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08

------------------------------------------------------------------------------
FIRST VERSION of Indeed support. Unlike runAiBot.py (the LinkedIn bot, which
has been debugged against many real runs), this has not yet been run against a
live Indeed account - it was written without the ability to browse Indeed.com
directly to verify selectors. Expect rough edges. If something breaks, paste
the console output (and, if you can, a screenshot of where it stopped) back so
the actual page structure can be fixed against - the same way every LinkedIn
bug this session got fixed from real log output.

Shares your profile answers (name, resume, salary expectations, etc.) and AI
settings with the LinkedIn bot - see config/questions.py, config/personals.py,
and config/secrets.py. Indeed-only settings (search terms, filters, run
behavior) live in config/indeed.py.
------------------------------------------------------------------------------
'''

# Imports
import os
import csv
import pyautogui
from random import randint
from datetime import datetime
from urllib.parse import urlencode

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, NoSuchFrameException, WebDriverException, TimeoutException

from config.personals import *
from config.questions import *
from config.indeed import (
    search_terms, search_location, days_posted, radius, easy_apply_only, job_type, on_site,
    bad_words as indeed_bad_words, blacklisted_companies, max_applications_per_run, run_non_stop,
    pause_before_submit, pause_at_failed_question, overwrite_previous_answers,
    file_name, failed_file_name, logs_folder_path,
)
from config.secrets import use_AI
import config.secrets as _secrets_module
from config.settings import (
    click_gap, min_application_gap, max_application_gap, run_in_background, keep_screen_awake,
    max_applications_per_day as global_max_applications_per_day, restrict_active_hours,
    active_hours_start, active_hours_end, extended_break_every, extended_break_min, extended_break_max,
)

from modules.open_chrome import *  # gives us `driver`, `actions`, `wait`, `options`
from modules.helpers import *
from modules.clickers_and_finders import try_xp, try_linkText, try_find_by_classes

if use_AI:
    from modules.ai.connections import create_ai_client, answer_question, close_ai_client
    from modules.resumes.extractor import extract_resume_text

# Indeed login isn't necessarily configured the first time someone tries this - same
# "not configured yet" sentinel pattern used for the LinkedIn login in runAiBot.py.
indeed_username = getattr(_secrets_module, "indeed_username", "indeed_username@example.com")
indeed_password = getattr(_secrets_module, "indeed_password", "example_password")

if run_in_background == True:
    pause_at_failed_question = False
    pause_before_submit = False
    run_non_stop = False

make_directories([file_name, failed_file_name, logs_folder_path + "/screenshots"])

first_name = first_name.strip()
middle_name = middle_name.strip()
last_name = last_name.strip()
full_name = first_name + " " + middle_name + " " + last_name if middle_name else first_name + " " + last_name

aiClient = None
easy_applied_count = 0
failed_count = 0
skip_count = 0
randomly_answered_questions = set()


#< Login functions
def is_logged_in_indeed() -> bool:
    '''
    Function to check if user is logged-in on Indeed.
    * Returns `True` if logged-in, `False` otherwise.

    Mirrors the exact fix made for the LinkedIn bot's login-check race
    condition: if the browser is still sitting on Indeed's own login/auth
    domain, that's treated as definitely NOT logged in, regardless of whether
    any specific element check below found (or missed, due to a page layout
    this hasn't been tested against) a login form.
    '''
    try:
        WebDriverWait(driver, 15).until(lambda d: "secure.indeed.com" not in d.current_url
                   or try_xp(d, '//input[@type="email"]', False)
                   or try_xp(d, '//input[@type="password"]', False))
    except WebDriverException:
        pass
    if "secure.indeed.com" in driver.current_url:
        print_lg(f"Still on Indeed's login page, so assuming user is NOT logged in! Current URL: {driver.current_url}")
        return False
    if try_xp(driver, '//input[@type="email"]', False): return False
    if try_xp(driver, '//input[@type="password"]', False): return False
    if try_linkText(driver, "Sign in"): return False
    print_lg(f"Didn't find a login form, so assuming user is logged in! Current URL: {driver.current_url}, Page title: {driver.title!r}")
    return True


def login_indeed() -> None:
    '''
    Function to log in to Indeed.
    * Tries `indeed_username`/`indeed_password` from `secrets.py`.
    * If that's not configured, or fails, asks the user to log in manually.

    Indeed's login is historically a two-step flow (email first, then
    password on a second screen) rather than one combined form like
    LinkedIn's - this tries that two-step flow, but falls back to treating
    both fields as present on one screen if the password field is already
    there right after the email is filled in.
    '''
    driver.get("https://secure.indeed.com/auth")
    if indeed_username == "indeed_username@example.com" and indeed_password == "example_password":
        safe_alert("User did not configure indeed_username and indeed_password in secrets.py, hence can't login automatically! Please login manually!", "Login Manually", "Okay")
        print_lg("User did not configure indeed_username and indeed_password in secrets.py, hence can't login automatically! Please login manually!")
        manual_login_retry(is_logged_in_indeed, 2)
        return
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="email"]')))
        try:
            email_field = driver.find_element(By.XPATH, '//input[@type="email"]')
            email_field.send_keys(Keys.CONTROL + "a")
            human_type(email_field, indeed_username)
        except Exception as e:
            print_lg("Couldn't find email field.", e)

        # Password field may already be on the same screen, or need a "Continue" click first.
        if not try_xp(driver, '//input[@type="password"]', False):
            try_xp(driver, '//button[@type="submit"]')
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="password"]')))
            except TimeoutException:
                pass

        try:
            password_field = driver.find_element(By.XPATH, '//input[@type="password"]')
            password_field.send_keys(Keys.CONTROL + "a")
            human_type(password_field, indeed_password)
            driver.find_element(By.XPATH, '//button[@type="submit"]').click()
        except Exception as e:
            print_lg("Couldn't find password field or submit button.", e)
    except Exception as e1:
        print_lg("Couldn't Login!", e1)

    try:
        wait.until(lambda d: "secure.indeed.com" not in d.current_url)
        print_lg("Login successful!")
    except Exception:
        print_lg("Seems like login attempt failed! Possibly due to wrong credentials, a captcha, or 2FA! Try logging in manually!")
        manual_login_retry(is_logged_in_indeed, 2)
#>


#< History tracking (kept in Indeed's own CSVs - see config/indeed.py)
def get_applied_job_keys() -> set:
    job_keys = set()
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                if row: job_keys.add(row[0])
    except FileNotFoundError:
        print_lg(f"The CSV file '{file_name}' does not exist.")
    return job_keys


def get_applications_today_count() -> int:
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row.get('Date Applied', '').startswith(today_str):
                    count += 1
    except FileNotFoundError:
        pass
    return count


def submitted_jobs(job_key: str, title: str, company: str, job_link: str) -> None:
    try:
        with open(file_name, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['Job Key', 'Title', 'Company', 'Job Link', 'Date Applied']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0: writer.writeheader()
            writer.writerow({'Job Key': job_key, 'Title': title, 'Company': company, 'Job Link': job_link, 'Date Applied': datetime.now()})
    except Exception as e:
        print_lg("Failed to update submitted jobs list! Probably the file is open elsewhere, permission denied, or missing.", e)


def failed_job(job_key: str, title: str, company: str, job_link: str, reason: str, exception: Exception = None, screenshot_name: str = "Not Available") -> None:
    try:
        with open(failed_file_name, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['Job Key', 'Title', 'Company', 'Job Link', 'Date Tried', 'Assumed Reason', 'Stack Trace', 'Screenshot Name']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if file.tell() == 0: writer.writeheader()
            writer.writerow({'Job Key': job_key, 'Title': title, 'Company': company, 'Job Link': job_link,
                              'Date Tried': datetime.now(), 'Assumed Reason': reason, 'Stack Trace': exception,
                              'Screenshot Name': screenshot_name})
    except Exception as e:
        print_lg("Failed to update failed jobs list! Probably the file is open elsewhere, permission denied, or missing.", e)


def screenshot(job_key: str, failedAt: str) -> str:
    screenshot_name = "{} - {} - {}.png".format(job_key, failedAt, str(datetime.now())).replace(":", "-")
    try:
        driver.save_screenshot((logs_folder_path + "/screenshots/" + screenshot_name).replace("//", "/"))
    except Exception as e:
        print_lg("Failed to take screenshot!", e)
    return screenshot_name
#>


#< Search
def build_search_url(term: str) -> str:
    '''
    Builds an Indeed search results URL directly from query params, rather
    than clicking through search-box UI (which is what actually broke for the
    LinkedIn "Past month" filter this session) - a much more stable approach
    since Indeed has historically supported linkable, bookmarkable search URLs
    for SEO. `fromage`/`radius`/`sort` are Indeed's real, long-standing query
    param names as of this bot's last known-good reference; if Indeed has
    since renamed them, this filter step just silently won't narrow results -
    it won't break the run, since job-level filtering (bad words, blacklist,
    easy_apply_only) still applies per listing regardless.
    '''
    params = {"q": term}
    if search_location.strip():
        params["l"] = search_location.strip()
        params["radius"] = radius
    if days_posted and days_posted > 0:
        params["fromage"] = days_posted
    params["sort"] = "date"
    return "https://www.indeed.com/jobs?" + urlencode(params)


def get_job_cards() -> list:
    '''Returns every job-result element on the current search page, found via
    Indeed's long-standing `data-jk` (job key) attribute - present on the
    clickable job title link within each result card.'''
    try:
        return driver.find_elements(By.XPATH, '//a[@data-jk]')
    except Exception:
        return []
#>


#< Answering application questions
def answer_common_questions(label: str, answer: str) -> str:
    if 'sponsorship' in label or 'visa' in label: answer = require_visa
    if 'citizenship' in label or 'employment eligibility' in label: answer = us_citizenship
    return answer


def answer_text_like(label_org: str, job_description: str) -> str:
    '''Same keyword-first, AI-fallback, random-last priority the LinkedIn bot
    uses for free-text questions - see runAiBot.py's text-question branch.'''
    label = label_org.lower()
    answer = ""
    if 'experience' in label or 'years' in label: answer = years_of_experience
    elif 'phone' in label or 'mobile' in label: answer = phone_number
    elif 'street' in label: answer = street
    elif 'city' in label or 'location' in label: answer = current_city
    elif 'signature' in label: answer = full_name
    elif 'name' in label:
        if 'full' in label: answer = full_name
        elif 'first' in label and 'last' not in label: answer = first_name
        elif 'last' in label and 'first' not in label: answer = last_name
        elif 'employer' in label: answer = recent_employer
        else: answer = full_name
    elif 'notice' in label: answer = str(notice_period)
    elif 'salary' in label or 'compensation' in label or 'ctc' in label or 'pay' in label:
        answer = str(desired_salary)
    elif 'linkedin' in label: answer = linkedIn
    elif 'website' in label or 'portfolio' in label or 'link' in label: answer = website
    else: answer = answer_common_questions(label, answer)

    if answer == "" and use_AI and aiClient:
        try:
            ai_answer = answer_question(aiClient, label_org, question_type="text", job_description=job_description, user_information_all=user_information_all)
            if ai_answer:
                print_lg(f'AI answered "{label_org}": "{ai_answer}"')
                return ai_answer.strip()
        except Exception as e:
            print_lg("Failed to get AI answer!", e)
    if answer == "":
        randomly_answered_questions.add((label_org, "text"))
        answer = years_of_experience
    return answer


def answer_indeed_form(container, job_description: str = None) -> None:
    '''
    Answers whatever form fields are visible in `container` (the Indeed Apply
    step currently on screen). Indeed's own apply flow shows one section of
    questions per screen (contact info, resume, then employer-defined
    screening questions), so this is called once per screen rather than
    trying to find every question up front like the LinkedIn bot does inside
    one big modal.
    '''
    # Plain text/number inputs
    for text_input_el in container.find_elements(By.XPATH, './/input[@type="text" or @type="tel" or @type="number" or @type="email"]'):
        try:
            if text_input_el.get_attribute("value") and not overwrite_previous_answers:
                continue
            label = ""
            input_id = text_input_el.get_attribute("id")
            if input_id:
                label_el = try_xp(container, f'.//label[@for="{input_id}"]', False)
                if label_el: label = label_el.text
            if not label:
                label = text_input_el.get_attribute("aria-label") or text_input_el.get_attribute("placeholder") or "Unknown"
            answer = answer_text_like(label, job_description)
            text_input_el.clear()
            human_type(text_input_el, str(answer))
        except Exception as e:
            print_lg("Failed to answer a text field.", e)

    # Textareas (e.g. "why are you a good fit")
    for textarea_el in container.find_elements(By.XPATH, './/textarea'):
        try:
            if textarea_el.get_attribute("value") and not overwrite_previous_answers:
                continue
            input_id = textarea_el.get_attribute("id")
            label = ""
            if input_id:
                label_el = try_xp(container, f'.//label[@for="{input_id}"]', False)
                if label_el: label = label_el.text
            if not label:
                label = textarea_el.get_attribute("aria-label") or "Unknown"
            answer = answer_text_like(label, job_description)
            textarea_el.clear()
            human_type(textarea_el, str(answer))
        except Exception as e:
            print_lg("Failed to answer a textarea.", e)

    # Dropdowns
    for select_el in container.find_elements(By.XPATH, './/select'):
        try:
            select = Select(select_el)
            current = select.first_selected_option.text
            if current and current != "Select an option" and not overwrite_previous_answers:
                continue
            input_id = select_el.get_attribute("id")
            label = ""
            if input_id:
                label_el = try_xp(container, f'.//label[@for="{input_id}"]', False)
                if label_el: label = label_el.text
            options_text = [o.text for o in select.options if o.text.strip()]
            answer = answer_common_questions(label.lower(), "")
            picked = False
            if answer:
                for opt in options_text:
                    if answer.lower() in opt.lower():
                        select.select_by_visible_text(opt)
                        picked = True
                        break
            if not picked and use_AI and aiClient:
                try:
                    ai_answer = answer_question(aiClient, label or "Unknown", options=options_text, question_type="single_select", job_description=job_description, user_information_all=user_information_all)
                    match = next((o for o in options_text if o.lower() == (ai_answer or "").strip().lower()), None)
                    if match:
                        select.select_by_visible_text(match)
                        picked = True
                        print_lg(f'AI answered "{label}": "{match}"')
                except Exception as e:
                    print_lg("Failed to get AI answer!", e)
            if not picked and len(select.options) > 1:
                select.select_by_index(randint(1, len(select.options) - 1))
                randomly_answered_questions.add((label, "select"))
        except Exception as e:
            print_lg("Failed to answer a dropdown.", e)

    # Radio-button groups - group by `name` attribute, since Indeed's radio
    # inputs in one question share a name the way HTML radio groups always do.
    seen_radio_groups = set()
    for radio_el in container.find_elements(By.XPATH, './/input[@type="radio"]'):
        try:
            name = radio_el.get_attribute("name")
            if not name or name in seen_radio_groups:
                continue
            seen_radio_groups.add(name)
            group = container.find_elements(By.XPATH, f'.//input[@type="radio" and @name="{name}"]')
            already_selected = any(g.is_selected() for g in group)
            if already_selected and not overwrite_previous_answers:
                continue
            fieldset = try_xp(radio_el, './ancestor::fieldset', False)
            label = ""
            if fieldset:
                legend = try_xp(fieldset, './/legend', False)
                if legend: label = legend.text
            option_labels = []
            for opt in group:
                opt_id = opt.get_attribute("id")
                opt_label_el = try_xp(container, f'.//label[@for="{opt_id}"]', False) if opt_id else False
                option_labels.append(opt_label_el.text if opt_label_el else "Unknown")
            answer = answer_common_questions(label.lower(), "")
            picked_index = None
            if answer:
                for i, opt_label in enumerate(option_labels):
                    if answer.lower() in opt_label.lower():
                        picked_index = i
                        break
            if picked_index is None and use_AI and aiClient:
                try:
                    ai_answer = answer_question(aiClient, label or "Unknown", options=option_labels, question_type="single_select", job_description=job_description, user_information_all=user_information_all)
                    for i, opt_label in enumerate(option_labels):
                        if opt_label.lower() == (ai_answer or "").strip().lower():
                            picked_index = i
                            print_lg(f'AI answered "{label}": "{opt_label}"')
                            break
                except Exception as e:
                    print_lg("Failed to get AI answer!", e)
            if picked_index is None:
                picked_index = 0
                randomly_answered_questions.add((label, "radio"))
            group[picked_index].click()
        except Exception as e:
            print_lg("Failed to answer a radio group.", e)
#>


def switch_to_apply_iframe() -> bool:
    '''
    Indeed's own quick-apply flow ("Indeed Apply") has historically run inside
    an iframe rather than directly in the page - unlike LinkedIn's Easy Apply
    modal, which is plain page DOM. Tries a couple of plausible iframe
    identifiers; if none are found, assumes the apply UI is directly in the
    page (in case Indeed has since changed this) and continues without
    switching context.
    '''
    driver.switch_to.default_content()
    for locator in [(By.ID, "indeedapply-modal-iframe"), (By.XPATH, '//iframe[contains(@id, "indeedapply")]'), (By.XPATH, '//iframe[contains(@title, "Apply")]')]:
        try:
            frame = WebDriverWait(driver, 5).until(EC.presence_of_element_located(locator))
            driver.switch_to.frame(frame)
            return True
        except (TimeoutException, NoSuchElementException, NoSuchFrameException):
            continue
    return False


def apply_to_job(job_link: str, job_key: str, title: str, company: str, job_description: str) -> bool:
    '''
    Runs the "Indeed Apply" flow for one job. Returns True if submitted.
    Mirrors the LinkedIn bot's Easy Apply loop: repeatedly answer whatever's
    on screen, click Continue/Next, stop after too many attempts (probably
    stuck on a question this can't answer), and click Submit at the end.
    '''
    in_iframe = switch_to_apply_iframe()
    print_lg(f"Indeed Apply UI found {'inside an iframe' if in_iframe else 'directly on the page (no matching iframe found)'}.")
    try:
        step = 0
        submitted = False
        while step < 15:
            step += 1
            container = driver.find_element(By.TAG_NAME, "body")
            answer_indeed_form(container, job_description)

            submit_btn = try_xp(driver, '//button[contains(@aria-label, "Submit") or contains(., "Submit your application")]', False)
            if submit_btn:
                if pause_before_submit and step != 0:
                    decision = safe_confirm(
                        '1. Please verify your information.\n2. If you edited something, please return to this final screen.\n3. DO NOT CLICK "Submit your application".\n\nYou can turn off "Pause before submit" in config/indeed.py ("Disable Pause" skips it for THIS application only).',
                        "Confirm your information", ["Disable Pause", "Discard Application", "Submit Application"])
                    if decision == "Discard Application":
                        return False
                submit_btn.click()
                buffer(click_gap)
                submitted = True
                break

            continue_btn = try_xp(driver, '//button[contains(@aria-label, "Continue") or contains(., "Continue")]', False)
            if not continue_btn:
                continue_btn = try_xp(driver, '//button[@type="submit"]', False)
            if not continue_btn:
                print_lg("Couldn't find a Continue or Submit button - stopping this application.")
                break
            try:
                continue_btn.click()
                buffer(click_gap)
            except Exception as e:
                print_lg("Failed to click Continue.", e)
                break
        else:
            if pause_at_failed_question:
                safe_alert("Couldn't get through the Indeed application form automatically.\nPlease finish it manually, then click Continue.", "Help Needed", "Continue")
            if randomly_answered_questions:
                print_lg("Stuck for one or some of the following questions...", randomly_answered_questions)

        return submitted
    finally:
        driver.switch_to.default_content()


def run_search_term(term: str) -> None:
    global easy_applied_count, failed_count, skip_count
    applied_ids = get_applied_job_keys()
    search_url = build_search_url(term)
    print_lg(f'\n>>>> Now searching Indeed for "{term}" <<<<\n')
    driver.get(search_url)
    buffer(click_gap)

    cards = get_job_cards()
    print_lg(f"Found {len(cards)} job(s) on this results page.")

    for card in cards:
        if max_applications_per_run and easy_applied_count >= max_applications_per_run:
            print_lg(f"Reached max_applications_per_run ({max_applications_per_run}). Stopping this search term.")
            return
        if global_max_applications_per_day and get_applications_today_count() >= global_max_applications_per_day:
            print_lg(f"Reached max_applications_per_day ({global_max_applications_per_day}). Stopping.")
            return
        if restrict_active_hours:
            hour = datetime.now().hour
            if not (active_hours_start <= hour < active_hours_end):
                print_lg(f"Outside active hours ({active_hours_start}:00-{active_hours_end}:00). Stopping.")
                return

        if keep_screen_awake: pyautogui.press('shiftright')

        job_key = card.get_attribute("data-jk")
        if not job_key or job_key in applied_ids:
            continue

        job_link = f"https://www.indeed.com/viewjob?jk={job_key}"
        title = card.text.strip() or "Unknown"
        company = "Unknown"

        try:
            card.click()
            buffer(click_gap)
        except Exception as e:
            print_lg(f'Failed to open job "{title}".', e)
            continue

        try:
            description_el = try_find_by_classes(driver, ["jobsearch-jobDescriptionText", "jobsearch-JobComponent-description"])
            job_description = description_el.text
        except Exception:
            job_description = None

        lowered_desc = (job_description or "").lower()
        lowered_title = title.lower()
        if any(word.lower() in lowered_title or word.lower() in lowered_desc for word in indeed_bad_words):
            print_lg(f'Skipping "{title}" - matched a bad word.')
            skip_count += 1
            continue
        if company in blacklisted_companies:
            print_lg(f'Skipping "{title}" - company "{company}" is blacklisted.')
            skip_count += 1
            continue
        # Indeed doesn't expose job_type/on_site as URL-filterable the way LinkedIn does
        # (or at least not reliably enough to depend on), so these are applied as a
        # best-effort keyword check against the title/description instead of a real filter.
        if job_type and not any(jt.lower() in lowered_title or jt.lower() in lowered_desc for jt in job_type):
            print_lg(f'Skipping "{title}" - none of job_type {job_type} matched.')
            skip_count += 1
            continue
        if on_site and not any(setting.lower() in lowered_title or setting.lower() in lowered_desc for setting in on_site):
            print_lg(f'Skipping "{title}" - none of on_site {on_site} matched.')
            skip_count += 1
            continue

        apply_btn = try_xp(driver, '//button[contains(., "Apply now") or contains(@aria-label, "Apply now")]', False)
        if not apply_btn:
            if easy_apply_only:
                print_lg(f'Skipping "{title}" - no "Apply now" (Indeed Apply) button found; probably an external application.')
                skip_count += 1
                continue

        try:
            apply_btn.click()
            buffer(click_gap)
        except Exception as e:
            print_lg(f'Failed to click Apply now for "{title}".', e)
            failed_job(job_key, title, company, job_link, "Couldn't click Apply now", e)
            failed_count += 1
            continue

        try:
            submitted = apply_to_job(job_link, job_key, title, company, job_description)
        except Exception as e:
            screenshot_name = screenshot(job_key, "Applying")
            print_lg(f'Something went wrong applying to "{title}".', e)
            failed_job(job_key, title, company, job_link, "Unhandled error during apply", e, screenshot_name)
            failed_count += 1
            driver.switch_to.default_content()
            continue

        if submitted:
            print_lg(f'Successfully applied to "{title}" at "{company}".')
            submitted_jobs(job_key, title, company, job_link)
            easy_applied_count += 1
            buffer(randint(min_application_gap, max_application_gap))
            if extended_break_every and easy_applied_count % extended_break_every == 0:
                pause = randint(extended_break_min, extended_break_max)
                print_lg(f"Taking an extended break of {pause}s to keep a human-like pace...")
                buffer(pause)
        else:
            print_lg(f'Could not finish applying to "{title}".')
            failed_job(job_key, title, company, job_link, "Didn't reach a Submit button", None)
            failed_count += 1


def run() -> None:
    for term in search_terms:
        run_search_term(term)
    print_lg("\n\nSummary:")
    print_lg(f"Jobs Easy Applied: {easy_applied_count}")
    print_lg(f"Failed jobs: {failed_count}")
    print_lg(f"Irrelevant jobs skipped: {skip_count}")


def main() -> None:
    global aiClient, user_information_all
    print_lg("Please consider sponsoring this project at: https://github.com/sponsors/GodsScion")
    try:
        driver.get("https://www.indeed.com/")
        if not is_logged_in_indeed():
            login_indeed()

        if use_AI:
            aiClient = create_ai_client()
            resume_text = ""
            try:
                resume_text = extract_resume_text(default_resume_path if os.path.isabs(default_resume_path) else os.path.join(os.path.dirname(os.path.abspath(__file__)), default_resume_path))
            except Exception as e:
                print_lg("Failed to read resume for AI context.", e)
            if resume_text:
                user_information_all = (user_information_all + "\n\nResume:\n" + resume_text) if user_information_all.strip() else resume_text
                print_lg(f"Loaded your resume ({len(resume_text)} characters) to use as AI context.")

        run()
        while run_non_stop:
            run()

    except (NoSuchWindowException, WebDriverException) as e:
        print_lg("The browser window was closed or the session became invalid. Exiting.", e)
    except Exception as e:
        critical_error_log("In Indeed Applier Main", e)
    finally:
        if use_AI and aiClient:
            try:
                close_ai_client(aiClient)
                print_lg("Closed AI client.")
            except Exception:
                pass
        print_lg("Closing the browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
