"""GitHub skill market integration for downloading skills by URL."""

import asyncio
import base64
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# Constants (no config dependency needed)
# ---------------------------------------------------------------------------

GITHUB_DEFAULT_REF = "main"
GITHUB_CONTENTS_MAX_FILES = 200
GITHUB_DOWNLOAD_CONCURRENCY = 10


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubMarketError(Exception):
    """Raised on GitHub market operation failures."""

    def __init__(self, message: str, detail: str = "", suggested_action: str = ""):
        self.message = message
        self.detail = detail
        self.suggested_action = suggested_action
        super().__init__(f"{message}: {detail}" if detail else message)


class TooManyFilesException(Exception):
    """Raised when directory has too many files for Contents API."""


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def _get_github_token() -> Optional[str]:
    """Return GitHub token if available from environment."""
    for var in ["GITHUB_PAT", "GH_PAT", "GITHUB_TOKEN", "GH_TOKEN"]:
        token = os.environ.get(var)
        if token:
            return token
    return None


def _parse_github_url(url: str) -> tuple[str, str, Optional[str], str]:
    """Parse GitHub URL into owner, repo, ref, subpath."""
    parsed = urlparse(url.strip())
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise GitHubMarketError(
            message="Invalid GitHub URL",
            detail="URL must be a github.com repository or directory URL",
            suggested_action="Provide a valid GitHub URL",
        )

    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise GitHubMarketError(
            message="Invalid GitHub URL",
            detail="GitHub URL must include owner and repository",
            suggested_action="Provide a full repository URL",
        )

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    ref = None
    subpath = ""

    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        ref = parts[3]
        if len(parts) > 4:
            subpath = "/".join(parts[4:])
    elif len(parts) > 2:
        subpath = "/".join(parts[2:])

    return owner, repo, ref, subpath


def _build_headers(token: Optional[str]) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


async def _get_default_branch(owner: str, repo: str, token: Optional[str]) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_build_headers(token))
    if resp.status_code == 404:
        raise GitHubMarketError(
            message="Repository not found",
            detail="The GitHub repository does not exist or is inaccessible",
            suggested_action="Check the repository URL and access permissions",
        )
    if resp.status_code in {401, 403}:
        raise GitHubMarketError(
            message="GitHub access denied",
            detail="Repository is private or requires authentication",
            suggested_action="Provide a valid GitHub token",
        )
    if not resp.is_success:
        raise GitHubMarketError(
            message="Failed to access repository",
            detail=f"GitHub API error: {resp.status_code}",
            suggested_action="Try again later or verify the URL",
        )
    data = resp.json()
    return data.get("default_branch", GITHUB_DEFAULT_REF)


async def _fetch_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: Optional[str],
) -> Optional[dict]:
    base_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
    url = f"{base_url}/{path}" if path else base_url
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_build_headers(token), params={"ref": ref})

    if resp.status_code == 404:
        return None
    if resp.status_code in {401, 403}:
        raise GitHubMarketError(
            message="GitHub access denied",
            detail="Repository is private or requires authentication",
            suggested_action="Provide a valid GitHub token",
        )
    if not resp.is_success:
        raise GitHubMarketError(
            message="Failed to access repository",
            detail=f"GitHub API error: {resp.status_code}",
            suggested_action="Try again later or verify the URL",
        )
    return resp.json()


async def _download_tarball(owner: str, repo: str, ref: str, token: Optional[str]) -> bytes:
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref}"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(url, headers=_build_headers(token))
    if resp.status_code in {401, 403}:
        raise GitHubMarketError(
            message="GitHub access denied",
            detail="Repository is private or requires authentication",
            suggested_action="Provide a valid GitHub token",
        )
    if resp.status_code == 404:
        raise GitHubMarketError(
            message="Repository or ref not found",
            detail="The repository or branch/tag does not exist",
            suggested_action="Check the URL or branch name",
        )
    if not resp.is_success:
        raise GitHubMarketError(
            message="Failed to download repository",
            detail=f"GitHub API error: {resp.status_code}",
            suggested_action="Try again later or verify the URL",
        )
    return resp.content


# ---------------------------------------------------------------------------
# Recursive directory listing & download via Contents API
# ---------------------------------------------------------------------------


