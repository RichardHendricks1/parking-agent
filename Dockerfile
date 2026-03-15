FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Install Node.js 20 to build the WhatsApp bridge.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

COPY pyproject.toml README.md LICENSE ./
COPY nanobot/ nanobot/
COPY bridge/ bridge/

RUN uv pip install --system --no-cache .

WORKDIR /src/bridge
RUN npm install && \
    npm run build && \
    npm prune --omit=dev

WORKDIR /src

RUN python - <<'PY'
import compileall
import pathlib
import shutil
import sysconfig

purelib = pathlib.Path(sysconfig.get_paths()["purelib"])
package_dir = purelib / "nanobot"
compileall.compile_dir(str(package_dir), force=True, quiet=1, legacy=True)

for py_file in package_dir.rglob("*.py"):
    py_file.unlink()

packaged_bridge = package_dir / "bridge"
if packaged_bridge.exists():
    shutil.rmtree(packaged_bridge)
PY

FROM python:3.12-slim-bookworm AS runtime

# Install Node.js runtime for the prebuilt WhatsApp bridge.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y curl gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/nanobot /usr/local/bin/nanobot
COPY --from=builder /src/bridge/dist /opt/nanobot/bridge/dist
COPY --from=builder /src/bridge/node_modules /opt/nanobot/bridge/node_modules
COPY --from=builder /src/bridge/package.json /opt/nanobot/bridge/package.json

ENV NANOBOT_BUNDLED_BRIDGE_DIR=/opt/nanobot/bridge \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /root/.nanobot

EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["gateway"]
