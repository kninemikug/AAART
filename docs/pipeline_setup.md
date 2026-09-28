# Pipeline Setup Record

## Test execution

- Python: `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python`
  (Python 3.14)
- Command: `/Users/user/Workspace/Programming/Projects/AAART/venv/bin/python -m pytest`

## Dependency installation record

| Dependency | Version | Status | First use |
| --- | --- | --- | --- |
| pytest | 9.1.1 | Installed 2026-09-02 | Pipeline smoke test |
| requests | 2.34.2 | Already installed | RawPedia collection |
| beautifulsoup4 | 4.15.0 | Already installed | RawPedia collection |
| markdownify | 1.2.3 | Already installed | RawPedia collection |
| sentence-transformers | 6.1.0 | Installed 2026-09-28 | Task 8-2 chunking & embedding benchmark |
| torch | 2.14.0 | Installed 2026-09-28 | Task 8-2 chunking & embedding benchmark |
| transformers | 5.17.0 | Installed 2026-09-28 | Task 8-2 chunking & embedding benchmark |
| tokenizers | 0.23.2 | Installed 2026-09-28 | Task 8-2 chunking & embedding benchmark |
| numpy | 2.5.3 | Installed 2026-09-28 | Task 8-2 chunking & embedding benchmark |
| chromadb | 1.5.9 | Installed 2026-09-28 | Task 8-2 vector store & benchmark |

Add a dependency here when its consuming task installs it. Packaging metadata
will be considered only when the installed set requires a maintained list.
