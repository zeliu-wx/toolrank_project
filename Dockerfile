ARG LAKES_IMAGE_PLATFORM=linux/amd64
FROM --platform=${LAKES_IMAGE_PLATFORM} python:3.10-slim-bookworm

ARG SMARTBUGS_REF=89c16bb620c6bfb10e9c025f9372c9a80b1c5279

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    LAKES_SMARTBUGS_DIR=/opt/smartbugs \
    LAKES_DOCKER_PLATFORM=linux/amd64

# System dependencies: git, Docker-in-Docker support, and build tools.
# DinD requires dockerd, containerd, and iptables. SmartBugs talks to the
# daemon inside this image so temporary tool paths stay in one filesystem namespace.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list; \
    fi; \
    printf '%s\n' 'Acquire::Retries "5";' 'Acquire::http::Timeout "240";' 'Acquire::https::Timeout "240";' > /etc/apt/apt.conf.d/99-retries; \
    apt_retry() { \
        for attempt in 1 2 3 4 5; do \
            "$@" && return 0; \
            sleep $((attempt * 5)); \
            apt-get update || true; \
        done; \
        "$@"; \
    }; \
    apt_retry apt-get update; \
    apt_retry apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg build-essential iptables default-jre-headless sudo; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl --retry 5 --retry-delay 2 --retry-connrefused -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list; \
    apt_retry apt-get update; \
    apt_retry apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io; \
    rm -rf /var/lib/apt/lists/*

# solc-select plus commonly used compiler versions. Smartian compiles with local solc;
# other versions can still be installed on demand at runtime.
RUN pip install solc-select \
    && solc-select install 0.4.25 0.4.26 0.5.12 0.5.17 0.6.12 0.8.19 0.8.30 || true

# .NET 8 SDK for Smartian.dll and the runner preflight check.
RUN curl --retry 5 --retry-delay 2 --retry-connrefused -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --channel 8.0 --install-dir /opt/dotnet \
    && rm /tmp/dotnet-install.sh

# Clone SmartBugs and install its runtime environment with Poetry.
RUN pip install --retries 5 --timeout 120 poetry \
    && git config --global http.version HTTP/1.1 \
    && for attempt in 1 2 3 4 5; do \
        git clone https://github.com/smartbugs/smartbugs /opt/smartbugs && break; \
        rm -rf /opt/smartbugs; \
        sleep $((attempt * 5)); \
    done \
    && test -d /opt/smartbugs/.git \
    && cd /opt/smartbugs \
    && git checkout ${SMARTBUGS_REF} \
    && poetry config virtualenvs.in-project true \
    && poetry install --only main --no-interaction --no-root

RUN python -c "from pathlib import Path; p=Path('/opt/smartbugs/sb/docker.py'); s=p.read_text(); old='client().images.pull(image)'; new='client().images.pull(image, platform=os.getenv(\"LAKES_DOCKER_PLATFORM\") or os.getenv(\"DOCKER_DEFAULT_PLATFORM\") or \"linux/amd64\")'; p.write_text(s.replace(old, new))"

# Overlay custom tool configs such as mando-hgt and vulhunter.
COPY docker/smartbugs-tools/ /opt/smartbugs/tools/

# LAKES package.
WORKDIR /work
COPY . /work
RUN set -eux; \
    pip install -e .; \
    solcx_install() { \
        version="$1"; \
        for attempt in 1 2 3 4 5; do \
            python -m solcx.install "$version" && return 0; \
            sleep $((attempt * 5)); \
        done; \
        python -m solcx.install "$version"; \
    }; \
    solcx_install 0.4.26; \
    solcx_install 0.5.17; \
    solcx_install 0.6.12; \
    solcx_install 0.7.6; \
    solcx_install 0.8.30

# Phase 2 special tool: sailfish. The thin wrapper uses only the standard library;
# its public image and solc are pulled or downloaded on demand at runtime.
ENV LAKES_SAILFISH_RUNNER=/work/docker/runners/run_sailfish.py

# Phase 2 special tool: gptscan. The runner executes src/main.py from the vendored
# virtualenv, uses src/jars for Java parsing, and receives the LLM endpoint at runtime.
# requirements-docker.txt omits host Ubuntu packages; falcon-analyzer is a git
# dependency, and openai uses the legacy SDK.
ENV LAKES_GPTSCAN_ROOT=/work/docker/vendor/gptscan
RUN set -eux; \
    python -m venv /work/docker/vendor/gptscan/.venv; \
    git config --global http.version HTTP/1.1; \
    gptscan_install() { \
        for attempt in 1 2 3 4 5; do \
            /work/docker/vendor/gptscan/.venv/bin/pip install --retries 5 --timeout 120 -r /work/docker/vendor/gptscan/requirements-docker.txt && return 0; \
            sleep $((attempt * 5)); \
        done; \
        /work/docker/vendor/gptscan/.venv/bin/pip install --retries 5 --timeout 120 -r /work/docker/vendor/gptscan/requirements-docker.txt; \
    }; \
    gptscan_install

# Phase 2 special tool: securify2. The runner builds securify:{ver} inside DinD
# using the contract solc version, then runs securifyjson.py through Docker.
ENV LAKES_SECURIFY2_RUNNER=/work/docker/vendor/securify2/securifyjson.py

# Phase 2 special tool: smartian. .NET 8 runs Smartian.dll; run_smartian compiles
# the contract with local solc before fuzzing. INVARIANT avoids the libicu dependency.
ENV DOTNET_ROOT=/opt/dotnet \
    PATH=/opt/dotnet:${PATH} \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    LAKES_SMARTIAN_RUNNER=/work/docker/runners/run_smartian.py

# Select a default solc so bare `solc` works for preflight checks.
# Tool runners can still switch versions per contract at runtime.
RUN solc-select use 0.5.12

# Smartian.dll embeds absolute resource paths from the build machine. Redirect the
# original build path to the vendored copy so those runtime lookups resolve.
RUN mkdir -p /Users/liuze/Downloads/QuantifyX \
    && ln -sfn /work/docker/vendor/smartian /Users/liuze/Downloads/QuantifyX/Smartian

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-buildx-plugin; \
    rm -rf /var/lib/apt/lists/*; \
    ln -sfn /opt/dotnet/dotnet /usr/local/bin/dotnet

# Internal dockerd image/layer storage. A named volume can cache pulled tool images.
VOLUME /var/lib/docker

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
