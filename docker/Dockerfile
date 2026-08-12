# Regenerates the GitHub profile stat cards and pushes them to the repo.
# The generator script is pulled from the repo at runtime (always latest), so
# this image only needs Python (stdlib only) and git.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Invoked via `sh` so no host exec bit is required.
ENTRYPOINT ["sh", "/usr/local/bin/entrypoint.sh"]
