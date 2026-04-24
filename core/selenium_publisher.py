# -*- coding: utf-8 -*-
"""Selenium-based video publisher for Kuaishou CP (Channel B - stable fallback).

Automates the cp.kuaishou.com publish workflow via Chrome browser, replicating
the original KuaishouWebPublisher's behavior. This serves as the fallback
publisher when the HTTP API channel (publisher.py) is unavailable.

The public interface matches KuaishouPublisher so TaskQueue can swap channels.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.config import (
    BROWSER_OPTIONS,
    CHROME_CONFIG,
    KUAISHOU_WEB_URLS,
    PUBLISH_CONFIG,
    WEB_SELECTORS,
)
from core.cookie_manager import CookieManager
from core.db_manager import DBManager
from core.logger import get_logger

log = get_logger("selenium_publisher")


class SeleniumPublisher:
    """Publish videos to Kuaishou via Selenium browser automation.

    This is the stable fallback (Channel B) that drives a real Chrome
    browser through the cp.kuaishou.com publish page. It is slower than
    the HTTP API publisher but more resilient to API-level changes.

    Parameters
    ----------
    cookie_manager : CookieManager
        Manages cookie retrieval and validation for accounts.
    db_manager : DBManager
        Database access for account data and publish records.
    """

    def __init__(self, cookie_manager: CookieManager, db_manager: DBManager) -> None:
        self.cm = cookie_manager
        self.db = db_manager
        self._driver: Optional[webdriver.Chrome] = None

    # ==================================================================
    # Public API (matches KuaishouPublisher interface)
    # ==================================================================

    def publish_video(
        self,
        account_id: int,
        video_path: str,
        drama_name: str,
        caption: Optional[str] = None,
        cover_path: Optional[str] = None,
        is_private: bool = False,
    ) -> dict:
        """Execute the full Selenium publish flow for one account.

        Parameters
        ----------
        account_id : int
            Database ID of the target account.
        video_path : str
            Local path to the video file to upload.
        drama_name : str
            Drama/series name for monetisation task association.
        caption : str, optional
            Post caption. Defaults to ``"{drama_name} #快来看短剧"``.
        cover_path : str, optional
            Local path to a custom cover image. If ``None``, uses auto-cover.
        is_private : bool
            If ``True``, publish as private video.

        Returns
        -------
        dict
            ``{success: bool, photo_id: str | None, message: str}``
        """
        if caption is None:
            caption = f"{drama_name} #快来看短剧"

        log.info(
            "[SeleniumPublisher] Starting publish: account=%s video=%s drama=%s",
            account_id, os.path.basename(video_path), drama_name,
        )

        # --- Pre-flight validation ---
        if not os.path.isfile(video_path):
            return _fail(f"Video not found: {video_path}")

        if os.path.getsize(video_path) == 0:
            return _fail("Video file is empty")

        cookie_list = self._get_cookie_list(account_id)
        if not cookie_list:
            return _fail("No cookies available for account")

        try:
            # Step 1: Launch browser
            log.info("[SeleniumPublisher] Step 1/9: Initialising browser...")
            self._init_browser(account_id)

            # Step 2: Inject cookies
            log.info("[SeleniumPublisher] Step 2/9: Loading cookies...")
            self._load_cookies(cookie_list)

            # Step 3: Navigate to publish page
            log.info("[SeleniumPublisher] Step 3/9: Navigating to publish page...")
            self._navigate_to_publish()

            # Step 4: Upload video file
            log.info("[SeleniumPublisher] Step 4/9: Uploading video...")
            self._upload_video(video_path)

            # Step 5: Wait for upload to complete
            log.info("[SeleniumPublisher] Step 5/9: Waiting for upload processing...")
            self._wait_for_upload_complete()

            # Step 6: Fill title / description
            log.info("[SeleniumPublisher] Step 6/9: Filling video info...")
            self._fill_video_info(caption, drama_name)

            # Step 7: Search and link drama monetisation task
            log.info("[SeleniumPublisher] Step 7/9: Linking drama task...")
            self._search_and_select_drama(drama_name)

            # Step 8: Set publish settings (private flag, cover, etc.)
            log.info("[SeleniumPublisher] Step 8/9: Applying publish settings...")
            self._set_publish_settings(is_private=is_private, cover_path=cover_path)

            # Step 9: Click publish and verify
            log.info("[SeleniumPublisher] Step 9/9: Publishing...")
            self._click_publish_button()
            photo_id = self._verify_publish_success()

            log.info(
                "[SeleniumPublisher] Publish complete: account=%s photo_id=%s",
                account_id, photo_id,
            )
            return {
                "success": True,
                "photo_id": photo_id,
                "message": "Published successfully via Selenium",
            }

        except TimeoutException as exc:
            msg = f"Timeout during publish: {exc}"
            log.error("[SeleniumPublisher] %s", msg)
            return _fail(msg)
        except WebDriverException as exc:
            msg = f"Browser error: {exc}"
            log.error("[SeleniumPublisher] %s", msg)
            return _fail(msg)
        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            log.error("[SeleniumPublisher] %s", msg, exc_info=True)
            return _fail(msg)
        finally:
            self._close_browser()

    # ==================================================================
    # Browser lifecycle
    # ==================================================================

    def _init_browser(self, account_id: int) -> None:
        """Launch Chrome with per-account user data directory.

        Each account gets isolated browser state via a dedicated
        ``--user-data-dir`` so cookies / sessions don't conflict.

        Parameters
        ----------
        account_id : int
            Used to derive the user-data subdirectory and debug port.
        """
        chrome_path = CHROME_CONFIG["chrome_path"]
        driver_path = CHROME_CONFIG["driver_path"]
        user_data_base = CHROME_CONFIG["user_data_base"]
        base_port = int(CHROME_CONFIG["base_port"])

        user_data_dir = os.path.join(str(user_data_base), str(account_id))
        os.makedirs(user_data_dir, exist_ok=True)
        debug_port = base_port + int(account_id)

        opts = Options()
        if chrome_path:
            opts.binary_location = str(chrome_path)

        # Standard stability flags
        if BROWSER_OPTIONS.get("no_sandbox"):
            opts.add_argument("--no-sandbox")
        if BROWSER_OPTIONS.get("disable_gpu"):
            opts.add_argument("--disable-gpu")
        if BROWSER_OPTIONS.get("disable_dev_shm"):
            opts.add_argument("--disable-dev-shm-usage")
        if BROWSER_OPTIONS.get("headless"):
            opts.add_argument("--headless=new")

        window_size = BROWSER_OPTIONS.get("window_size", "1920,1080")
        opts.add_argument(f"--window-size={window_size}")

        opts.add_argument(f"--user-data-dir={user_data_dir}")
        opts.add_argument(f"--remote-debugging-port={debug_port}")

        # Suppress automation detection banners
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        service = Service(executable_path=str(driver_path))

        log.debug(
            "[SeleniumPublisher] Launching Chrome: binary=%s driver=%s port=%d",
            chrome_path, driver_path, debug_port,
        )
        self._driver = webdriver.Chrome(service=service, options=opts)
        self._driver.set_page_load_timeout(60)
        self._driver.implicitly_wait(5)
        log.info("[SeleniumPublisher] Browser launched for account %s", account_id)

    def _close_browser(self) -> None:
        """Safely close the browser and release resources."""
        if self._driver is not None:
            try:
                self._driver.quit()
                log.info("[SeleniumPublisher] Browser closed")
            except WebDriverException as exc:
                log.warning("[SeleniumPublisher] Error closing browser: %s", exc)
            finally:
                self._driver = None

    # ==================================================================
    # Cookie management
    # ==================================================================

    def _get_cookie_list(self, account_id: int) -> list[dict]:
        """Retrieve raw cookie dicts from the database.

        Returns a list of ``{name, value, domain, ...}`` dicts suitable
        for ``driver.add_cookie()``.
        """
        try:
            raw = self.db.get_account_cookies(account_id)
            if not raw:
                return []
            if isinstance(raw, str):
                raw = json.loads(raw)
            # Handle nested format: {"cookies": [...]}
            if isinstance(raw, dict) and "cookies" in raw:
                return raw["cookies"]
            if isinstance(raw, list):
                return raw
            return []
        except Exception as exc:
            log.error(
                "[SeleniumPublisher] Failed to load cookies for account %s: %s",
                account_id, exc,
            )
            return []

    def _load_cookies(self, cookie_list: list[dict]) -> None:
        """Inject cookies into the browser session.

        Must navigate to the target domain first so that the browser
        accepts cookies for that domain.

        Parameters
        ----------
        cookie_list : list[dict]
            Cookie dicts with at least ``name`` and ``value`` keys.
        """
        driver = self._require_driver()

        # Navigate to the domain first so cookies are accepted
        driver.get("https://cp.kuaishou.com/")
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        loaded = 0
        for cookie in cookie_list:
            if not isinstance(cookie, dict):
                continue
            if "name" not in cookie or "value" not in cookie:
                continue

            selenium_cookie = {
                "name": cookie["name"],
                "value": str(cookie["value"]),
            }

            # Copy optional fields if present
            if "domain" in cookie:
                selenium_cookie["domain"] = cookie["domain"]
            if "path" in cookie:
                selenium_cookie["path"] = cookie["path"]
            if "secure" in cookie:
                selenium_cookie["secure"] = bool(cookie["secure"])
            if "httpOnly" in cookie:
                selenium_cookie["httpOnly"] = bool(cookie["httpOnly"])

            try:
                driver.add_cookie(selenium_cookie)
                loaded += 1
            except WebDriverException as exc:
                log.debug(
                    "[SeleniumPublisher] Skipped cookie '%s': %s",
                    cookie.get("name"), exc,
                )

        log.info("[SeleniumPublisher] Loaded %d/%d cookies", loaded, len(cookie_list))

    # ==================================================================
    # Publish workflow steps
    # ==================================================================

    def _navigate_to_publish(self) -> None:
        """Navigate to the video publish page and wait for it to load."""
        driver = self._require_driver()
        publish_url = KUAISHOU_WEB_URLS["publish_url"]

        driver.get(publish_url)
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Verify we are on the publish page (not redirected to login)
        current = driver.current_url
        if "passport" in current or "login" in current:
            raise WebDriverException(
                f"Redirected to login page ({current}). Cookies may be expired."
            )
        log.info("[SeleniumPublisher] Publish page loaded: %s", current)

    def _upload_video(self, video_path: str) -> None:
        """Send the video file to the upload input element.

        The upload ``<input type="file">`` is typically hidden; Selenium's
        ``send_keys`` works on hidden file inputs without clicking.

        Parameters
        ----------
        video_path : str
            Absolute path to the video file.
        """
        driver = self._require_driver()
        upload_timeout = PUBLISH_CONFIG["upload_timeout"]

        # Locate the file input -- may be hidden
        upload_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, WEB_SELECTORS["upload_input"]))
        )

        abs_path = os.path.abspath(video_path)
        log.debug("[SeleniumPublisher] Sending file to upload input: %s", abs_path)
        upload_input.send_keys(abs_path)
        log.info("[SeleniumPublisher] Video file submitted to upload input")

    def _wait_for_upload_complete(self) -> None:
        """Wait for the video upload and server-side processing to finish.

        Watches for the upload progress indicator to disappear or for
        processing-complete signals on the page.
        """
        driver = self._require_driver()
        upload_timeout = PUBLISH_CONFIG["upload_timeout"]
        process_timeout = PUBLISH_CONFIG["process_timeout"]
        total_timeout = upload_timeout + process_timeout

        # Wait for upload progress bar to appear then disappear
        try:
            # First, wait for progress element to show up (upload started)
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".upload-progress, .progress-bar, [class*='progress']")
                )
            )
            log.debug("[SeleniumPublisher] Upload progress detected")
        except TimeoutException:
            # Progress bar may not appear for very fast uploads
            log.debug("[SeleniumPublisher] No progress bar detected, continuing")

        # Wait for progress to finish: either the progress element disappears
        # or the publish button becomes enabled
        try:
            WebDriverWait(driver, total_timeout).until(
                _upload_finished_condition
            )
            log.info("[SeleniumPublisher] Upload/processing complete")
        except TimeoutException:
            # Take a screenshot for debugging before raising
            self._save_debug_screenshot("upload_timeout")
            raise TimeoutException(
                f"Video upload/processing did not complete within {total_timeout}s"
            )

    def _fill_video_info(self, caption: str, drama_name: str) -> None:
        """Fill in the title and description fields on the publish form.

        Parameters
        ----------
        caption : str
            Text for the title / caption field.
        drama_name : str
            Drama name, used as part of description if no separate field.
        """
        driver = self._require_driver()

        # Title input
        try:
            title_el = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, WEB_SELECTORS["title_input"])
                )
            )
            title_el.clear()
            title_el.send_keys(caption)
            log.debug("[SeleniumPublisher] Title set: %s", caption[:50])
        except TimeoutException:
            log.warning("[SeleniumPublisher] Title input not found, skipping")

        # Description textarea
        try:
            desc_el = driver.find_element(
                By.CSS_SELECTOR, WEB_SELECTORS["description_textarea"]
            )
            desc_el.clear()
            desc_el.send_keys(f"{drama_name} #快来看短剧 #短剧推荐")
            log.debug("[SeleniumPublisher] Description set")
        except NoSuchElementException:
            log.debug("[SeleniumPublisher] Description textarea not found, skipping")

    def _search_and_select_drama(self, drama_name: str) -> None:
        """Search for and select the drama monetisation task.

        Looks for the drama/banner task linking UI on the publish page,
        enters the drama name, and selects the matching result.

        Parameters
        ----------
        drama_name : str
            Name of the drama to search for.
        """
        driver = self._require_driver()

        # The drama linking section may use various selectors
        drama_selectors = [
            "input[placeholder*='剧目'], input[placeholder*='短剧']",
            "input[placeholder*='搜索'], input[placeholder*='关联']",
            "[class*='drama'] input, [class*='banner'] input",
        ]

        drama_input = None
        for selector in drama_selectors:
            try:
                drama_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                break
            except TimeoutException:
                continue

        if drama_input is None:
            log.warning(
                "[SeleniumPublisher] Drama search input not found, skipping drama link"
            )
            return

        # Type the drama name and wait for results
        drama_input.clear()
        drama_input.send_keys(drama_name)
        log.debug("[SeleniumPublisher] Searching for drama: %s", drama_name)

        # Wait for dropdown results
        result_selectors = [
            "[class*='dropdown'] [class*='item']",
            "[class*='search-result'] [class*='item']",
            "[class*='option']",
            "li[class*='drama']",
        ]

        for selector in result_selectors:
            try:
                results = WebDriverWait(driver, 8).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                )
                if results:
                    # Click the first matching result
                    results[0].click()
                    log.info(
                        "[SeleniumPublisher] Drama '%s' selected", drama_name
                    )
                    return
            except TimeoutException:
                continue

        log.warning(
            "[SeleniumPublisher] No drama results found for '%s'", drama_name
        )

    def _set_publish_settings(
        self,
        is_private: bool = False,
        cover_path: Optional[str] = None,
    ) -> None:
        """Configure publish settings: visibility, cover image, etc.

        Parameters
        ----------
        is_private : bool
            If ``True``, check the private-publish checkbox.
        cover_path : str, optional
            Path to a custom cover image to upload.
        """
        driver = self._require_driver()

        # Set private mode if requested
        if is_private:
            try:
                private_cb = driver.find_element(
                    By.CSS_SELECTOR,
                    "input[type='checkbox'][name='private'], "
                    "[class*='private'] input[type='checkbox']"
                )
                if not private_cb.is_selected():
                    private_cb.click()
                    log.info("[SeleniumPublisher] Private mode enabled")
            except NoSuchElementException:
                log.warning("[SeleniumPublisher] Private checkbox not found")

        # Upload custom cover image if provided
        if cover_path and os.path.isfile(cover_path):
            try:
                cover_input = driver.find_element(
                    By.CSS_SELECTOR, WEB_SELECTORS["cover_upload"]
                )
                cover_input.send_keys(os.path.abspath(cover_path))
                log.info("[SeleniumPublisher] Custom cover uploaded: %s", cover_path)
                # Brief wait for cover to process
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[class*='cover'] img, .cover-preview img")
                    )
                )
            except (NoSuchElementException, TimeoutException):
                log.warning("[SeleniumPublisher] Cover upload failed, using auto-cover")

    def _click_publish_button(self) -> None:
        """Locate and click the publish / submit button."""
        driver = self._require_driver()
        publish_timeout = PUBLISH_CONFIG["publish_timeout"]

        # Try multiple selectors for the publish button
        button_selectors = [
            WEB_SELECTORS["publish_button"],
            "button[class*='publish']",
            "button[class*='submit']",
        ]

        for selector in button_selectors:
            try:
                # Use a CSS-only selector (strip any pseudo-selectors like :has-text)
                css_selector = selector.split(":has-text")[0].strip().rstrip(",")
                if not css_selector:
                    continue

                publish_btn = WebDriverWait(driver, publish_timeout).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
                )
                publish_btn.click()
                log.info("[SeleniumPublisher] Publish button clicked")
                return
            except (TimeoutException, NoSuchElementException):
                continue

        # Fallback: try XPath with text matching
        try:
            publish_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(),'发布') or contains(text(),'提交')]")
                )
            )
            publish_btn.click()
            log.info("[SeleniumPublisher] Publish button clicked (XPath fallback)")
            return
        except TimeoutException:
            pass

        self._save_debug_screenshot("publish_button_not_found")
        raise WebDriverException("Could not find or click the publish button")

    def _verify_publish_success(self) -> Optional[str]:
        """Wait for the publish success confirmation.

        Returns
        -------
        str or None
            The photo/work ID if extractable from the success page,
            otherwise ``None``.
        """
        driver = self._require_driver()
        verify_timeout = PUBLISH_CONFIG["verify_timeout"]

        # Wait for success indicator
        success_selectors = [
            (By.XPATH, "//*[contains(text(),'发布成功')]"),
            (By.XPATH, "//*[contains(text(),'提交成功')]"),
            (By.CSS_SELECTOR, WEB_SELECTORS["success_message"]),
            (By.CSS_SELECTOR, "[class*='success']"),
        ]

        for by, selector in success_selectors:
            try:
                WebDriverWait(driver, verify_timeout).until(
                    EC.presence_of_element_located((by, selector))
                )
                log.info("[SeleniumPublisher] Publish success confirmed")
                break
            except TimeoutException:
                continue
        else:
            # Check if we were redirected to works page (also indicates success)
            current_url = driver.current_url
            if "manage" in current_url or "my-works" in current_url:
                log.info(
                    "[SeleniumPublisher] Redirected to works page, treating as success"
                )
            else:
                self._save_debug_screenshot("verify_failed")
                raise TimeoutException(
                    f"Publish success not confirmed within {verify_timeout}s"
                )

        # Try to extract photo_id from the page or URL
        return self._extract_photo_id()

    def _extract_photo_id(self) -> Optional[str]:
        """Attempt to extract the published photo/work ID from the page.

        Returns
        -------
        str or None
            The photo ID string if found.
        """
        driver = self._require_driver()

        # Method 1: Check URL for an ID parameter
        current_url = driver.current_url
        for param in ("photoId", "workId", "id"):
            if f"{param}=" in current_url:
                try:
                    from urllib.parse import parse_qs, urlparse

                    parsed = urlparse(current_url)
                    qs = parse_qs(parsed.query)
                    if param in qs:
                        photo_id = qs[param][0]
                        log.info("[SeleniumPublisher] Extracted photo_id from URL: %s", photo_id)
                        return photo_id
                except Exception:
                    pass

        # Method 2: Look for the ID in page text / data attributes
        try:
            el = driver.find_element(
                By.CSS_SELECTOR,
                "[data-photo-id], [data-work-id], [data-id]"
            )
            for attr in ("data-photo-id", "data-work-id", "data-id"):
                val = el.get_attribute(attr)
                if val:
                    log.info("[SeleniumPublisher] Extracted photo_id from element: %s", val)
                    return val
        except NoSuchElementException:
            pass

        log.debug("[SeleniumPublisher] Could not extract photo_id")
        return None

    # ==================================================================
    # Helpers
    # ==================================================================

    def _require_driver(self) -> webdriver.Chrome:
        """Return the current driver or raise if not initialised."""
        if self._driver is None:
            raise WebDriverException("Browser not initialised -- call _init_browser first")
        return self._driver

    def _save_debug_screenshot(self, label: str) -> None:
        """Save a screenshot for post-mortem debugging.

        Parameters
        ----------
        label : str
            Short label to include in the filename.
        """
        if self._driver is None:
            return
        try:
            screenshot_dir = Path("D:/ks_automation/logs/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = screenshot_dir / f"selenium_{label}_{ts}.png"
            self._driver.save_screenshot(str(path))
            log.info("[SeleniumPublisher] Debug screenshot saved: %s", path)
        except Exception as exc:
            log.warning("[SeleniumPublisher] Failed to save screenshot: %s", exc)


# ======================================================================
# Module-level helpers
# ======================================================================

def _fail(message: str) -> dict:
    """Build a standardised failure result dict."""
    return {"success": False, "photo_id": None, "message": message}


def _upload_finished_condition(driver: webdriver.Chrome) -> bool:
    """Custom expected-condition: upload has finished.

    Returns ``True`` when either:
    - No progress elements remain visible, or
    - The publish button is clickable (implies upload done).
    """
    # Check if progress indicators are gone
    progress_elements = driver.find_elements(
        By.CSS_SELECTOR,
        ".upload-progress, .progress-bar, [class*='progress'][class*='active']"
    )
    progress_visible = any(
        el.is_displayed() for el in progress_elements
    )

    if not progress_visible:
        return True

    # Alternatively, check if publish button is enabled
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[class*='publish']")
        return btn.is_enabled() and not btn.get_attribute("disabled")
    except NoSuchElementException:
        return False