async def _list_directory_recursive(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: Optional[str],
    max_files: int,
    _current_count: int = 0,
) -> list[dict]:
    """Recursively list all files in a directory using Contents API."""
    contents = await _fetch_contents(owner, repo, path, ref, token)

    if contents is None:
        logger.debug("[list_recursive] Contents API returned None for path={}", path)
        return []

    if isinstance(contents, dict):
        if contents.get("type") == "file":
            return [{"path": contents["path"], "sha": contents.get("sha"), "size": contents.get("size", 0)}]
        return []

    logger.info(
        "[list_recursive] Contents API for path='{}' returned {} entries",
        path,
        len(contents),
    )

    files: list[dict] = []
    dirs: list[str] = []

    for item in contents:
        item_type = item.get("type")
        if item_type == "file":
            files.append({
                "path": item["path"],
                "sha": item.get("sha"),
                "size": item.get("size", 0),
            })
            if len(files) + _current_count > max_files:
                raise TooManyFilesException(f"Directory contains more than {max_files} files")
        elif item_type == "dir":
            dirs.append(item["path"])

    for dir_path in dirs:
        sub_files = await _list_directory_recursive(
            owner, repo, dir_path, ref, token, max_files,
            _current_count=len(files) + _current_count,
        )
        files.extend(sub_files)
        if len(files) + _current_count > max_files:
            raise TooManyFilesException(f"Directory contains more than {max_files} files")

    return files


async def _download_file_raw(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: Optional[str],
) -> bytes:
    """Download a single file via raw.githubusercontent.com with Contents API fallback."""
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(raw_url, headers=headers)

        if resp.is_success:
            return resp.content

        if resp.status_code in {401, 403, 404}:
            logger.debug("Raw URL failed for {}, falling back to Contents API", path)
            content_data = await _fetch_contents(owner, repo, path, ref, token)
            if content_data and isinstance(content_data, dict) and content_data.get("type") == "file":
                encoding = content_data.get("encoding")
                content = content_data.get("content")
                if encoding == "base64" and content:
                    return base64.b64decode(content)
            raise GitHubMarketError(
                message="Failed to download file",
                detail=f"Could not download {path}",
                suggested_action="Check file exists and permissions",
            )

        raise GitHubMarketError(
            message="Failed to download file",
            detail=f"GitHub returned {resp.status_code} for {path}",
            suggested_action="Try again later or verify the URL",
        )


async def _download_directory_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: Optional[str],
    max_files: int,
) -> dict[str, bytes]:
    """Download all files in a directory using Contents API."""
    files = await _list_directory_recursive(owner, repo, path, ref, token, max_files)

    if not files:
        raise GitHubMarketError(
            message="Empty directory",
            detail=f"No files found in {path or 'repository root'}",
            suggested_action="Check the directory path",
        )

    logger.info("Downloading {} files from {}/{}/{} via Contents API", len(files), owner, repo, path)

    semaphore = asyncio.Semaphore(GITHUB_DOWNLOAD_CONCURRENCY)

    async def download_one(file_info: dict) -> tuple[str, bytes]:
        async with semaphore:
            content = await _download_file_raw(owner, repo, file_info["path"], ref, token)
            rel_path = file_info["path"]
            if path:
                rel_path = file_info["path"][len(path):].lstrip("/")
            return rel_path, content

    results = await asyncio.gather(*[download_one(f) for f in files])
    return dict(results)


