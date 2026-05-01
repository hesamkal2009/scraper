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

_file_handler = logging.FileHandler(LOG_FILE, mode="w")
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
    logger.info(f"Loading existing state from {STATE_FILE}")
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(states: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    logger.info(f"Saving top 10 listings to state file {STATE_FILE}")

    # 1. Sort and slice the items first
    # 2. Convert back to a dict
    # 3. Assign it to a variable (or overwrite 'state')
    sorted_items = sorted(
        states.items(), key=lambda item: item[1]["date"], reverse=True
    )
    top_10_state = dict(sorted_items[:10])

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(top_10_state, f, indent=2)
        logger.info(f"State saved: {len(top_10_state)} listings in memory.")
    except Exception as e:
        logger.critical(f"Failed to save state file: {e}")


# ---------------------------------------------------------------------------
# Chrome driver
# ---------------------------------------------------------------------------
SELENIUM_GRID_URL = "http://localhost:4444/wd/hub"


def _wait_for_grid(timeout: int = 30) -> None:
    """Block until the Selenium Grid inside the container is accepting sessions."""
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{SELENIUM_GRID_URL}/status", timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Selenium Grid not ready after {timeout}s.")


def _build_options() -> Options:
    options = Options()

    if not IS_DOCKER:
        chrome_binary = CHROME_BINARY or _detect_chrome_binary()
        options.binary_location = chrome_binary

    if HEADLESS or IS_DOCKER:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")

    if not IS_WINDOWS:
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    return options


