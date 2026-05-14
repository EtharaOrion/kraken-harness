# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

import requests
from bs4 import BeautifulSoup
from fastcore.net import HTTP403ForbiddenError, HTTP404NotFoundError
from ghapi.core import GhApi
from unidiff import PatchSet

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Rate-limit ceiling: 12 retries * 5min = 1 hour max per stuck token.
# Beyond this, the token is treated as permanently revoked.
MAX_RATE_LIMIT_RETRIES = int(os.environ.get("SWEFF_MAX_RATE_LIMIT_RETRIES", "12"))
RATE_LIMIT_SLEEP_SECONDS = int(os.environ.get("SWEFF_RATE_LIMIT_SLEEP", str(60 * 5)))
MAX_HTTP_RETRIES = int(os.environ.get("SWEFF_MAX_HTTP_RETRIES", "8"))

# DLQ (dead-letter queue): structured failure log for autonomous pipeline runs.
# When a recoverable failure happens, we write a JSONL record here so the run
# completes and humans can triage afterwards instead of silently dropping data.
_DLQ_DIR = Path(os.environ.get("SWEFF_DLQ_DIR", "artifacts/dlq"))
_DLQ_LOCK = threading.Lock()


class TokenStuckError(Exception):
    """Raised when a GitHub token appears revoked or permanently rate-limited."""


class PatchFetchError(Exception):
    """Raised when a patch cannot be fetched from GitHub after retries."""


def write_to_dlq(filename: str, record: dict) -> None:
    """Append a failure record to a dead-letter queue file (thread-safe).

    Args:
        filename: bare filename (e.g. 'patch_fetch_failures.jsonl').
        record: arbitrary JSON-serializable dict describing the failure.
    """
    record.setdefault("ts", time.time())
    try:
        with _DLQ_LOCK:
            _DLQ_DIR.mkdir(parents=True, exist_ok=True)
            with (_DLQ_DIR / filename).open("a") as f:
                f.write(json.dumps(record) + "\n")
    except Exception as exc:
        # DLQ write must never crash the pipeline. Surface to stderr only.
        logger.error(f"DLQ write failed for {filename}: {exc}")


