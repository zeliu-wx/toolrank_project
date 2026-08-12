ARG LAKES_IMAGE_PLATFORM=$BUILDPLATFORM
ARG SMARTIAN_REF=badd4ffe9dd47270b6abbe27af84a6435263716c

FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:8.0-bookworm-slim AS smartian-builder

ARG LAKES_IMAGE_PLATFORM
ARG SMARTIAN_REF

ENV DEBIAN_FRONTEND=noninteractive \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY docker/vendor/smartian/src/ /work/docker/vendor/smartian/src/

# Build on BuildKit's native platform so the .NET SDK never runs through QEMU.
# The runtime identifier still follows the final LAKES image architecture.
RUN set -eux; \
    case "${LAKES_IMAGE_PLATFORM}" in \
        linux/amd64) smartian_runtime=linux-x64 ;; \
        linux/arm64) smartian_runtime=linux-arm64 ;; \
        *) echo "unsupported LAKES_IMAGE_PLATFORM: ${LAKES_IMAGE_PLATFORM}" >&2; exit 2 ;; \
    esac; \
    git clone --no-checkout https://github.com/SoftSec-KAIST/Smartian.git /tmp/smartian-build; \
    git -C /tmp/smartian-build checkout --detach "${SMARTIAN_REF}"; \
    git -C /tmp/smartian-build submodule update --init \
        nethermind EVMAnalysis/B2R2; \
    git -C /tmp/smartian-build/nethermind submodule update --init \
        src/Dirichlet src/rocksdb-sharp; \
    cp -a /tmp/smartian-build/nethermind /work/docker/vendor/smartian/nethermind; \
    cp -a /tmp/smartian-build/EVMAnalysis /work/docker/vendor/smartian/EVMAnalysis; \
    dotnet restore /work/docker/vendor/smartian/src/Smartian.fsproj \
        --runtime "${smartian_runtime}" \
        --verbosity normal; \
    dotnet build /work/docker/vendor/smartian/src/Smartian.fsproj \
        --configuration Release \
        --runtime "${smartian_runtime}" \
        --output /work/docker/vendor/smartian/build \
        --no-restore \
        --nologo; \
    test -s /work/docker/vendor/smartian/build/Smartian.dll; \
    rm -rf /tmp/smartian-build \
        /work/docker/vendor/smartian/nethermind \
        /work/docker/vendor/smartian/EVMAnalysis

FROM --platform=${LAKES_IMAGE_PLATFORM} python:3.10-slim-bookworm

ARG SMARTBUGS_REF=89c16bb620c6bfb10e9c025f9372c9a80b1c5279
ARG FALCON_REF=93c1be7914f24e5567ff17da45be6f87b506c069

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    LAKES_SMARTBUGS_DIR=/opt/smartbugs \
    LAKES_DOCKER_PLATFORM=linux/amd64

