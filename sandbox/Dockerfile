# Sandbox for safe execution of user code, mutmut, and pytest.
# This runs with no network, no host mounts beyond the work dir,
# and a strict timeout enforced by the subprocess caller.

FROM python:3.11-slim

# Create a non-root user — never run user code as root
RUN useradd -m -s /bin/bash sandbox

# Install only what the test pipeline needs
RUN pip install --no-cache-dir \
    pytest==8.2.0 \
    pytest-timeout==2.3.1 \
    mutmut==2.4.3

# Work directory — caller mounts source + tests here
WORKDIR /sandbox
RUN chown sandbox:sandbox /sandbox

USER sandbox

# Default: run pytest with a 30s per-test timeout
CMD ["pytest", "--timeout=30", "-v", "--tb=short"]