class Repo:
    def __init__(self, owner: str, name: str, token: Optional[str] = None):
        """
        Init to retrieve target repository and create ghapi tool

        Args:
            owner (str): owner of target repository
            name (str): name of target repository
            token (str): github token
        """
        self.owner = owner
        self.name = name
        self.token = token
        self.api = GhApi(token=token)
        self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)
        # GitHub API may redirect to a fork if the token owner has one.
        # Force canonical owner/name to prevent fork resolution issues.
        if self.repo is not None:
            canonical = f"{owner}/{name}"
            if self.repo.full_name != canonical:
                logger.warning(
                    f"GitHub resolved {canonical} as {self.repo.full_name} "
                    f"(token user's fork). Forcing canonical name."
                )
                self.repo.full_name = canonical
                self.repo.owner.login = owner
                self.repo.name = name

    def call_api(self, func: Callable, **kwargs) -> dict | None:
        """
        API call wrapper with bounded rate limit handling.

        Sleeps up to MAX_RATE_LIMIT_RETRIES * RATE_LIMIT_SLEEP_SECONDS (default
        1 hour) for a stuck token before raising TokenStuckError. This prevents
        a single revoked token from hanging the entire pipeline.

        Args:
            func (callable): API function to call
            **kwargs: keyword arguments to pass to API function
        Return:
            values (dict): response object of `func`
        """
        call_attempts = 0
        while call_attempts < MAX_RATE_LIMIT_RETRIES:
            try:
                return func(**kwargs)
            except HTTP403ForbiddenError:
                for attempt in range(MAX_RATE_LIMIT_RETRIES):
                    try:
                        rl = self.api.rate_limit.get()
                        remaining = rl.resources.core.remaining
                    except Exception as exc:
                        logger.warning(
                            f"[{self.owner}/{self.name}] rate_limit.get() failed: {exc}"
                        )
                        remaining = 0
                    logger.info(
                        f"[{self.owner}/{self.name}] Rate limit exceeded for token {self.token[:10]}, "
                        f"attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES}, remaining calls: {remaining}"
                    )
                    if remaining > 0:
                        break
                    time.sleep(RATE_LIMIT_SLEEP_SECONDS)
                else:
                    write_to_dlq(
                        "token_stuck.jsonl",
                        {
                            "repo": f"{self.owner}/{self.name}",
                            "token_prefix": self.token[:10] if self.token else None,
                            "reason": "call_api rate-limit exhausted",
                        },
                    )
                    raise TokenStuckError(
                        f"Token {self.token[:10] if self.token else '<none>'} appears revoked: "
                        f"rate limit never reset after {MAX_RATE_LIMIT_RETRIES} retries"
                    )
                call_attempts += 1
            except HTTP404NotFoundError:
                logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
                return None
        # call_attempts exhausted (e.g. repeated 403s without rate-limit recovery)
        raise TokenStuckError(
            f"call_api gave up after {MAX_RATE_LIMIT_RETRIES} attempts for "
            f"{self.owner}/{self.name}: {func.__name__}"
        )

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by a PR

        Args:
            pull (dict): PR dictionary object from GitHub
        Return:
            resolved_issues (list): list of issue numbers referenced by PR
        """
        # Define 1. issue number regex pattern 2. comment regex pattern 3. keywords
        issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
        comments_pat = re.compile(r"(?s)<!--.*?-->")
        keywords = {
            "close",
            "closes",
            "closed",
            "fix",
            "fixes",
            "fixed",
            "resolve",
            "resolves",
            "resolved",
        }

        # Construct text to search over for issue numbers from PR body and commit messages
        text = pull.title if pull.title else ""
        text += "\n" + (pull.body if pull.body else "")
        commits = self.get_all_loop(
            self.api.pulls.list_commits, pull_number=pull.number, quiet=True
        )
        commit_messages = [commit.commit.message for commit in commits]
        commit_text = "\n".join(commit_messages) if commit_messages else ""
        text += "\n" + commit_text
        # Remove comments from text
        text = comments_pat.sub("", text)
        # Look for issue numbers in text via scraping <keyword, number> patterns
        references = dict(issues_pat.findall(text))
        resolved_issues = list()
        if references:
            for word, issue_num in references.items():
                if word.lower() in keywords:
                    resolved_issues.append(issue_num)
        return resolved_issues

    def get_all_loop(
        self,
        func: Callable,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        quiet: bool = False,
        **kwargs,
    ) -> Iterator:
        """
        Return all values from a paginated API endpoint.

        Args:
            func (callable): API function to call
            per_page (int): number of values to return per page
            num_pages (int): number of pages to return
            quiet (bool): whether to print progress
            **kwargs: keyword arguments to pass to API function
        """
        page = 1
        args = {
            "owner": self.owner,
            "repo": self.name,
            "per_page": per_page,
            **kwargs,
        }
        while True:
            try:
                # Get values from API call
                values = func(**args, page=page)
                yield from values
                if len(values) == 0:
                    break
                if not quiet:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Processed page {page} ({per_page} values per page). "
                        f"Remaining calls: {rl.resources.core.remaining}"
                    )
                if num_pages is not None and page >= num_pages:
                    break
                page += 1
            except (HTTP403ForbiddenError, requests.exceptions.HTTPError) as e:
                # Rate-limit path: bounded retry, then DLQ + raise.
                logger.warning(
                    f"[{self.owner}/{self.name}] HTTP/rate-limit error on page {page} "
                    f"w/ token {self.token[:10]} - {e}"
                )
                for attempt in range(MAX_RATE_LIMIT_RETRIES):
                    try:
                        rl = self.api.rate_limit.get()
                        remaining = rl.resources.core.remaining
                    except Exception as inner:
                        logger.warning(
                            f"[{self.owner}/{self.name}] rate_limit.get() failed: {inner}"
                        )
                        remaining = 0
                    if remaining > 0:
                        break
                    logger.info(
                        f"[{self.owner}/{self.name}] Waiting for rate limit reset "
                        f"for token {self.token[:10]} (attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES})"
                    )
                    time.sleep(RATE_LIMIT_SLEEP_SECONDS)
                else:
                    write_to_dlq(
                        "token_stuck.jsonl",
                        {
                            "repo": f"{self.owner}/{self.name}",
                            "token_prefix": self.token[:10] if self.token else None,
                            "page": page,
                            "reason": "get_all_loop rate-limit exhausted",
                        },
                    )
                    raise TokenStuckError(
                        f"Token {self.token[:10] if self.token else '<none>'} appears revoked"
                    )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # Network-level failures: short backoff, do not exhaust the rate-limit budget.
                logger.warning(
                    f"[{self.owner}/{self.name}] Network error on page {page}: {e}; backing off 30s"
                )
                time.sleep(30)
        if not quiet:
            logger.info(
                f"[{self.owner}/{self.name}] Processed {(page-1)*per_page + len(values)} values"
            )

    def get_all_issues(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all issues from repo

        Args:
            per_page (int): number of issues to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort issues
            sort (str): field to sort issues by
            state (str): state of issues to look for
            quiet (bool): whether to print progress
        """
        issues = self.get_all_loop(
            self.api.issues.list_for_repo,
            num_pages=num_pages,
            per_page=per_page,
            direction=direction,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return issues

    def get_all_pulls(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all PRs from repo

        Args:
            per_page (int): number of PRs to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort PRs
            sort (str): field to sort PRs by
            state (str): state of PRs to look for
            quiet (bool): whether to print progress
        """
        pulls = self.get_all_loop(
            self.api.pulls.list,
            num_pages=num_pages,
            direction=direction,
            per_page=per_page,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return pulls


def extract_problem_statement_and_hints(pull: dict, repo: Repo) -> tuple[str, str]:
    """
    Extract problem statement from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    if repo.name == "django":
        return extract_problem_statement_and_hints_django(pull, repo)
    text = ""
    all_hint_texts = list()
    for issue_number in pull["resolved_issues"]:
        issue = repo.call_api(
            repo.api.issues.get,
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
        )
        if issue is None:
            continue
        title = issue.title if issue.title else ""
        body = issue.body if issue.body else ""
        text += f"{title}\n{body}\n"
        issue_number = issue.number
        hint_texts = _extract_hints(pull, repo, issue_number)
        hint_text = "\n".join(hint_texts)
        all_hint_texts.append(hint_text)
    return text, "\n".join(all_hint_texts) if all_hint_texts else ""


def _extract_hints(pull: dict, repo: Repo, issue_number: int) -> list[str]:
    """
    Extract hints from comments associated with a pull request (before first commit)

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
        issue_number (int): issue number
    Return:
        hints (list): list of hints
    """
    # Get all commits in PR
    commits = repo.get_all_loop(
        repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
    )
    commits = list(commits)
    if len(commits) == 0:
        # If there are no comments, return no hints
        return []
    # Get time of first commit in PR
    commit_time = commits[0].commit.author.date  # str
    commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))
    # Get all comments in PR
    all_comments = repo.get_all_loop(
        repo.api.issues.list_comments, issue_number=issue_number, quiet=True
    )
    all_comments = list(all_comments)
    # Iterate through all comments, only keep comments created before first commit
    comments = list()
    for comment in all_comments:
        comment_time = time.mktime(
            time.strptime(comment.updated_at, "%Y-%m-%dT%H:%M:%SZ")
        )  # use updated_at instead of created_at
        if comment_time < commit_time:
            comments.append(comment)
        else:
            break
        # only include information available before the first commit was created
    # Keep text from comments
    comments = [comment.body for comment in comments]
    return comments


