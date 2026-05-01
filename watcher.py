import os
import sys
import json
import logging
import platform
import requests
import time

from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.keys import Keys

from chromedriver_manager import ensure_chromedriver

# ---------------------------------------------------------------------------
# Bootstrap — load .env from /data (Docker) or script dir (local/Windows)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IS_DOCKER = os.getenv("DOCKER", "false").strip().lower() == "true"
IS_WINDOWS = platform.system() == "Windows"

_env_path = "/data/.env" if IS_DOCKER else os.path.join(SCRIPT_DIR, ".env")
load_dotenv(_env_path)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TARGET_URL = os.getenv("TARGET_URL", "https://ikwilhuren.nu/")
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "30"))
ELEMENT_WAIT_TIMEOUT = int(os.getenv("ELEMENT_WAIT_TIMEOUT", "15"))
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"
CHROME_BINARY = os.getenv("CHROME_BINARY", "")  # empty = auto-detect

# Paths — Docker uses /data for all persistent files; local uses script dir
_data_dir = "/data" if IS_DOCKER else SCRIPT_DIR
STATE_FILE = os.getenv("STATE_FILE", os.path.join(_data_dir, "last_listing.txt"))
LOG_FILE = os.getenv("LOG_FILE", os.path.join(_data_dir, "watcher.log"))
CHROMEDRIVER_PATH = os.getenv(
    "CHROMEDRIVER_PATH",
    (
        "/usr/bin/chromedriver"
        if IS_DOCKER
        else os.path.join(
            SCRIPT_DIR, "chromedriver.exe" if IS_WINDOWS else "chromedriver"
        )
    ),
)

# ---------------------------------------------------------------------------
# Logging
# — File handler: CRITICAL only  (keeps log tiny on the 25 GB server)
# — Stdout handler: INFO         (visible via `docker logs` and cron output)
# ---------------------------------------------------------------------------
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

_file_handler = logging.FileHandler(LOG_FILE)
_file_handler.setLevel(logging.CRITICAL)

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_file_handler, _stdout_handler],
)
logger = logging.getLogger(__name__)

# Silence noisy third-party loggers
logging.getLogger("selenium").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Chrome binary auto-detect
# ---------------------------------------------------------------------------
def _detect_chrome_binary() -> str:
    if IS_DOCKER:
        # selenium/standalone-chrome ships Chrome at this path
        return "/usr/bin/google-chrome"

    if IS_WINDOWS:
        candidates = [
            os.path.join(
                os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                "Google\\Chrome\\Application\\chrome.exe",
            ),
            os.path.join(
                os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
                "Google\\Chrome\\Application\\chrome.exe",
            ),
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Google\\Chrome\\Application\\chrome.exe",
            ),
        ]
    else:
        candidates = [
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ]

    for path in candidates:
        if path and os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Could not auto-detect Chrome/Chromium binary. "
        "Set CHROME_BINARY in your .env file."
    )


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.critical("Telegram credentials not configured.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram notification sent.")
    except Exception as e:
        logger.critical(f"Failed to send Telegram message: {e}")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(states: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)

    # 1. Sort and slice the items first
    # 2. Convert back to a dict
    # 3. Assign it to a variable (or overwrite 'state')
    sorted_items = sorted(
        states.items(), key=lambda item: item[1]["date"], reverse=True
    )
    top_10_state = dict(sorted_items[:10])

    with open(STATE_FILE, "w") as f:
        json.dump(top_10_state, f, indent=2)


