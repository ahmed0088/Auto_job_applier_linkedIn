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

from modules.helpers import get_default_temp_profile, make_directories
from config.settings import run_in_background, auto_manage_driver, disable_extensions, safe_mode, file_name, failed_file_name, logs_folder_path, generated_resume_path
from config.questions import default_resume_path
if auto_manage_driver:
    import os, re, sys, subprocess
    import undetected_chromedriver as uc
else:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    # from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from modules.helpers import find_default_profile_directory, critical_error_log, print_lg
from selenium.common.exceptions import SessionNotCreatedException

def find_google_chrome_path() -> str | None:
    '''
    Finds the actual Google Chrome executable, preferring it over any other
    Chromium-based browser on the system. uc.find_chrome_executable() collects
    candidates in a Python set, whose iteration order is randomized per
    process, so a stray/incompatible Chromium build installed elsewhere can
    get picked instead of Chrome on some runs and not others.
    '''
    if sys.platform == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_path):
            return mac_path
    return uc.find_chrome_executable()

def get_installed_chrome_major_version(chrome_path: str) -> int | None:
    '''
    Returns the major version of the given Chrome executable, or None if it
    can't be determined. Used so the auto-managed driver downloads a
    chromedriver matching the browser actually installed, instead of just the
    latest one (which breaks as soon as Chrome falls a version behind).
    '''
    try:
        output = subprocess.check_output([chrome_path, "--version"], text=True)
        match = re.search(r"(\d+)\.", output)
        return int(match.group(1)) if match else None
    except Exception:
        return None

def createChromeSession(isRetry: bool = False):
    make_directories([file_name,failed_file_name,logs_folder_path+"/screenshots",default_resume_path,generated_resume_path+"/temp"])
    # Set up WebDriver with Chrome Profile
    options = uc.ChromeOptions() if auto_manage_driver else Options()
    if run_in_background:   options.add_argument("--headless")
    if disable_extensions:  options.add_argument("--disable-extensions")

    print_lg("IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM! Or it's highly likely that application will just open browser and not do anything!")
    profile_dir = find_default_profile_directory()
    if isRetry:
        print_lg("Will login with a guest profile, browsing history will not be saved in the browser!")
    elif profile_dir and not safe_mode:
        options.add_argument(f"--user-data-dir={profile_dir}")
    else:
        print_lg("Logging in with a guest profile, Web history will not be saved!")
        options.add_argument(f"--user-data-dir={get_default_temp_profile()}")
    if auto_manage_driver:
        # try: 
        #     driver = uc.Chrome(driver_executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe", options=options)
        # except (FileNotFoundError, PermissionError) as e: 
        #     print_lg("(auto-managed driver) Got '{}' when using pre-installed ChromeDriver.".format(type(e).__name__))
            print_lg("Downloading the matching Chrome driver... This may take some time (this happens each run when auto_manage_driver is enabled).")
            chrome_path = find_google_chrome_path()
            driver = uc.Chrome(options=options, browser_executable_path=chrome_path, version_main=get_installed_chrome_major_version(chrome_path))
    else: driver = webdriver.Chrome(options=options) #, service=Service(executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe"))
    driver.maximize_window()
    wait = WebDriverWait(driver, 5)
    actions = ActionChains(driver)
    return options, driver, actions, wait

try:
    options, driver, actions, wait = None, None, None, None
    options, driver, actions, wait = createChromeSession()
except SessionNotCreatedException as e:
    critical_error_log("Failed to create Chrome Session, retrying with guest profile", e)
    options, driver, actions, wait = createChromeSession(True)
except Exception as e:
    msg = 'Seems like Google Chrome is out dated. Update browser and try again! \n\n\nIf issue persists, try Safe Mode. Set, safe_mode = True in config.py \n\nPlease check GitHub discussions/support for solutions https://github.com/GodsScion/Auto_job_applier_linkedIn \n                                   OR \nReach out in discord ( https://discord.gg/fFp7uUzWCY )'
    if isinstance(e,TimeoutError): msg = "Couldn't download Chrome-driver. Set auto_manage_driver = False in config!"
    print_lg(msg)
    critical_error_log("In Opening Chrome", e)
    try:
        from pyautogui import alert
        alert(msg, "Error in opening chrome")
    except Exception:
        pass
    try: driver.quit()
    except NameError: exit()
    
