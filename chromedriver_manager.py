import os
import re
import stat
import shutil
import zipfile
import logging
import platform
import subprocess
import requests

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_DOCKER = os.getenv("DOCKER", "false").strip().lower() == "true"

MIN_CHROMEDRIVER_VERSION = 115
CHROMEDRIVER_LATEST_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)


def ensure_chromedriver(chromedriver_path: str) -> bool:
    """
    Docker:  ChromeDriver is bundled in selenium/standalone-chrome — skip entirely.
    Local:   Check version; download latest stable if missing or version <= 115.
    Returns True if ready to use, False on failure.
    """
    logger.info("Ensuring ChromeDriver is ready for Selenium.")
    logger.info(f"Checking ChromeDriver path: {chromedriver_path}")
    # Ensure the local or Docker ChromeDriver installation is valid before running Selenium
    if IS_DOCKER:
        logger.info(f"Docker mode — using bundled ChromeDriver at {chromedriver_path}.")
        return True

    version = _get_installed_version(chromedriver_path)

    if version is not None and version > MIN_CHROMEDRIVER_VERSION:
        logger.info(f"ChromeDriver v{version} at {chromedriver_path} — OK.")
        return True

    if version is not None:
        logger.warning(
            f"ChromeDriver v{version} is <= minimum ({MIN_CHROMEDRIVER_VERSION}). Re-downloading."
        )
    else:
        logger.info("ChromeDriver not found. Downloading latest stable.")

    dest_dir = os.path.dirname(chromedriver_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    return _download_latest(chromedriver_path)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _get_installed_version(chromedriver_path: str) -> int | None:
    # Return installed ChromeDriver major version, or None if it is missing
    if not os.path.isfile(chromedriver_path):
        return None
    try:
        result = subprocess.run(
            [chromedriver_path, "--version"], capture_output=True, text=True, timeout=5
        )
        match = re.search(r"ChromeDriver (\d+)\.", result.stdout)
        if match:
            return int(match.group(1))
    except Exception as e:
        logger.warning(f"Could not read ChromeDriver version: {e}")
    return None


def _platform_key() -> str:
    return "win64" if IS_WINDOWS else "linux64"


def _zip_entry_suffix(platform_key: str) -> str:
    return "/chromedriver.exe" if platform_key == "win64" else "/chromedriver"


def _leftover_folder(platform_key: str) -> str:
    return f"chromedriver-{platform_key}"


def _download_latest(destination_path: str) -> bool:
    # Download and install the latest ChromeDriver for the current platform
    platform_key = _platform_key()
    entry_suffix = _zip_entry_suffix(platform_key)
    leftover = _leftover_folder(platform_key)

    try:
        logger.info("Fetching latest stable ChromeDriver info...")
        resp = requests.get(CHROMEDRIVER_LATEST_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        stable = data["channels"]["Stable"]
        version = stable["version"]
        downloads = stable["downloads"].get("chromedriver", [])

        download_url = next(
            (d["url"] for d in downloads if d["platform"] == platform_key), None
        )
        if not download_url:
            logger.error(f"No {platform_key} ChromeDriver download found.")
            return False

        logger.info(f"Downloading ChromeDriver {version} ({platform_key})...")
        zip_path = destination_path + ".zip"

        with requests.get(download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        dest_dir = os.path.dirname(destination_path) or "."
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.namelist():
                if member.endswith(entry_suffix):
                    extracted = z.extract(member, dest_dir)
                    if os.path.abspath(extracted) != os.path.abspath(destination_path):
                        shutil.move(extracted, destination_path)
                    break

        os.remove(zip_path)

        leftover_dir = os.path.join(dest_dir, leftover)
        if os.path.isdir(leftover_dir):
            shutil.rmtree(leftover_dir)

        if not IS_WINDOWS:
            st = os.stat(destination_path)
            os.chmod(
                destination_path,
                st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
            )

        logger.info(f"ChromeDriver {version} installed at {destination_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to download ChromeDriver: {e}")
        return False
