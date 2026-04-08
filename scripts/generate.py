#!/usr/bin/env python3
"""
Generate daily work dashboard data by fetching from Jira, GitHub, and Slack APIs.
Writes a JSON snapshot and prunes old data files.
"""

import base64
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# Constants
JIRA_BASE_URL = "https://gusto.atlassian.net"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
SLACK_BASE_URL = "https://slack.com/api"
GITHUB_USERNAME = "tchiu21"
GITHUB_ORG = "Gusto"
GITHUB_REPO = "app"
SLACK_CHANNELS = [
    "#retirement-compliance-filings-help",
    "#retirement-compliance",
    "#retirement-compliance-lobby",
    "#retirement-apa-support",
]
DATA_DIR = Path("data")
RETENTION_WORKDAYS = 14


def log(message: str) -> None:
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def get_workday_ago(days: int) -> datetime:
    """Calculate date N workdays ago from today."""
    current = datetime.now()
    workdays_counted = 0

    while workdays_counted < days:
        current -= timedelta(days=1)
        if current.weekday() < 5:  # Monday=0, Friday=4
            workdays_counted += 1

    return current


def is_workday(date: datetime) -> bool:
    """Check if a date is a workday (Monday-Friday)."""
    return date.weekday() < 5


def fetch_jira_issues() -> Dict[str, List[Dict[str, Any]]]:
    """Fetch Jira issues and categorize them."""
    log("Fetching Jira issues...")

    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")

    if not email or not token:
        log("WARNING: JIRA_EMAIL or JIRA_API_TOKEN not set, skipping Jira")
        return {"done": [], "in_progress": [], "up_next": []}

    auth_string = f"{email}:{token}"
    auth_bytes = base64.b64encode(auth_string.encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_bytes}",
        "Content-Type": "application/json",
    }

    done = []
    in_progress = []
    up_next = []

    try:
        # Query 1: Active and recently completed issues
        jql_active = (
            'project = RETIRE AND assignee = currentUser() '
            'AND status in ("In Progress", "In Review", "Done") '
            'ORDER BY updated DESC'
        )

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/search",
            headers=headers,
            params={"jql": jql_active, "maxResults": 50},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        two_workdays_ago = get_workday_ago(2)

        for issue in data.get("issues", []):
            key = issue["key"]
            fields = issue["fields"]
            summary = fields.get("summary", "")

            # Get description (first 200 chars, plaintext)
            description = ""
            desc_field = fields.get("description")
            if desc_field:
                # Jira description is in ADF (Atlassian Document Format)
                # Extract plain text from content nodes
                description = extract_plain_text_from_adf(desc_field)[:200]

            url = f"{JIRA_BASE_URL}/browse/{key}"
            status = fields.get("status", {}).get("name", "")
            updated_str = fields.get("updated", "")

            item = {
                "source": "jira",
                "key": key,
                "summary": summary,
                "description": description,
                "url": url,
            }

            # Categorize
            if status == "Done":
                # Check if updated in last 2 workdays
                if updated_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if updated_dt >= two_workdays_ago:
                            done.append(item)
                    except Exception as e:
                        log(f"WARNING: Failed to parse updated date for {key}: {e}")
            elif status in ("In Progress", "In Review"):
                in_progress.append(item)

        log(f"  Found {len(done)} done, {len(in_progress)} in progress")

        # Query 2: Backlog items
        jql_backlog = (
            'project = RETIRE AND assignee = currentUser() '
            'AND status in ("To Do", "Backlog", "Open") '
            'ORDER BY priority ASC'
        )

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/search",
            headers=headers,
            params={"jql": jql_backlog, "maxResults": 5},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        for issue in data.get("issues", []):
            key = issue["key"]
            fields = issue["fields"]
            summary = fields.get("summary", "")

            description = ""
            desc_field = fields.get("description")
            if desc_field:
                description = extract_plain_text_from_adf(desc_field)[:200]

            url = f"{JIRA_BASE_URL}/browse/{key}"

            up_next.append({
                "source": "jira",
                "key": key,
                "summary": summary,
                "description": description,
                "url": url,
            })

        log(f"  Found {len(up_next)} backlog items (up next)")

    except Exception as e:
        log(f"WARNING: Failed to fetch Jira issues: {e}")

    return {"done": done, "in_progress": in_progress, "up_next": up_next}


