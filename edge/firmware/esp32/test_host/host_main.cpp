// Runs lib/io_core on Linux behind a real TCP socket, for conformance tests and as a drop-in for the Python
// remote I/O. This exercises the firmware's decision logic on x86_64. It says nothing about ESP32 timing or Wi-Fi.
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
#include <vector>

#include "io_core.h"

namespace {
uint32_t nowMs() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<uint32_t>(ts.tv_sec * 1000ULL + ts.tv_nsec / 1000000);
}

uint32_t envU32(const char *name, uint32_t fallback) {
  const char *value = std::getenv(name);
  return value != nullptr ? static_cast<uint32_t>(std::strtoul(value, nullptr, 10)) : fallback;
}

struct Conn {
  int fd;
  std::vector<uint8_t> buffer;
};

bool serviceConn(Conn &conn, IoCore &core) {
  uint8_t chunk[512];
  const ssize_t n = read(conn.fd, chunk, sizeof(chunk));
  if (n <= 0) {
    return false;
  }
  conn.buffer.insert(conn.buffer.end(), chunk, chunk + n);
  while (conn.buffer.size() >= 7) {
    const uint16_t protocol = (conn.buffer[2] << 8) | conn.buffer[3];
    const uint16_t length = (conn.buffer[4] << 8) | conn.buffer[5];
    if (protocol != 0 || length < 2 || length > 254) {
      return false;
    }
    if (conn.buffer.size() < static_cast<size_t>(6 + length)) {
      break;
    }
    uint8_t response[7 + 256];
    const size_t responseLen = core.handlePdu(conn.buffer.data() + 7, length - 1, response + 7, nowMs());
    std::memcpy(response, conn.buffer.data(), 4);
    response[4] = static_cast<uint8_t>((responseLen + 1) >> 8);
    response[5] = static_cast<uint8_t>((responseLen + 1) & 0xFF);
    response[6] = conn.buffer[6];
    if (write(conn.fd, response, 7 + responseLen) < 0) {
      return false;
    }
    conn.buffer.erase(conn.buffer.begin(), conn.buffer.begin() + 6 + length);
  }
  return true;
}
}  // namespace

int main() {
  std::random_device random;
  IoCore core(static_cast<uint16_t>(random() % 0xFFF0) + 1, envU32("WD_TIMEOUT_MS", regmap::WD_TIMEOUT_MS),
              envU32("LEASE_TTL_MS", regmap::LEASE_TTL_MS), nowMs());

  const int listener = socket(AF_INET, SOCK_STREAM, 0);
  const int yes = 1;
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = INADDR_ANY;
  address.sin_port = htons(static_cast<uint16_t>(envU32("MODBUS_PORT", 502)));
  if (bind(listener, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0 || listen(listener, 8) != 0) {
    std::perror("listen");
    return 1;
  }

  // Optional UDP field link to the plant simulator, same text format as remote_io/server.py.
  int field = -1;
  sockaddr_in plant{};
  if (const char *host = std::getenv("PLANT_HOST")) {
    field = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in local{};
    local.sin_family = AF_INET;
    local.sin_addr.s_addr = INADDR_ANY;
    local.sin_port = htons(5020);
    bind(field, reinterpret_cast<sockaddr *>(&local), sizeof(local));
    addrinfo hints{};
    hints.ai_family = AF_INET;
    addrinfo *found = nullptr;
    while (getaddrinfo(host, nullptr, &hints, &found) != 0) {
      sleep(1);
    }
    plant = *reinterpret_cast<sockaddr_in *>(found->ai_addr);
    plant.sin_port = htons(5021);
    freeaddrinfo(found);
  }

  std::printf("host_main: firmware core on Linux (not an ESP32), epoch %u\n", core.epoch());
  std::fflush(stdout);
  std::vector<Conn> conns;
  uint32_t lastTick = nowMs();
  while (true) {
    std::vector<pollfd> fds;
    fds.push_back({listener, POLLIN, 0});
    if (field >= 0) {
      fds.push_back({field, POLLIN, 0});
    }
    const size_t first = fds.size();
    for (const Conn &conn : conns) {
      fds.push_back({conn.fd, POLLIN, 0});
    }
    poll(fds.data(), fds.size(), 5);
    if (fds[0].revents & POLLIN) {
      const int fd = accept(listener, nullptr, nullptr);
      if (fd >= 0) {
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
        conns.push_back({fd, {}});
      }
    }
    if (field >= 0 && (fds[1].revents & POLLIN)) {
      char text[128];
      const ssize_t n = recv(field, text, sizeof(text) - 1, 0);
      if (n > 0) {
        text[n] = '\0';
        FieldInputs in;
        int fb1, fb2, trip1, trip2, autoSwitch;
        if (std::sscanf(text, "S %f %f %d %d %d %d %d", &in.level, &in.flow, &fb1, &fb2, &trip1, &trip2, &autoSwitch) == 7) {
          in.fb1 = fb1;
          in.fb2 = fb2;
          in.trip1 = trip1;
          in.trip2 = trip2;
          in.autoSwitch = autoSwitch;
          core.setField(in);
        }
      }
    }
    for (size_t i = first; i < fds.size(); ++i) {
      if (fds[i].revents != 0) {
        Conn &conn = conns[i - first];
        if (!serviceConn(conn, core)) {
          close(conn.fd);
          conn.fd = -1;
        }
      }
    }
    for (size_t i = conns.size(); i-- > 0;) {
      if (conns[i].fd < 0) {
        conns.erase(conns.begin() + static_cast<long>(i));
      }
    }
    const uint32_t now = nowMs();
    if (now - lastTick >= regmap::TICK_MS) {
      lastTick = now;
      core.tick(now);
      if (field >= 0) {
        char text[32];
        const int n = std::snprintf(text, sizeof(text), "O %d %d", core.output(0), core.output(1));
        sendto(field, text, static_cast<size_t>(n), 0, reinterpret_cast<sockaddr *>(&plant), sizeof(plant));
      }
    }
  }
}