def send_request_with_rate_limit_handling(url, headers=None, params=None, timeout: int = 30):
    """GET with bounded retries on rate-limit and transient errors.

    Raises:
        PatchFetchError: when MAX_HTTP_RETRIES is exhausted.
        requests.HTTPError: on non-rate-limit HTTP errors (4xx other than 403/429, 5xx).
    """
    backoff = 60  # secondary-rate-limit exponential backoff
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_HTTP_RETRIES):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            wait = min(60, 5 * (2 ** attempt))
            logger.warning(f"Network error fetching {url}: {e}; retry in {wait}s")
            time.sleep(wait)
            continue

        if response.status_code in (200, 201):
            return response.text

        if response.status_code in (403, 429):
            error = (response.text or "").lower()
            retry_after = response.headers.get("retry-after")
            remaining = response.headers.get("x-ratelimit-remaining")
            reset = response.headers.get("x-ratelimit-reset")

            if retry_after:
                sleep_for = min(int(retry_after), RATE_LIMIT_SLEEP_SECONDS)
            elif remaining == "0" and reset:
                sleep_for = max(0, min(int(reset) - int(time.time()), RATE_LIMIT_SLEEP_SECONDS))
            elif "secondary rate limit" in error:
                sleep_for = backoff
                backoff = min(backoff * 2, RATE_LIMIT_SLEEP_SECONDS)
            else:
                sleep_for = 60
            logger.info(
                f"Rate limited on {url} (status {response.status_code}, "
                f"attempt {attempt + 1}/{MAX_HTTP_RETRIES}); sleeping {sleep_for}s"
            )
            time.sleep(sleep_for)
            last_exc = requests.HTTPError(f"{response.status_code} on {url}")
            continue

        # Non-recoverable HTTP error
        response.raise_for_status()

    raise PatchFetchError(
        f"Failed to fetch {url} after {MAX_HTTP_RETRIES} retries: {last_exc}"
    )


