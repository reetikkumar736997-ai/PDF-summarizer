# TODO - Fix Frontend + Backend Errors

- [ ] Step 1: Fix backend imports to reliably start with `uvicorn backend.main:app --reload` from project root.
- [ ] Step 2: Add `backend/__init__.py` to make backend a package.
- [ ] Step 3: Make `/upload_pdf` response compatible with both HTML and Streamlit (return `message`).
- [ ] Step 4: Harden `/ask` for missing/empty Chroma collections; return helpful error.
- [ ] Step 5: Run backend and verify `/docs` + signup/login/upload/ask end-to-end.