# ---------------------------------------------------------------------------
# Chrome driver
# ---------------------------------------------------------------------------
def build_driver() -> webdriver.Chrome:
    chrome_binary = CHROME_BINARY or _detect_chrome_binary()
    logger.info(f"Chrome: {chrome_binary} | headless={HEADLESS} | docker={IS_DOCKER}")

    options = Options()
    options.binary_location = chrome_binary

    if HEADLESS:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")

    if not IS_WINDOWS:
        options.add_argument("--single-process")
        options.add_argument("--memory-pressure-off")
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    service = Service(executable_path=CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


# ---------------------------------------------------------------------------
# Scraper — helper functions
# ---------------------------------------------------------------------------
def _press_tabs(driver: webdriver.Chrome, count: int) -> None:
    """Send TAB key count times"""
    for _ in range(count):
        driver.switch_to.active_element.send_keys(Keys.TAB)


def _press_arrows_enter_tab(
    driver: webdriver.Chrome, count: int, final_tab: bool = True
) -> None:
    """Send ARROW_DOWN count times, then ENTER, optionally TAB"""
    for _ in range(count):
        driver.switch_to.active_element.send_keys(Keys.ARROW_DOWN)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    if final_tab:
        driver.switch_to.active_element.send_keys(Keys.TAB)


def _search_location(driver: webdriver.Chrome) -> None:
    """Navigate to location field and enter Utrecht search"""
    _press_tabs(driver, 11)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    driver.switch_to.active_element.send_keys("Utrecht, Utrecht, Utrecht")
    time.sleep(3)
    driver.switch_to.active_element.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
    _press_tabs(driver, 2)
    driver.switch_to.active_element.click()


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
def scrape_listings(driver: webdriver.Chrome) -> list[dict]:
    """
    Loads TARGET_URL, waits for listing cards, returns list of dicts sorted
    newest-first: {id, title, price, date, url}

    NOTE: CSS selectors below are best-effort — tune them on Windows with
    HEADLESS=false until the real DOM structure is confirmed.
    """
    logger.info(f"Loading {TARGET_URL}")
    driver.get(TARGET_URL)

    wait = WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT)
    CARD_SELECTOR = (
        "div.property-item, div.listing-item, article.property, "
        "div[class*='woning'], div[class*='listing']"
    )

    # Search for location (twice)
    _search_location(driver)
    _search_location(driver)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR)))

    # Navigate to filter section
    _press_tabs(driver, 17)
    driver.switch_to.active_element.send_keys(Keys.ENTER)

    # Select filters
    _press_arrows_enter_tab(driver, 7)  # From Price
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 10)  # To Price
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 2)  # From Living Space
    _press_tabs(driver, 1)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 2, final_tab=False)  # Property Type
    _press_tabs(driver, 1)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 2, final_tab=False)  # Apartment Type
    _press_tabs(driver, 1)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 2, final_tab=False)  # Bedrooms

    # Apply filters and wait
    _press_tabs(driver, 4)
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    time.sleep(4)

    # Set sort to newest
    _press_tabs(driver, 25)
    time.sleep(3)
    _press_tabs(driver, 2)
    time.sleep(3)

    if "/aanbod/?page=" in driver.switch_to.active_element.get_attribute("href"):
        raise Exception(
            "Unexpected pagination link focused — selectors likely need updating."
        )

    driver.switch_to.active_element.send_keys(Keys.ENTER, Keys.ARROW_DOWN, Keys.ENTER)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR)))

    try:
        wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, CARD_SELECTOR))
        )
    except TimeoutException:
        logger.critical(
            f"Timed out waiting for listing cards. Page snippet:\n{driver.page_source[:3000]}"
        )
        return []

    cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
    logger.info(f"Found {len(cards)} listing cards.")

    listings = []
    for card in cards:
        try:
            listing = _parse_card(card)
            if listing:
                listings.append(listing)
        except Exception as e:
            logger.debug(f"Could not parse card: {e}")

    listings.sort(key=lambda x: x.get("date") or "", reverse=True)
    return listings


def _parse_card(card) -> dict | None:
    """
    Extracts fields from a single listing card element.
    Adjust selectors here once the real DOM is confirmed via Windows debug run.
    """
    listing_id = (
        card.get_attribute("data-id")
        or card.get_attribute("data-object-id")
        or card.get_attribute("id")
    )

    title = ""
    for sel in [
        "h2",
        "h3",
        ".title",
        ".property-title",
        ".woning-title",
        "[class*='title']",
    ]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            title = el.text.strip()
            if title:
                break
        except Exception:
            pass

    price = ""
    for sel in [".price", "[class*='price']", ".huurprijs", "span[class*='rent']"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            price = el.text.strip()
            if price:
                break
        except Exception:
            pass

    date_str = ""
    for sel in ["time", "[datetime]", "[class*='date']", "[class*='datum']"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            date_str = el.get_attribute("datetime") or el.text.strip()
            if date_str:
                break
        except Exception:
            pass

    url = ""
    for sel in ["a", "a.property-link", "a[href*='woning']", "a[href*='huur']"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            url = el.get_attribute("href") or ""
            if url:
                break
        except Exception:
            pass

    if not listing_id and url:
        listing_id = url.rstrip("/").split("/")[-1]

    if not title and not listing_id:
        return None

    return {
        "id": listing_id or title,
        "title": title,
        "price": price,
        "date": date_str,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def run_check() -> None:
    logger.info("=== Housing watcher check started ===")

    if not ensure_chromedriver(CHROMEDRIVER_PATH):
        logger.critical("ChromeDriver setup failed. Aborting.")
        return

    listings = []
    for _ in range(3):
        try:
            driver = build_driver()
            listings = scrape_listings(driver)
            break
        except Exception as e:
            logger.critical(f"WebDriver error: {e}")
            time.sleep(5)
        finally:
            if driver:
                driver.quit()

    if not listings:
        logger.critical("No listings found — selectors likely need updating.")
        return

    states = load_state()
    if not states:
        for listing in listings:
            states[listing["id"]] = {
                "last_check": datetime.now().isoformat(),
                "title": listing["title"],
                "date": listing["date"],
                "price": listing["price"],
                "url": listing["url"],
            }
        save_state(states)
        logger.info("First run — baseline established, no notifications sent.")
        return

    for listing in listings:
        if listing["id"] not in states:
            logger.info(f"{len(listing)} new listing(s) found.")
            send_telegram(_format_message(listing))
            states[listing["id"]] = {
                "last_check": datetime.now().isoformat(),
                "title": listing["title"],
                "date": listing["date"],
                "price": listing["price"],
                "url": listing["url"],
            }

    save_state(states)

    logger.info("=== Check complete ===")


def _format_message(listing: dict) -> str:
    lines = ["🏠 <b>New Rental Listing!</b>"]
    if listing.get("title"):
        lines.append(f"📍 <b>{listing['title']}</b>")
    if listing.get("price"):
        lines.append(f"💶 {listing['price']}")
    if listing.get("date"):
        lines.append(f"📅 {listing['date']}")
    if listing.get("url"):
        lines.append(f"🔗 <a href=\"{listing['url']}\">{listing['url']}</a>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_check()