def extract_patches(pull: dict, repo: Repo) -> tuple[str, str]:
    """
    Get patch and test patch from PR

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        patch_change_str (str): gold patch
        patch_test_str (str): test patch
    """

    headers = {
        "Accept": "application/vnd.github.v3.diff",  # This is needed since diff_url is not crawlable.
        "Authorization": f"Bearer {repo.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        patch = send_request_with_rate_limit_handling(pull["url"], headers=headers)
    except (PatchFetchError, requests.exceptions.RequestException, requests.exceptions.HTTPError) as e:
        # Surface the failure to the DLQ so it can be retried/triaged later,
        # then return None sentinels so the caller can distinguish 'fetch
        # failed' from 'PR genuinely has empty patch'.
        logger.error(f"Patch fetch failed for {pull.get('url')}: {e}")
        write_to_dlq(
            "patch_fetch_failures.jsonl",
            {
                "pull_url": pull.get("url"),
                "pull_number": pull.get("number"),
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        return None, None

    patch_test = ""
    patch_fix = ""
    for hunk in PatchSet(patch):
        if any(
            test_word in hunk.path for test_word in ["test", "tests", "e2e", "testing"]
        ):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test


### MARK: Repo Specific Parsing Functions ###
def extract_problem_statement_and_hints_django(
    pull: dict, repo: Repo
) -> tuple[str, list[str]]:
    """
    Get problem statement and hints from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    text = ""
    all_hints_text = list()
    for issue_number in pull["resolved_issues"]:
        url = f"https://code.djangoproject.com/ticket/{issue_number}"
        resp = requests.get(url)
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")

        # Get problem statement (title + body)
        issue_desc = soup.find("div", {"id": "ticket"})
        title = issue_desc.find("h1", class_="searchable").get_text()
        title = re.sub(r"\s+", " ", title).strip()
        body = issue_desc.find("div", class_="description").get_text()
        body = re.sub(r"\n+", "\n", body)
        body = re.sub(r"    ", "\t", body)
        body = re.sub(r"[ ]{2,}", " ", body).strip()
        text += f"{title}\n{body}\n"

        # Get time of first commit in PR
        commits = repo.get_all_loop(
            repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
        )
        commits = list(commits)
        if len(commits) == 0:
            continue
        commit_time = commits[0].commit.author.date
        commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))

        # Get all comments before first commit
        comments_html = soup.find("div", {"id": "changelog"})
        div_blocks = comments_html.find_all("div", class_="change")
        # Loop through each div block
        for div_block in div_blocks:
            # Find the comment text and timestamp
            comment_resp = div_block.find("div", class_="comment")
            timestamp_resp = div_block.find("a", class_="timeline")
            if comment_resp is None or timestamp_resp is None:
                continue

            comment_text = re.sub(r"\s+", " ", comment_resp.text).strip()
            timestamp = timestamp_resp["title"]
            if timestamp.startswith("See timeline at "):
                timestamp = timestamp[len("See timeline at ") :]
            if "/" in timestamp:
                timestamp = time.mktime(time.strptime(timestamp, "%m/%d/%y %H:%M:%S"))
            elif "," in timestamp:
                timestamp = time.mktime(
                    time.strptime(timestamp, "%b %d, %Y, %I:%M:%S %p")
                )
            else:
                raise ValueError(f"Timestamp format not recognized: {timestamp}")

            # Append the comment and timestamp as a tuple to the comments list
            if timestamp < commit_time:
                all_hints_text.append((comment_text, timestamp))

    return text, all_hints_text
