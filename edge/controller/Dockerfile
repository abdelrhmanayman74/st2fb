# FORTE at the pinned commit with the Modbus com layer and the migrated FBs.
# Build context is edge/:  docker build -f controller/Dockerfile -t st2fb-edge-controller .
# FORTE is the pinned commit plus one small patch (controller/patches): see the patch for why.
# The smallest working set: the Modbus client layer only (libmodbus). MQTT, OPC UA and HTTP layers stay off;
# docs/EDGE.md explains why. FBDK and ETH stay on because DEV_MGR, the management port, needs them.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS builder

ENV FORTE_COMMIT=efcd63c957ec191cab4fd57f8c5d6e3a3a30e0e2

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      g++ ninja-build python3 python3-venv git ca-certificates libmodbus-dev \
 && rm -rf /var/lib/apt/lists/*

# FORTE needs CMake >= 3.30; Ubuntu 24.04 ships 3.28.
RUN python3 -m venv /opt/cmake && /opt/cmake/bin/pip install --no-cache-dir 'cmake==3.31.6'

RUN git init -q /forte \
 && git -C /forte remote add origin https://github.com/eclipse-4diac/4diac-forte.git \
 && git -C /forte fetch -q --depth 1 origin "$FORTE_COMMIT" \
 && git -C /forte checkout -q FETCH_HEAD

# One local patch on top of the pinned commit, explained in the patch file.
COPY controller/patches/ /tmp/patches/
RUN git -C /forte apply --verbose /tmp/patches/*.patch

# First build with empty FB sources, so that changing an FB recompiles four files and not all of FORTE.
COPY controller/module/CMakeLists.txt /forte/modules/st2fb_edge/CMakeLists.txt
RUN cd /forte/modules/st2fb_edge \
 && touch PUMP_STATION_SUPERVISOR_fbt.cpp IO_GUARD_fbt.cpp OUTPUT_PACK_fbt.cpp SCAN_PROBE_fbt.cpp \
 && echo 'add_subdirectory(st2fb_edge)' >> /forte/modules/CMakeLists.txt \
 && /opt/cmake/bin/cmake -S /forte -B /forte/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DFORTE_ARCHITECTURE=Posix \
      -DFORTE_COM_ETH=ON -DFORTE_COM_FBDK=ON -DFORTE_COM_MODBUS=ON \
      -DFORTE_TESTS=OFF \
 && ninja -C /forte/build forte

COPY controller/generated/*_fbt.cpp controller/generated/*_fbt.h controller/module/SCAN_PROBE_fbt.cpp controller/module/SCAN_PROBE_fbt.h /forte/modules/st2fb_edge/
# COPY keeps source mtimes, older than the placeholder objects, so touch or ninja would rebuild nothing.
RUN touch /forte/modules/st2fb_edge/*.cpp \
 && ninja -C /forte/build forte \
 && strip /forte/build/forte \
 && { echo "forte $FORTE_COMMIT"; echo "libmodbus $(dpkg-query -W -f '${Version}' libmodbus-dev)"; echo "arch $(dpkg --print-architecture)"; } > /forte/build/BUILD_INFO

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmodbus5 python3 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --no-create-home forte
COPY --from=builder /forte/build/forte /forte/build/BUILD_INFO /opt/forte/
COPY common/ /app/common/
COPY regmap.json /app/regmap.json
COPY controller/agent/ /app/agent/
USER 10001
WORKDIR /app
ENTRYPOINT ["python3", "-B", "-u", "-m", "agent.agent"]
