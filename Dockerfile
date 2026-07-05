ARG LAKES_IMAGE_PLATFORM=linux/amd64
FROM --platform=${LAKES_IMAGE_PLATFORM} python:3.10-slim-bookworm

ARG SMARTBUGS_REF=89c16bb620c6bfb10e9c025f9372c9a80b1c5279

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    LAKES_SMARTBUGS_DIR=/opt/smartbugs \
    LAKES_DOCKER_PLATFORM=linux/amd64

# 系统依赖：git（克隆 smartbugs）、完整 Docker 引擎（Docker-in-Docker）、构建工具。
# DinD 必需：dockerd + containerd + iptables（容器网络）。SmartBugs 与镜像内部
# 的 dockerd 通信，临时目录挂载在同一文件系统命名空间内，规避 DooD 路径不匹配。
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

# solc-select（多版本 solc）+ 预装常用版本（smartian 用本地 solc 编译合约；
# 其它版本运行时按需 solc-select install）
RUN pip install solc-select \
    && solc-select install 0.4.25 0.4.26 0.5.12 0.5.17 0.6.12 0.8.19 0.8.30 || true

# .NET 8 SDK（smartian 跑 Smartian.dll；run_smartian 的预检用 `dotnet --version` 需 SDK）
RUN curl --retry 5 --retry-delay 2 --retry-connrefused -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --channel 8.0 --install-dir /opt/dotnet \
    && rm /tmp/dotnet-install.sh

# SmartBugs：克隆 + poetry 安装到系统环境
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

# 叠加定制工具配置（mando-hgt / vulhunter 等）
COPY docker/smartbugs-tools/ /opt/smartbugs/tools/

# LAKES 本体
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
    solcx_install 0.8.30

# Phase 2 特例工具：sailfish 瘦包装脚本（纯标准库；公开镜像 holmessherlock/sailfish
# 与 solc 均在运行时按需拉取/下载）
ENV LAKES_SAILFISH_RUNNER=/work/docker/runners/run_sailfish.py

# Phase 2 特例工具：gptscan（按 runner 的 _run_gptscan 逻辑：用自带 venv 跑 src/main.py，
# Java 解析 src/jars，LLM 端点由运行时 -e 提供）。源码已随 COPY . /work 进镜像。
# 注意：requirements-docker.txt 已剔除 Ubuntu 系统泄漏包；falcon-analyzer 为 git 依赖，
# openai 为旧版 SDK。
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

# Phase 2 特例工具：securify2（按 runner 的 _run_securify2 逻辑：securifyjson.py 在 DinD 内
# 按合约 solc 版本 docker build securify:{ver} 再运行；securifyjson.py 调用 `sudo docker`，
# 故镜像装 sudo。源码已随 COPY . /work 进镜像）
ENV LAKES_SECURIFY2_RUNNER=/work/docker/vendor/securify2/securifyjson.py

# Phase 2 特例工具：smartian（.NET 8 跑 Smartian.dll；run_smartian 用本地 solc 编译合约后
# 模糊测试）。构建产物与瘦包装脚本已随 COPY . /work 进镜像。INVARIANT 绕开 libicu 依赖。
ENV DOTNET_ROOT=/opt/dotnet \
    PATH=/opt/dotnet:${PATH} \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    LAKES_SMARTIAN_RUNNER=/work/docker/runners/run_smartian.py

# 选一个默认 solc 版本，使裸 `solc` 可用（smartian 等的预检 `solc --version` 需要）。
# 运行时各工具仍可 `solc-select use <ver>` 按合约覆盖。
RUN solc-select use 0.5.12

# Smartian.dll 在构建机上把资源（src/Agent/*.bin 等）的绝对路径焊进了二进制。
# 用符号链接把原构建路径重定向到镜像内 vendored 副本，使写死路径在运行时可解析。
RUN mkdir -p /Users/liuze/Downloads/QuantifyX \
    && ln -sfn /work/docker/vendor/smartian /Users/liuze/Downloads/QuantifyX/Smartian

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-buildx-plugin; \
    rm -rf /var/lib/apt/lists/*; \
    ln -sfn /opt/dotnet/dotnet /usr/local/bin/dotnet

# 内部 dockerd 的镜像/层存储；可用命名卷挂载以跨运行缓存已拉取的工具镜像
VOLUME /var/lib/docker

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--help"]