def extract_plain_text_from_adf(adf: Dict[str, Any]) -> str:
    """Extract plain text from Atlassian Document Format."""
    text_parts = []

    def extract_text(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            if "content" in node:
                for child in node["content"]:
                    extract_text(child)
        elif isinstance(node, list):
            for item in node:
                extract_text(item)

    extract_text(adf)
    return " ".join(text_parts).strip()


def fetch_github_prs() -> Dict[str, List[Dict[str, Any]]]:
    """Fetch GitHub PRs and categorize them."""
    log("Fetching GitHub PRs...")

    token = os.environ.get("GITHUB_TOKEN")

    if not token:
        log("WARNING: GITHUB_TOKEN not set, skipping GitHub")
        return {"done": [], "in_progress": [], "up_next": []}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    done = []
    in_progress = []
    up_next = []

    try:
        two_days_ago = datetime.now() - timedelta(days=2)
        two_days_ago_iso = two_days_ago.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Query 1: PRs authored by user
        query_authored = """
        query($org: String!, $repo: String!, $author: String!, $since: DateTime!) {
          repository(owner: $org, name: $repo) {
            pullRequests(first: 50, author: $author, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                body
                url
                state
                mergedAt
                createdAt
                updatedAt
              }
            }
          }
        }
        """

        response = requests.post(
            GITHUB_GRAPHQL_URL,
            headers=headers,
            json={
                "query": query_authored,
                "variables": {
                    "org": GITHUB_ORG,
                    "repo": GITHUB_REPO,
                    "author": GITHUB_USERNAME,
                    "since": two_days_ago_iso,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            log(f"WARNING: GitHub GraphQL errors: {data['errors']}")

        prs = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])

        for pr in prs:
            number = pr["number"]
            title = pr["title"]
            body = pr.get("body", "")
            url = pr["url"]
            state = pr["state"]
            merged_at = pr.get("mergedAt")

            # Create description (title + first 200 chars of body)
            description = title
            if body:
                body_preview = body[:200]
                description = f"{title} - {body_preview}"

            item = {
                "source": "github",
                "key": f"PR #{number}",
                "summary": title,
                "description": description[:200],
                "url": url,
            }

            # Categorize
            if state == "MERGED" and merged_at:
                try:
                    merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
                    if merged_dt >= two_days_ago:
                        done.append(item)
                except Exception as e:
                    log(f"WARNING: Failed to parse merged date for PR #{number}: {e}")
            elif state == "OPEN":
                in_progress.append(item)

        log(f"  Found {len(done)} merged PRs, {len(in_progress)} open PRs")

        # Query 2: PRs with review requested
        query_review = """
        query($org: String!, $repo: String!) {
          repository(owner: $org, name: $repo) {
            pullRequests(first: 50, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                body
                url
                reviewRequests(first: 10) {
                  nodes {
                    requestedReviewer {
                      ... on User {
                        login
                      }
                      ... on Team {
                        slug
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        response = requests.post(
            GITHUB_GRAPHQL_URL,
            headers=headers,
            json={
                "query": query_review,
                "variables": {
                    "org": GITHUB_ORG,
                    "repo": GITHUB_REPO,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            log(f"WARNING: GitHub GraphQL errors: {data['errors']}")

        prs = data.get("data", {}).get("repository", {}).get("pullRequests", {}).get("nodes", [])

        for pr in prs:
            number = pr["number"]
            title = pr["title"]
            body = pr.get("body", "")
            url = pr["url"]

            review_requests = pr.get("reviewRequests", {}).get("nodes", [])

            # Check if review requested from user or team
            review_requested = False
            for req in review_requests:
                reviewer = req.get("requestedReviewer", {})
                if reviewer.get("login") == GITHUB_USERNAME:
                    review_requested = True
                    break
                if reviewer.get("slug") == "retirement-compliance":
                    review_requested = True
                    break

            if review_requested:
                description = title
                if body:
                    body_preview = body[:200]
                    description = f"{title} - {body_preview}"

                up_next.append({
                    "source": "github",
                    "key": f"PR #{number}",
                    "summary": title,
                    "description": description[:200],
                    "url": url,
                })

        log(f"  Found {len(up_next)} PRs needing review")

    except Exception as e:
        log(f"WARNING: Failed to fetch GitHub PRs: {e}")

    return {"done": done, "in_progress": in_progress, "up_next": up_next}


def fetch_slack_attention() -> List[Dict[str, Any]]:
    """Fetch Slack messages needing attention."""
    log("Fetching Slack messages...")

    token = os.environ.get("SLACK_BOT_TOKEN")

    if not token:
        log("WARNING: SLACK_BOT_TOKEN not set, skipping Slack")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    attention_items = []

    try:
        # Get bot user ID
        response = requests.get(
            f"{SLACK_BASE_URL}/auth.test",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        bot_user_id = response.json().get("user_id")

        # Search for mentions in last 24 hours
        one_day_ago = datetime.now() - timedelta(days=1)
        one_day_ago_ts = int(one_day_ago.timestamp())

        response = requests.get(
            f"{SLACK_BASE_URL}/search.messages",
            headers=headers,
            params={
                "query": f"<@{bot_user_id}>",
                "sort": "timestamp",
                "sort_dir": "desc",
                "count": 20,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            log(f"WARNING: Slack search failed: {data.get('error')}")
            return attention_items

        mentions = data.get("messages", {}).get("matches", [])
        log(f"  Found {len(mentions)} mentions in last 24h")

        for mention in mentions:
            channel_id = mention.get("channel", {}).get("id")
            channel_name = mention.get("channel", {}).get("name")
            text = mention.get("text", "")
            ts = mention.get("ts", "")

            # Calculate age
            try:
                msg_time = datetime.fromtimestamp(float(ts))
                age_delta = datetime.now() - msg_time
                hours = int(age_delta.total_seconds() / 3600)
                age = f"{hours}h"
            except Exception:
                age = "unknown"

            url = f"https://gusto.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

            attention_items.append({
                "channel": f"#{channel_name}",
                "summary": f"Mention in #{channel_name}",
                "description": text[:200],
                "age": age,
                "url": url,
            })

        # Check specific channels for @retirement-compliance-devs mentions without team reply
        channel_ids = get_channel_ids(headers, SLACK_CHANNELS)

        for channel_name, channel_id in channel_ids.items():
            if not channel_id:
                continue

            # Get messages from last 24h
            response = requests.get(
                f"{SLACK_BASE_URL}/conversations.history",
                headers=headers,
                params={
                    "channel": channel_id,
                    "oldest": str(one_day_ago_ts),
                    "limit": 100,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                log(f"WARNING: Failed to fetch history for {channel_name}: {data.get('error')}")
                continue

            messages = data.get("messages", [])

            for msg in messages:
                text = msg.get("text", "")
                ts = msg.get("ts", "")

                # Check if message mentions @retirement-compliance-devs
                if "<!subteam^" not in text and "@retirement-compliance-devs" not in text:
                    continue

                # Check message age
                try:
                    msg_time = datetime.fromtimestamp(float(ts))
                    age_delta = datetime.now() - msg_time
                    hours = age_delta.total_seconds() / 3600

                    if hours < 2:
                        continue  # Too recent

                    age = f"{int(hours)}h"
                except Exception:
                    age = "unknown"

                # Check for team replies
                has_team_reply = check_for_team_reply(headers, channel_id, ts)

                if not has_team_reply:
                    url = f"https://gusto.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

                    attention_items.append({
                        "channel": channel_name,
                        "summary": f"@devs mention in {channel_name} - no reply",
                        "description": text[:200],
                        "age": age,
                        "url": url,
                    })

        log(f"  Found {len(attention_items)} total items needing attention")

    except Exception as e:
        log(f"WARNING: Failed to fetch Slack messages: {e}")

    return attention_items


def get_channel_ids(headers: Dict[str, str], channel_names: List[str]) -> Dict[str, Optional[str]]:
    """Get channel IDs for given channel names."""
    result = {name: None for name in channel_names}

    try:
        response = requests.get(
            f"{SLACK_BASE_URL}/conversations.list",
            headers=headers,
            params={"types": "public_channel,private_channel", "limit": 1000},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            log(f"WARNING: Failed to list channels: {data.get('error')}")
            return result

        channels = data.get("channels", [])

        for channel in channels:
            name = f"#{channel['name']}"
            if name in channel_names:
                result[name] = channel["id"]

    except Exception as e:
        log(f"WARNING: Failed to get channel IDs: {e}")

    return result


def check_for_team_reply(headers: Dict[str, str], channel_id: str, thread_ts: str) -> bool:
    """Check if a thread has a reply from a team member."""
    try:
        # Get thread replies
        response = requests.get(
            f"{SLACK_BASE_URL}/conversations.replies",
            headers=headers,
            params={"channel": channel_id, "ts": thread_ts, "limit": 100},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            return False

        messages = data.get("messages", [])

        # Get retirement-compliance-devs user group members
        team_members = get_team_members(headers)

        # Check if any reply is from a team member
        for msg in messages[1:]:  # Skip original message
            user_id = msg.get("user")
            if user_id in team_members:
                return True

    except Exception as e:
        log(f"WARNING: Failed to check thread replies: {e}")

    return False


def get_team_members(headers: Dict[str, str]) -> set:
    """Get members of retirement-compliance-devs user group."""
    try:
        response = requests.get(
            f"{SLACK_BASE_URL}/usergroups.list",
            headers=headers,
            params={"include_users": True},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            return set()

        for group in data.get("usergroups", []):
            if group.get("handle") == "retirement-compliance-devs":
                return set(group.get("users", []))

    except Exception as e:
        log(f"WARNING: Failed to get team members: {e}")

    return set()


def write_json_output(data: Dict[str, Any]) -> None:
    """Write JSON output to data directory."""
    log("Writing JSON output...")

    # Ensure data directory exists
    DATA_DIR.mkdir(exist_ok=True)

    # Get current date
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")

    # Add metadata
    data["date"] = date_str
    data["generated_at"] = today.isoformat()

    # Write file
    output_path = DATA_DIR / f"{date_str}.json"
    with output_path.open("w") as f:
        json.dump(data, f, indent=2)

    log(f"  Wrote {output_path}")


def prune_old_data() -> None:
    """Delete JSON files older than retention period."""
    log("Pruning old data files...")

    if not DATA_DIR.exists():
        return

    cutoff_date = get_workday_ago(RETENTION_WORKDAYS)
    deleted_count = 0

    for file_path in DATA_DIR.glob("*.json"):
        try:
            # Parse date from filename
            date_str = file_path.stem  # e.g., "2026-04-08"
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date < cutoff_date:
                file_path.unlink()
                deleted_count += 1
                log(f"  Deleted {file_path.name}")

        except Exception as e:
            log(f"WARNING: Failed to process {file_path.name}: {e}")

    log(f"  Deleted {deleted_count} old file(s)")


def main() -> None:
    """Main entry point."""
    log("=== Starting work dashboard data generation ===")

    # Fetch data from all sources
    jira_data = fetch_jira_issues()
    github_data = fetch_github_prs()
    slack_attention = fetch_slack_attention()

    # Combine data
    combined_data = {
        "done": jira_data["done"] + github_data["done"],
        "in_progress": jira_data["in_progress"] + github_data["in_progress"],
        "up_next": jira_data["up_next"] + github_data["up_next"],
        "slack_attention": slack_attention,
    }

    # Write output
    write_json_output(combined_data)

    # Prune old data
    prune_old_data()

    # Print summary
    log("=== Summary ===")
    log(f"  Done: {len(combined_data['done'])} items")
    log(f"  In Progress: {len(combined_data['in_progress'])} items")
    log(f"  Up Next: {len(combined_data['up_next'])} items")
    log(f"  Slack Attention: {len(combined_data['slack_attention'])} items")
    log("=== Complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)
