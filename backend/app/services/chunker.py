"""
Source processing and text chunking service with directory analysis + chunk tagging.
"""
import os
import re
import json
import tempfile
import subprocess
from typing import List, Optional, Dict
from urllib.parse import urlparse

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from bs4 import BeautifulSoup


class SourceProcessor:
    """Process sources and produce tagged chunks + directory metadata."""

    def __init__(self, chunk_size: int = 2000, chunk_overlap: int = 200):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n## ", "\n### ", "\n#### ", "\n", ". ", " ", ""],
        )

    # ── URL Handling ──

    async def fetch_url(self, url: str) -> str:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 LearnFlow/1.0"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        article = soup.find("article")
        text = article.get_text(separator="\n", strip=True) if article else soup.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)

    # ── GitHub Handling ──

    def _parse_gh_url(self, url: str) -> tuple:
        clean = urlparse(url)._replace(query="").geturl()
        path = urlparse(clean).path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {url}")
        return parts[0], parts[1]

    async def fetch_github_readme(self, repo_url: str) -> str:
        owner, repo = self._parse_gh_url(repo_url)
        urls = [
            f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
            f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.rst",
            f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md",
            f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.rst",
            f"https://api.github.com/repos/{owner}/{repo}/readme",
        ]
        headers = {"User-Agent": "LearnFlow/1.0", "Accept": "application/vnd.github.v3.raw"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for u in urls:
                try:
                    resp = await client.get(u, headers=headers)
                    if resp.status_code == 200:
                        return resp.text
                except Exception:
                    continue
        raise ValueError(f"Could not fetch README for {repo_url}")

    # ── Clone + Extract + Analyze ──

    def _skip_dir(self, name: str) -> bool:
        skip = {".git", ".github", "node_modules", "__pycache__", "build", "dist",
                "venv", ".venv", "env", ".ipynb_checkpoints", "site-packages",
                "bower_components", "target", "vendor", ".gradle", "coverage"}
        return name in skip or (name.startswith(".") and name not in {".", ".ci", ".devcontainer"})

    _READABLE_EXTS = {
        ".md", ".rst", ".txt", ".py", ".ipynb", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".json", ".xml", ".html", ".css", ".js",
        ".sh", ".bash", ".c", ".cpp", ".h", ".hpp", ".java",
        ".rs", ".go", ".rb", ".php", ".swift", ".tex", ".bib",
    }

    async def clone_and_extract(self, repo_url: str) -> dict:
        """
        Clone repo and return:
          text: combined content for chunking
          dir_tree: directory structure {path: {"type":"file"|"dir", "size":int}}
          readme_content: raw README text
        """
        clean_url = urlparse(repo_url)._replace(query="").geturl()
        dir_tree = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", clean_url, tmpdir],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise ValueError(f"Git clone failed: {result.stderr[:200]}")

            text_parts = []
            readme_text = ""

            for root, dirs, files in os.walk(tmpdir):
                # Filter dirs
                dirs[:] = [d for d in dirs if not self._skip_dir(d)]
                rel_dir = os.path.relpath(root, tmpdir)
                if rel_dir == ".":
                    rel_dir = ""
                for d in dirs:
                    dir_path = f"{rel_dir}/{d}" if rel_dir else d
                    dir_tree[dir_path] = {"type": "dir"}

                for fname in files:
                    ext = f".{fname.split('.')[-1].lower()}" if "." in fname else ""
                    rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
                    fpath = os.path.join(root, fname)
                    try:
                        fsize = os.path.getsize(fpath)
                    except OSError:
                        continue

                    dir_tree[rel_path] = {"type": "file", "size": fsize}

                    # Track README separately
                    if fname.lower() == "readme.md":
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                                readme_text = f.read()
                        except Exception:
                            pass

                    if ext not in self._READABLE_EXTS and fname.lower() not in {
                        "readme.md", "readme.rst", "makefile", "dockerfile",
                    }:
                        continue
                    if fsize > 500 * 1024:
                        continue

                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        if len(content.strip()) < 20:
                            continue
                        text_parts.append(f"=== {rel_path} ===\n{content}\n")
                    except (UnicodeDecodeError, OSError):
                        continue

            if not text_parts:
                raise ValueError(f"No readable content found in {repo_url}")

            return {
                "text": "\n".join(text_parts),
                "dir_tree": dir_tree,
                "readme": readme_text,
            }

    # ── Chunk with Tags ──

    def _extract_headings(self, text: str, file_path: str = "") -> List[str]:
        """Extract markdown headings from content."""
        headings = re.findall(r"^(#{1,4})\s+(.+)$", text, re.MULTILINE)
        return [h[1].strip() for h in headings[:10]]

    def _extract_topic_hints(self, text: str) -> List[str]:
        """Extract topic keywords from chunk content."""
        # Look for bold terms, code keywords, and first sentence
        hints = []
        bold = re.findall(r"\*\*(.+?)\*\*", text)
        hints.extend(b[:30] for b in bold[:5])
        # First meaningful sentence
        sentences = re.split(r'[.。!！?？\n]', text.strip())
        if sentences and len(sentences[0]) > 5:
            hints.append(sentences[0][:60])
        return hints

    def _parse_file_path_from_content(self, content: str) -> str:
        """Extract === path === from anywhere in chunk content."""
        # Try start of chunk first (most reliable)
        m = re.match(r"^=== (.+?) ===\n?", content)
        if m:
            return m.group(1)
        # Try end of previous content (=== path === comes before ## heading)
        m = re.search(r"=== (.+?) ===\n", content[:200])
        if m:
            return m.group(1)
        return ""

    def chunk_text(self, text: str, source_type: str = "url") -> List[dict]:
        """Split text into chunks with rich metadata tags.
        
        Walks through combined text line-by-line, collecting file blocks
        at === path === markers, then chunks each file independently.
        """
        result = []
        chunk_index = 0

        # Split into file blocks by iterating lines
        lines = text.split("\n")
        current_file = ""
        current_content = []

        def flush_current():
            """Process buffered content as chunks for the current file."""
            nonlocal chunk_index
            if not current_content:
                return
            content = "\n".join(current_content).strip()
            if not content:
                return
            file_chunks = self.splitter.split_text(content)
            for fc in file_chunks:
                if not fc.strip():
                    continue
                headings = self._extract_headings(fc, current_file)
                topic_hints = self._extract_topic_hints(fc)
                result.append({
                    "index": chunk_index,
                    "content": fc.strip(),
                    "tokens": len(fc) // 4,
                    "meta": {
                        "source_type": source_type,
                        "file": current_file,
                        "headings": headings,
                        "topic_hints": topic_hints,
                        "chunk_index": chunk_index,
                    },
                })
                chunk_index += 1

        for line in lines:
            # Check for file path marker
            m = re.match(r"^=== (.+?) ===$", line.strip())
            if m:
                flush_current()
                current_file = m.group(1)
                current_content = []
            else:
                current_content.append(line)

        flush_current()

        return result

    # ── README TOC Parser (Level 1) ──

    def parse_readme_toc(self, readme_text: str) -> list:
        """Extract table of contents from README."""
        toc = []
        if not readme_text:
            return toc

        lines = readme_text.split("\n")

        # Strategy 1: Look for bullet-list ToC (common in GitHub README)
        # "[text](#link)" pattern
        in_toc_section = False
        toc_markers = ["table of contents", "目录", "overview"]

        for line in lines:
            lower = line.strip().lower()
            # Detect TOC section
            if any(m in lower for m in toc_markers) and line.strip().startswith("#"):
                in_toc_section = True
                continue
            if in_toc_section:
                # End of TOC: next heading or blank line after bullets
                if line.strip().startswith("#"):
                    break
                # Parse bullet links: - [Title](#section) or - [Title](url)
                m = re.match(r"^\s*[-*+]\s+\[(.+?)\]\(#?(.+?)\)", line)
                if m:
                    toc.append({"title": m.group(1).strip(), "link": m.group(2).strip()})
                    continue
                # Plain bullet without link
                m = re.match(r"^\s*[-*+]\s+(.+)", line)
                if m:
                    text = m.group(1).strip()
                    if text and not text.startswith("["):
                        toc.append({"title": text, "link": ""})
                    continue

            # Strategy 2: Numbered list with links
            m = re.match(r"^\s*\d+[.、]\s+\[(.+?)\]\((.+?)\)", line)
            if m:
                toc.append({"title": m.group(1).strip(), "link": m.group(2).strip()})

        # Strategy 3: Section headings from README itself
        if not toc:
            for line in lines:
                m = re.match(r"^##\s+(.+)", line)
                if m:
                    title = m.group(1).strip()
                    if title.lower() not in ("table of contents", "overview", "目录"):
                        toc.append({"title": title, "link": ""})

        return toc

    # ── Directory Heuristic (Level 2) ──

    def analyze_directory_structure(self, dir_tree: Dict) -> dict:
        """Analyze directory tree to identify content groups."""
        files = [(k, v) for k, v in dir_tree.items() if v.get("type") == "file"]

        # Find chapter/directory groups
        groups = {}
        for path, info in files:
            parts = path.split("/")
            if len(parts) >= 2:
                group_dir = parts[0]
                if group_dir not in groups:
                    groups[group_dir] = {"dir": group_dir, "files": [], "count": 0, "extensions": set()}
                groups[group_dir]["files"].append(path)
                groups[group_dir]["count"] += 1
                ext = f".{path.split('.')[-1]}"
                groups[group_dir]["extensions"].add(ext)

        # Build nice names for groups
        result = []
        for g in sorted(groups.values(), key=lambda x: x["dir"]):
            # Heuristically name: replace _ with space, remove common prefixes
            nice = g["dir"].replace("_", " ").replace("-", " ").title()
            # Check if looks like a chapter directory
            is_chapter = any(kw in g["dir"].lower() for kw in ["chapter", "lesson", "sec", "part", "module"])
            result.append({
                "name": nice,
                "dir": g["dir"],
                "files": g["files"],
                "count": g["count"],
                "is_chapter": is_chapter,
            })

        return {"groups": result, "total_files": len(files)}

    # ── Structure Confidence (L0) + Logic Type ──

    def _normalize_title(self, s: str) -> str:
        """Normalize a title for fuzzy comparison."""
        import unicodedata
        s = unicodedata.normalize("NFKC", s or "").lower().strip()
        s = re.sub(r"[\s\-_./\\:：·、,，()（）\[\]\d]+", "", s)
        return s

    def compute_structure_confidence(self, readme_toc: list, dir_groups: list) -> dict:
        """
        Multi-strategy agreement check (L0):
        - README TOC vs directory groups overlap → high/medium/low.
        - "high" means the roadmap agent can trust the structure; "low" means
          it should read actual files before planning.
        """
        reasons = []
        if not readme_toc:
            return {"level": "low", "reasons": ["README 没有可解析的目录"]}
        if not dir_groups:
            return {"level": "low", "reasons": ["仓库没有明显的分组目录"]}

        toc_norm = {self._normalize_title(t.get("title", "")) for t in readme_toc}
        group_norm = {self._normalize_title(g.get("name", "")) for g in dir_groups}
        group_norm |= {self._normalize_title(g.get("dir", "")) for g in dir_groups}

        if not toc_norm:
            return {"level": "low", "reasons": ["README 目录为空"]}

        overlap = len(toc_norm & group_norm)
        ratio = overlap / len(toc_norm)
        reasons.append(f"TOC {len(toc_norm)} 项与目录分组重叠 {overlap} 项（{ratio:.0%}）")

        if ratio >= 0.7:
            level = "high"
            reasons.append("TOC 与目录结构高度一致")
        elif ratio >= 0.4:
            level = "medium"
            reasons.append("TOC 与目录结构部分一致，规划时需抽样核对文件")
        else:
            level = "low"
            reasons.append("TOC 与目录结构不一致，规划前应读取实际文件")

        return {"level": level, "reasons": reasons}

    def detect_structure_logic(self, dir_groups: list, readme_toc: list = None) -> str:
        """
        Detect the repo's organizational logic:
        - tutorial-progression: chapter/lesson/module dirs
        - project-steps: src/code + step/part/task naming
        - paper-logic: paper/arxiv/section naming
        Returns one of: tutorial-progression | project-steps | paper-logic | mixed
        """
        dir_names = " ".join(g.get("dir", "").lower() for g in (dir_groups or []))
        toc_text = " ".join(t.get("title", "").lower() for t in (readme_toc or []))
        blob = dir_names + " " + toc_text

        score = {"tutorial-progression": 0, "project-steps": 0, "paper-logic": 0}
        for kw in ("chapter", "lesson", "sec", "part", "module", "unit", "课程", "章节"):
            if kw in blob:
                score["tutorial-progression"] += 1
        for kw in ("src", "code", "step", "task", "stage", "阶段", "步骤", "实现"):
            if kw in blob:
                score["project-steps"] += 1
        for kw in ("paper", "arxiv", "section", "abstract", "论文", "定理", "证明"):
            if kw in blob:
                score["paper-logic"] += 1

        best = max(score, key=score.get)
        if score[best] == 0:
            return "mixed"
        if score[best] - sorted(score.values(), reverse=True)[1] <= 0 and score[best] <= 2:
            return "mixed"
        return best

    # ── Full Pipeline ──

    async def process_source(self, source_type: str, url: str) -> dict:
        """
        Full pipeline: fetch → extract → analyze → chunk.
        Returns {chunks: [...], source_meta: {...}}.
        """
        parsed = urlparse(url)
        clean_url = parsed._replace(query="").geturl().rstrip("/")
        if source_type != "github" and "github.com" in clean_url:
            source_type = "github"

        if source_type == "github":
            try:
                result = await self.clone_and_extract(clean_url)
                text = result["text"]
                dir_tree = result.get("dir_tree", {})
                readme = result.get("readme", "")

                # Level 1: README TOC
                readme_toc = self.parse_readme_toc(readme)

                # Level 2: Directory analysis
                dir_analysis = self.analyze_directory_structure(dir_tree)

                # L0: structure confidence + logic type
                confidence = self.compute_structure_confidence(readme_toc, dir_analysis["groups"])
                logic = self.detect_structure_logic(dir_analysis["groups"], readme_toc)

                source_meta = {
                    "dir_tree_keys": list(dir_tree.keys())[:500],
                    "readme_toc": readme_toc,
                    "dir_groups": dir_analysis["groups"],
                    "total_files": dir_analysis["total_files"],
                    "structure_confidence": confidence,
                    "structure_logic": logic,
                }

                chunks = self.chunk_text(text, source_type="github")
                return {"chunks": chunks, "source_meta": source_meta}

            except ValueError:
                try:
                    text = await self._fetch_github_via_api(clean_url)
                except Exception:
                    text = await self.fetch_github_readme(clean_url)
                chunks = self.chunk_text(text, source_type="github")
                return {"chunks": chunks, "source_meta": {}}
        else:
            text = await self.fetch_url(clean_url)
            chunks = self.chunk_text(text, source_type="url")
            return {"chunks": chunks, "source_meta": {}}

    async def _fetch_github_via_api(self, repo_url: str) -> str:
        """Fallback: download repo as tarball via GitHub API."""
        import tarfile, io

        owner, repo = self._parse_gh_url(repo_url)
        tarball_url = f"https://api.github.com/repos/{owner}/{repo}/tarball"
        headers = {"User-Agent": "LearnFlow/1.0", "Accept": "application/vnd.github.v3+json"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(tarball_url, headers=headers)
            resp.raise_for_status()
            data = resp.content

        text_parts = []
        skip_parts = {"node_modules", "__pycache__", ".git", ".github", "build", "dist", "venv", ".venv", "env"}
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isdir() or member.size > 500 * 1024:
                    continue
                parts_path = member.name.split("/")
                if any(p in skip_parts for p in parts_path):
                    continue
                ext = f".{member.name.split('.')[-1].lower()}" if "." in member.name else ""
                if ext not in self._READABLE_EXTS:
                    continue
                try:
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    content = f.read().decode("utf-8", errors="replace")
                    if len(content.strip()) < 20:
                        continue
                    text_parts.append(f"=== {member.name} ===\n{content}\n")
                except Exception:
                    continue

        if not text_parts:
            raise ValueError(f"No readable content via API for {repo_url}")
        return "\n".join(text_parts)
