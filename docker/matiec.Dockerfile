# Reference oracle image: builds the matiec IEC 61131-3 compiler at a pinned commit.
# matiec is GPLv3. It runs only as an external tool inside this container; nothing
# from it is linked into or vendored in this repository.
#
#   docker build -f docker/matiec.Dockerfile -t st2fb-matiec:3a41303 docker
FROM ubuntu:24.04

ARG MATIEC_COMMIT=3a41303

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      autoconf automake bison ca-certificates flex g++ gcc git libtool make \
 && git clone https://github.com/beremiz/matiec.git /opt/matiec \
 && cd /opt/matiec \
 && git checkout "$MATIEC_COMMIT" \
 && autoreconf -i \
 && ./configure \
 && make -j"$(nproc)" \
 && git rev-parse --short=7 HEAD > /opt/matiec/COMMIT \
 && rm -rf /opt/matiec/.git \
 && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# iec2c: ST to C. /opt/matiec/lib: standard library sources and the C headers it generates against.
ENV PATH="/opt/matiec:${PATH}"
WORKDIR /work