def _create_zip_from_contents(files: dict[str, bytes]) -> bytes:
    """Create a ZIP archive from file contents dict."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Tarball fallback
# ---------------------------------------------------------------------------


def _safe_extract_tar(tar: tarfile.TarFile, target_dir: Path) -> None:
    target_dir_resolved = target_dir.resolve()
    for member in tar.getmembers():
        member_path = (target_dir / member.name).resolve()
        if os.path.commonpath([str(target_dir_resolved), str(member_path)]) != str(target_dir_resolved):
            raise GitHubMarketError(
                message="Invalid repository archive",
                detail="Archive contains unsafe paths",
                suggested_action="Use a different repository or ref",
            )
    tar.extractall(target_dir)


def _zip_directory(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in directory.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(directory).as_posix()
                zf.write(file_path, arcname)
    return buffer.getvalue()


async def _download_tarball_and_extract_subpath(
    owner: str,
    repo: str,
    ref: str,
    token: Optional[str],
    subpath: str,
) -> bytes:
    """Download tarball and extract only the specified subpath as ZIP."""
    import tempfile

    logger.info("Downloading tarball for {}/{} (fallback for large directory)", owner, repo)

    tarball = await _download_tarball(owner, repo, ref, token)

    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            _safe_extract_tar(tf, tmp_path)

            root_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
            if len(root_dirs) != 1:
                raise GitHubMarketError(
                    message="Invalid repository archive",
                    detail="Could not determine repository root directory",
                    suggested_action="Try again with a different repository",
                )
            repo_root = root_dirs[0]

            target_dir = repo_root
            if subpath:
                target_dir = repo_root / subpath

            if not target_dir.exists():
                raise GitHubMarketError(
                    message="Skill path not found",
                    detail=f"Path '{subpath}' does not exist in repository",
                    suggested_action="Check the URL and ensure the path exists",
                )

            if target_dir.is_file():
                if target_dir.name == "SKILL.md":
                    target_dir = target_dir.parent
                else:
                    raise GitHubMarketError(
                        message="Invalid skill path",
                        detail="URL must point to a directory containing SKILL.md",
                        suggested_action="Provide a directory URL or SKILL.md URL",
                    )

            return _zip_directory(target_dir)


async def _download_subpath_as_zip(
    owner: str,
    repo: str,
    subpath: str,
    ref: str,
    token: Optional[str],
) -> bytes:
    """Download a repository subpath as ZIP using optimal strategy.

    Strategy:
    1. Try Contents API for small directories (<= max_files)
    2. Fall back to tarball for large directories or API failures
    """
    max_files = GITHUB_CONTENTS_MAX_FILES

    try:
        files = await _download_directory_contents(owner, repo, subpath, ref, token, max_files)
        logger.info("Successfully downloaded via Contents API ({} files)", len(files))
        return _create_zip_from_contents(files)
    except TooManyFilesException:
        logger.info("Directory exceeds {} files, falling back to tarball", max_files)
        return await _download_tarball_and_extract_subpath(owner, repo, ref, token, subpath)
    except GitHubMarketError as e:
        if "Empty directory" in str(e.detail):
            raise
        logger.warning("Contents API failed ({}), trying tarball fallback", e.detail)
        return await _download_tarball_and_extract_subpath(owner, repo, ref, token, subpath)


# ---------------------------------------------------------------------------
# Marketplace / URL helpers
# ---------------------------------------------------------------------------


def _decode_github_content(data: dict) -> str:
    encoding = data.get("encoding")
    content = data.get("content")
    if encoding != "base64" or not content:
        raise GitHubMarketError(
            message="Invalid marketplace.json",
            detail="Unsupported file encoding or empty content",
            suggested_action="Ensure marketplace.json is a valid UTF-8 JSON file",
        )
    return base64.b64decode(content).decode("utf-8")


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _join_path(*parts: str) -> str:
    return "/".join([p.strip("/") for p in parts if p])


def _build_github_url(owner: str, repo: str, ref: str, path: str, is_file: bool) -> str:
    kind = "blob" if is_file else "tree"
    safe_path = path.strip("/")
    if safe_path:
        return f"https://github.com/{owner}/{repo}/{kind}/{ref}/{safe_path}"
    return f"https://github.com/{owner}/{repo}"


def _normalize_subpath(subpath: str) -> str:
    normalized = subpath.strip("/")
    if normalized.endswith("SKILL.md"):
        normalized = str(Path(normalized).parent)
    if normalized == ".":
        normalized = ""
    if normalized:
        parts = Path(normalized).parts
        if any(part == ".." for part in parts):
            raise GitHubMarketError(
                message="Invalid GitHub URL path",
                detail="Path traversal is not allowed",
                suggested_action="Provide a valid repository path",
            )
    return normalized


def _parse_marketplace_items(
    data: object,
    owner: str,
    repo: str,
    ref: str,
    base_path: str,
) -> list[dict]:
    """Parse marketplace.json and extract skill items."""
    if not isinstance(data, (dict, list)):
        raise GitHubMarketError(
            message="Invalid marketplace.json",
            detail="Unsupported marketplace.json format",
            suggested_action="Ensure marketplace.json is valid JSON",
        )

    results: list[dict] = []

    marketplace_metadata = {}
    if isinstance(data, dict):
        marketplace_metadata = {
            "version": data.get("metadata", {}).get("version") if isinstance(data.get("metadata"), dict) else None,
            "author": data.get("owner", {}).get("name") if isinstance(data.get("owner"), dict) else None,
        }

    # New format: plugins array with skill paths
    if isinstance(data, dict) and isinstance(data.get("plugins"), list):
        for plugin in data["plugins"]:
            if not isinstance(plugin, dict):
                continue
            plugin_skills = plugin.get("skills", [])
            if not isinstance(plugin_skills, list):
                continue

            for skill_entry in plugin_skills:
                if isinstance(skill_entry, str):
                    skill_path = _strip_relative_prefix(skill_entry)
                    full_path = _join_path(base_path, skill_path)
                    skill_name = Path(skill_path).name
                    url = _build_github_url(owner, repo, ref, full_path, is_file=False)
                    results.append({
                        "name": skill_name,
                        "description": None,
                        "version": marketplace_metadata.get("version"),
                        "author": marketplace_metadata.get("author"),
                        "github_url": url,
                    })
                elif isinstance(skill_entry, dict):
                    name = skill_entry.get("name") or skill_entry.get("id")
                    path = skill_entry.get("path") or skill_entry.get("directory")
                    url = skill_entry.get("github_url") or skill_entry.get("url")

                    if not url and path:
                        skill_path = _strip_relative_prefix(path)
                        full_path = _join_path(base_path, skill_path)
                        url = _build_github_url(owner, repo, ref, full_path, is_file=False)

                    if url:
                        results.append({
                            "name": name or Path(url).name,
                            "description": skill_entry.get("description"),
                            "version": skill_entry.get("version") or marketplace_metadata.get("version"),
                            "author": skill_entry.get("author") or marketplace_metadata.get("author"),
                            "github_url": url,
                        })

        if results:
            return results

    # Legacy format: direct skills/items array
    items: list = []
    if isinstance(data, dict):
        if isinstance(data.get("skills"), list):
            items = data["skills"]
        elif isinstance(data.get("items"), list):
            items = data["items"]
    elif isinstance(data, list):
        items = data

    for item in items:
        if isinstance(item, str):
            skill_path = _strip_relative_prefix(item)
            full_path = _join_path(base_path, skill_path)
            skill_name = Path(skill_path).name
            url = _build_github_url(owner, repo, ref, full_path, is_file=False)
            results.append({
                "name": skill_name,
                "description": None,
                "version": marketplace_metadata.get("version"),
                "author": marketplace_metadata.get("author"),
                "github_url": url,
            })
        elif isinstance(item, dict):
            name = item.get("name") or item.get("id") or item.get("title")
            description = item.get("description")
            version = item.get("version") or marketplace_metadata.get("version")
            author = item.get("author") or item.get("publisher") or marketplace_metadata.get("author")
            url = item.get("github_url") or item.get("url")
            path = item.get("path") or item.get("directory") or item.get("folder") or item.get("skill_path")

            if not url and path:
                skill_path = _strip_relative_prefix(path)
                full_path = _join_path(base_path, skill_path)
                url = _build_github_url(owner, repo, ref, full_path, is_file=False)

            if not url and name:
                full_path = _join_path(base_path, "skills", name)
                url = _build_github_url(owner, repo, ref, full_path, is_file=False)

            if url:
                results.append({
                    "name": name or Path(url).name,
                    "description": description,
                    "version": version,
                    "author": author,
                    "github_url": url,
                })

    if not results:
        raise GitHubMarketError(
            message="No skills found",
            detail="Marketplace does not contain any valid skills",
            suggested_action="Check marketplace.json content",
        )

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_market_url(url: str) -> dict:
    """Resolve a GitHub URL to either a skill list or a direct install target.

    Returns:
        ``{"mode": "direct", "github_url": ...}`` or
        ``{"mode": "list", "skills": [...], "source": ...}``
    """
    owner, repo, ref, subpath = _parse_github_url(url)
    token = _get_github_token()
    ref_to_use = ref or await _get_default_branch(owner, repo, token)
    normalized_subpath = _normalize_subpath(subpath)

    # If URL explicitly points to SKILL.md, treat as direct install
    if subpath.strip("/").endswith("SKILL.md"):
        dir_url = _build_github_url(owner, repo, ref_to_use, normalized_subpath, is_file=False)
        return {"mode": "direct", "github_url": dir_url}

    # If subpath points to a directory with SKILL.md, treat as direct install
    if normalized_subpath:
        skill_md_path = _join_path(normalized_subpath, "SKILL.md")
        content = await _fetch_contents(owner, repo, skill_md_path, ref_to_use, token)
        if isinstance(content, dict) and content.get("type") == "file":
            skill_url = _build_github_url(owner, repo, ref_to_use, normalized_subpath, is_file=False)
            return {"mode": "direct", "github_url": skill_url}

    # Check for marketplace.json
    base_path = normalized_subpath
    marketplace_path = _join_path(base_path, ".claude-plugin", "marketplace.json")
    marketplace_content = await _fetch_contents(owner, repo, marketplace_path, ref_to_use, token)
    if isinstance(marketplace_content, dict) and marketplace_content.get("type") == "file":
        raw = _decode_github_content(marketplace_content)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GitHubMarketError(
                message="Invalid marketplace.json",
                detail=str(exc),
                suggested_action="Ensure marketplace.json is valid JSON",
            ) from exc
        skills = _parse_marketplace_items(data, owner, repo, ref_to_use, base_path)
        return {"mode": "list", "skills": skills, "source": "marketplace"}

    # Check for skills directory
    skills_dir_path = base_path if base_path.endswith("skills") else _join_path(base_path, "skills")
    skills_dir = await _fetch_contents(owner, repo, skills_dir_path, ref_to_use, token)
    if isinstance(skills_dir, list):
        skills: list[dict] = []
        for entry in skills_dir:
            if entry.get("type") != "dir":
                continue
            skill_path = _join_path(skills_dir_path, entry.get("name", ""))
            skill_md = _join_path(skill_path, "SKILL.md")
            md_content = await _fetch_contents(owner, repo, skill_md, ref_to_use, token)
            if isinstance(md_content, dict) and md_content.get("type") == "file":
                skills.append({
                    "name": entry.get("name", ""),
                    "description": None,
                    "version": None,
                    "author": None,
                    "github_url": _build_github_url(owner, repo, ref_to_use, skill_path, is_file=False),
                })
        if skills:
            return {"mode": "list", "skills": skills, "source": "skills_dir"}

    # Fallback: check root for SKILL.md
    if not normalized_subpath:
        root_skill_md = await _fetch_contents(owner, repo, "SKILL.md", ref_to_use, token)
        if isinstance(root_skill_md, dict) and root_skill_md.get("type") == "file":
            skill_url = _build_github_url(owner, repo, ref_to_use, "", is_file=False)
            return {"mode": "direct", "github_url": skill_url}

    raise GitHubMarketError(
        message="No skills found",
        detail="Could not find SKILL.md, marketplace.json, or skills directory",
        suggested_action="Verify the GitHub URL and repository structure",
    )


async def fetch_skill_package_from_github(url: str) -> tuple[bytes, str, str]:
    """Download a skill directory from GitHub and return (zip_bytes, skill_name, filename).

    Uses optimized download strategy:
    1. For small directories (<= max_files): Use Contents API
    2. For large directories: Fall back to tarball download
    """
    owner, repo, ref, subpath = _parse_github_url(url)
    token = _get_github_token()
    normalized_subpath = _normalize_subpath(subpath)

    logger.info(
        "[fetch_skill] url={} -> owner={}, repo={}, ref={}, normalized_subpath={}",
        url, owner, repo, ref, normalized_subpath,
    )

    ref_to_use = ref or GITHUB_DEFAULT_REF

    try:
        zip_bytes = await _download_subpath_as_zip(owner, repo, normalized_subpath, ref_to_use, token)
    except GitHubMarketError as first_error:
        if not ref:
            try:
                default_branch = await _get_default_branch(owner, repo, token)
                if default_branch != ref_to_use:
                    logger.info("Retrying with default branch: {}", default_branch)
                    zip_bytes = await _download_subpath_as_zip(
                        owner, repo, normalized_subpath, default_branch, token
                    )
                else:
                    raise first_error
            except GitHubMarketError:
                raise first_error
        else:
            raise first_error

    # Validate SKILL.md exists in the ZIP
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        logger.info("[fetch_skill] Final ZIP contains {} entries: {}", len(namelist), namelist)
        if "SKILL.md" not in namelist:
            raise GitHubMarketError(
                message="SKILL.md not found",
                detail="Target directory does not contain SKILL.md",
                suggested_action="Ensure the URL points to a valid skill directory",
            )

    skill_name = repo if not normalized_subpath else Path(normalized_subpath).name
    original_filename = f"{skill_name}.zip"

    return zip_bytes, skill_name, original_filename