def build_driver():
    options = _build_options()

    if IS_DOCKER:
        logger.info(f"Docker — connecting to Selenium Grid at {SELENIUM_GRID_URL}")
        _wait_for_grid()
        driver = webdriver.Remote(
            command_executor=SELENIUM_GRID_URL,
            options=options,
        )
    else:
        chrome_binary = CHROME_BINARY or _detect_chrome_binary()
        logger.info(f"Local — Chrome: {chrome_binary} | headless={HEADLESS}")
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

    _press_tabs(driver, 5)  # Move to language selector
    driver.switch_to.active_element.send_keys(Keys.ENTER)
    _press_arrows_enter_tab(driver, 2, final_tab=False)
    driver.switch_to.active_element.send_keys(Keys.ENTER)

    time.sleep(3)  # Wait for language change to take effect

    # Search for location (twice)
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
    Extracts all fields from a single listing card element.
    Filters by rental status (only "For rent" / "Te huur").
    """
    status = ""
    for sel in [".badge", "[class*='status']", "span.badge"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            status = el.text.strip()
            if status:
                break
        except Exception:
            pass

    # Only process if it's a rental listing
    if not any(term in status.lower() for term in ["for rent", "te huur"]):
        return None

    listing_id = (
        card.get_attribute("data-id")
        or card.get_attribute("data-object-id")
        or card.get_attribute("id")
    )

    title = ""
    for sel in ["h5.card-title a", ".card-title a", "h2", "h3"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            title = el.text.strip()
            if title:
                break
        except Exception:
            pass

    url = ""
    for sel in ["a.stretched-link", ".card-title a", "a[href*='object']"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            url = el.get_attribute("href") or ""
            if url:
                break
        except Exception:
            pass

    if not listing_id and url:
        listing_id = url.rstrip("/").split("/")[-1]

    # Extract price
    price = ""
    for sel in [".fw-bold", "[class*='price']", "span.fw-bold"]:
        try:
            el = card.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if "€" in text or "month" in text.lower():
                price = text
                break
        except Exception:
            pass

    # Extract location/address
    location = ""
    try:
        # Find span with location info (usually 2nd or 3rd span in card-body)
        spans = card.find_elements(By.CSS_SELECTOR, ".card-body span")
        if len(spans) > 1:
            location = spans[1].text.strip()
    except Exception:
        pass

    # Extract available from date
    available_from = ""
    try:
        date_span = card.find_element(By.CSS_SELECTOR, ".d-flex.gap-1")
        date_text = date_span.text.strip()
        if "available" in date_text.lower():
            available_from = date_text
        else:
            available_from = date_text
    except Exception:
        pass

    # Extract size (m²)
    size = ""
    try:
        size_el = card.find_element(By.CSS_SELECTOR, "sup")
        parent = size_el.find_element(By.XPATH, "..")
        size_text = parent.text.strip()
        size = size_text
    except Exception:
        pass

    # Extract bedrooms
    bedrooms = ""
    try:
        spans = card.find_elements(By.CSS_SELECTOR, ".card-body span")
        for span in spans:
            text = span.text.strip()
            if "bedroom" in text.lower():
                bedrooms = text
                break
    except Exception:
        pass

    # Extract image
    image_url = ""
    try:
        img = card.find_element(By.CSS_SELECTOR, "img")
        image_url = img.get_attribute("src") or img.get_attribute("srcset")
    except Exception:
        pass

    # Extract registration info
    registration = ""
    try:
        reg_span = card.find_element(
            By.CSS_SELECTOR, ".d-flex.gap-1 span:contains('Register')"
        )
        registration = reg_span.text.strip()
    except Exception:
        try:
            spans = card.find_elements(By.CSS_SELECTOR, ".card-body span")
            for span in spans:
                if "register" in span.text.lower():
                    registration = span.text.strip()
                    break
        except Exception:
            pass

    if not title and not listing_id:
        return None

    return {
        "id": listing_id or title,
        "title": title,
        "url": url,
        "status": status,
        "price": price,
        "location": location,
        "available_from": available_from,
        "size": size,
        "bedrooms": bedrooms,
        "image_url": image_url,
        "registration_info": registration,
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
    driver = None
    for attempt in range(1, 4):
        logger.info(f"[Attempt {attempt}/3] Starting browser session")
        try:
            driver = build_driver()
            listings = scrape_listings(driver)
            logger.info(
                f"[Attempt {attempt}/3] Scrape completed: {len(listings)} listings loaded."
            )
            break
        except Exception as e:
            logger.critical(f"WebDriver error on attempt {attempt}: {e}")
            if attempt < 3:
                logger.info("Retrying after failure...")
                time.sleep(5)
        finally:
            if driver is not None:
                driver.quit()
                logger.info(f"[Attempt {attempt}/3] Browser session closed.")
                driver = None

    if not listings:
        logger.critical("No listings found — selectors likely need updating.")
        return

    states = load_state()
    logger.info(f"Existing state entries: {len(states)}")
    if not states:
        for listing in listings:
            states[listing["id"]] = {
                "last_check": datetime.now().isoformat(),
                "title": listing["title"],
                "url": listing["url"],
                "status": listing["status"],
                "price": listing["price"],
                "location": listing["location"],
                "available_from": listing["available_from"],
                "size": listing["size"],
                "bedrooms": listing["bedrooms"],
                "image_url": listing["image_url"],
                "registration_info": listing["registration_info"],
            }
        save_state(states)
        logger.info("First run — baseline established, no notifications sent.")
        return

    new_count = 0
    for listing in listings:
        if listing["id"] not in states:
            new_count += 1
            logger.info(
                f"New listing found: {listing['id']} | {listing.get('title', 'N/A')}"
            )
            send_telegram(_format_message(listing))
            states[listing["id"]] = {
                "last_check": datetime.now().isoformat(),
                "title": listing["title"],
                "url": listing["url"],
                "status": listing["status"],
                "price": listing["price"],
                "location": listing["location"],
                "available_from": listing["available_from"],
                "size": listing["size"],
                "bedrooms": listing["bedrooms"],
                "image_url": listing["image_url"],
                "registration_info": listing["registration_info"],
            }

    if new_count > 0:
        logger.info(f"Total new listings: {new_count}")
    save_state(states)

    logger.info("=== Check complete ===")


def _format_message(listing: dict) -> str:
    """Format listing data for Telegram notification"""
    lines = ["🏠 <b>New Rental Listing!</b>"]

    if listing.get("title"):
        lines.append(f"📍 <b>{listing['title']}</b>")

    if listing.get("location"):
        lines.append(f"📌 {listing['location']}")

    if listing.get("price"):
        lines.append(f"💶 <b>{listing['price']}</b>")

    if listing.get("size"):
        lines.append(f"📐 {listing['size']}")

    if listing.get("bedrooms"):
        lines.append(f"🛏️ {listing['bedrooms']}")

    if listing.get("available_from"):
        lines.append(f"📅 {listing['available_from']}")

    if listing.get("url"):
        lines.append(f"🔗 <a href=\"{listing['url']}\">View Listing</a>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_check()
