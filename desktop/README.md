# LearnFlow Desktop

This directory is the Tauri 2 shell for the existing React/Vite application.
It starts the packaged FastAPI sidecar on a random loopback port and generates
a fresh desktop token for every launch. The WebView has directory-picker
permission, but no broad filesystem permission; project file access is
validated again by the sidecar.

## Local build

1. Install the backend dependencies and `desktop/requirements-build.txt`.
2. Install Rust and the Tauri 2 platform prerequisites.
3. Run `npm install` in `frontend/` and `desktop/`.
4. Run `npm run build:sidecar` in `desktop/`.
5. Run `npm run dev` or `npm run build` in `desktop/`.

The generated target-triple sidecar and Rust/Node build output are ignored by
Git. macOS signing, Windows signing, and store credentials are intentionally
outside this repository stage.
