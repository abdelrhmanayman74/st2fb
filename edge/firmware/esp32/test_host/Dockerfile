# Firmware decision logic compiled for Linux. Build context: edge/firmware/esp32
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS build
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
COPY include/regmap.h /src/include/
COPY lib/io_core/ /src/lib/io_core/
COPY test_host/host_main.cpp /src/test_host/
RUN cd /src && g++ -std=c++17 -O2 -Wall -Wextra -Werror -static -Iinclude -Ilib/io_core lib/io_core/io_core.cpp test_host/host_main.cpp -o /host_main

FROM scratch
COPY --from=build /host_main /host_main
ENTRYPOINT ["/host_main"]
