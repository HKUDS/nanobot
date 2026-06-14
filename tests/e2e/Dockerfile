# Sandbox for computer_use end-to-end tests.
#
# Provides BOTH backends in an isolated Linux container:
#   - browser  : headless Chromium via Playwright (no display needed)
#   - desktop  : PyAutoGUI driving a virtual X11 display (Xvfb) — Codex-style,
#                but contained so it never touches a real machine.
#
# Build:  docker build -f tests/e2e/Dockerfile -t nanobot-cu-e2e .
# Run:    docker run --rm -e OPENROUTER_API_KEY=sk-or-... -e COMPUTER_USE_E2E=1 \
#                  nanobot-cu-e2e
#
# The desktop backend needs a display; the entrypoint starts Xvfb on :99 and
# exports DISPLAY so pyautogui/scrot work headlessly.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

# X11 virtual display + screenshot/input tooling for the desktop backend,
# plus the system libs Chromium needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11-utils scrot xauth \
    libxtst6 libxrandr2 libxss1 libnss3 libasound2 libgbm1 libgtk-3-0 \
    fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -e ".[computer-use,dev]" \
    && python -m playwright install --with-deps chromium

# Start Xvfb, wait for it, then run the e2e suite.
RUN printf '#!/bin/sh\nset -e\nXvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &\nfor i in $(seq 1 30); do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep 0.3; done\nexec "$@"\n' > /usr/local/bin/with-xvfb \
    && chmod +x /usr/local/bin/with-xvfb

ENV COMPUTER_USE_E2E=1
ENTRYPOINT ["with-xvfb"]
CMD ["pytest", "tests/e2e/test_computer_use_e2e.py", "-v", "-s"]