# System dependencies: git, Docker-in-Docker support, and build tools.
# DinD requires dockerd, containerd, and iptables. SmartBugs talks to the
# daemon inside this image so temporary tool paths stay in one filesystem namespace.
RUN set -eux; \
    native_arch="$(dpkg --print-architecture)"; \
    if [ "${native_arch}" = "arm64" ]; then \
        dpkg --add-architecture amd64; \
    fi; \
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
    if [ "${native_arch}" = "arm64" ]; then \
        apt_retry apt-get install -y --no-install-recommends \
            libc6:amd64 libstdc++6:amd64; \
    fi; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl --retry 5 --retry-delay 2 --retry-connrefused -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list; \
    apt_retry apt-get update; \
    apt_retry apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io; \
    rm -rf /var/lib/apt/lists/*

# Official Linux solc releases are x86-64. The ARM image therefore carries only
# their x86 userspace libraries; Docker's platform emulator runs the binary,
# while .NET and Python stay native.
# Smartian compiles with local solc, while other versions remain installable.
RUN pip install solc-select \
    && solc-select install 0.4.25 0.4.26 0.5.12 0.5.17 0.6.12 0.8.19 0.8.30 || true

# .NET 8 runtime for Smartian.dll and the runner preflight check.
RUN curl --retry 5 --retry-delay 2 --retry-connrefused -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --channel 8.0 --runtime dotnet --install-dir /opt/dotnet \
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
    lakes_install() { \
        for attempt in 1 2 3 4 5; do \
            pip install --retries 5 --timeout 120 -e . && return 0; \
            sleep $((attempt * 5)); \
        done; \
        pip install --retries 5 --timeout 120 -e .; \
    }; \
    lakes_install; \
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

COPY --from=smartian-builder \
    /work/docker/vendor/smartian/build/ \
    /work/docker/vendor/smartian/build/

# The source-resource path is identical in both stages, while ignored developer
# output and host paths cannot satisfy the build.
RUN set -eux; \
    test -s /work/docker/vendor/smartian/build/Smartian.dll; \
    test -s /work/docker/vendor/smartian/src/Agent/AttackerContract.bin; \
    test -s /work/docker/vendor/smartian/src/Agent/SFuzzContract.bin; \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
        /opt/dotnet/dotnet /work/docker/vendor/smartian/build/Smartian.dll \
        2>&1 | grep -F "Usage:"

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
    gptscan_requirements=/work/docker/vendor/gptscan/requirements-docker.txt; \
    falcon_z3_version=4.11.2.0; \
    if [ "$(dpkg --print-architecture)" = "arm64" ]; then \
        sed 's/z3-solver==4.11.2.0/z3-solver==4.13.0.0/' \
            "${gptscan_requirements}" > /tmp/gptscan-requirements.txt; \
        gptscan_requirements=/tmp/gptscan-requirements.txt; \
        falcon_z3_version=4.13.0.0; \
    fi; \
    gptscan_install() { \
        for attempt in 1 2 3 4 5; do \
            /work/docker/vendor/gptscan/.venv/bin/pip install --retries 5 --timeout 120 -r "${gptscan_requirements}" && return 0; \
            sleep $((attempt * 5)); \
        done; \
        /work/docker/vendor/gptscan/.venv/bin/pip install --retries 5 --timeout 120 -r "${gptscan_requirements}"; \
    }; \
    gptscan_install; \
    for attempt in 1 2 3 4 5; do \
        git clone --no-checkout https://github.com/MetaTrustLabs/falcon-metatrust /tmp/falcon-metatrust && break; \
        rm -rf /tmp/falcon-metatrust; \
        sleep $((attempt * 5)); \
    done; \
    test -d /tmp/falcon-metatrust/.git; \
    git -C /tmp/falcon-metatrust checkout --detach "${FALCON_REF}"; \
    sed -i \
        "s/z3-solver==4.11.2.0/z3-solver==${falcon_z3_version}/" \
        /tmp/falcon-metatrust/setup.py; \
    grep -F "\"z3-solver==${falcon_z3_version}\"" \
        /tmp/falcon-metatrust/setup.py; \
    /work/docker/vendor/gptscan/.venv/bin/pip install --no-deps \
        /tmp/falcon-metatrust; \
    /work/docker/vendor/gptscan/.venv/bin/python -c \
        "from importlib.metadata import version; import z3; from falcon import Falcon; assert version('z3-solver') == '${falcon_z3_version}'"

# Phase 2 special tool: securify2. The runner builds securify:{ver} inside DinD
# using the contract solc version, then runs securifyjson.py through Docker.
ENV LAKES_SECURIFY2_RUNNER=/work/docker/vendor/securify2/securifyjson.py

# Phase 2 special tool: smartian. .NET 8 runs Smartian.dll; run_smartian compiles
# the contract with local solc before fuzzing. INVARIANT avoids the libicu dependency.
ENV DOTNET_ROOT=/opt/dotnet \
    PATH=/opt/dotnet:${PATH} \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    LAKES_SMARTIAN_RUNNER=/work/docker/runners/run_smartian.py

# Select and execute a default solc so cross-architecture loader failures are
# caught while building the release image rather than at analyzer runtime.
# Tool runners can still switch versions per contract at runtime.
RUN solc-select use 0.5.12 \
    && solc --version

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
