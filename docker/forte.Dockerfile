# Base image: FORTE at the pinned commit, fully built, with one empty FB slot (modules/st2fb).
# Build from the repo root:  docker build -f docker/forte.Dockerfile -t st2fb-forte:efcd63c docker
FROM ubuntu:24.04

ENV FORTE_COMMIT=efcd63c957ec191cab4fd57f8c5d6e3a3a30e0e2

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      g++ ninja-build python3 python3-venv git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# FORTE needs CMake >= 3.30; Ubuntu 24.04 ships 3.28.
RUN python3 -m venv /opt/cmake && /opt/cmake/bin/pip install --no-cache-dir 'cmake>=3.30,<4'

RUN git init -q /forte \
 && git -C /forte remote add origin https://github.com/eclipse-4diac/4diac-forte.git \
 && git -C /forte fetch -q --depth 1 origin "$FORTE_COMMIT" \
 && git -C /forte checkout -q FETCH_HEAD

COPY forte_module/ /forte/modules/st2fb/
RUN echo 'add_subdirectory(st2fb)' >> /forte/modules/CMakeLists.txt

RUN /opt/cmake/bin/cmake -S /forte -B /forte/build -G Ninja \
      -DFORTE_ARCHITECTURE=Posix \
      -DFORTE_COM_ETH=ON -DFORTE_COM_FBDK=ON -DFORTE_COM_LOCAL=ON \
      -DFORTE_MODULE_CONVERT=ON -DFORTE_MODULE_IEC61131=ON -DFORTE_MODULE_UTILS=ON \
      -DFORTE_TESTS=OFF \
 && ninja -C /forte/build forte

ENV PATH=/opt/cmake/bin:$PATH
