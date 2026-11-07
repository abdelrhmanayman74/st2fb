// The part of the firmware that decides what the outputs do: Modbus PDU handling, the lease, fencing and the
// output watchdog. No Arduino, no sockets, no heap, and time is passed in, so the same file compiles for the
// ESP32 and for test_host/, where the same conformance test as the Python simulation runs against it.
// The behaviour must match edge/remote_io/server.py; tests/test_modbus_conformance.py checks both.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "../../include/regmap.h"

struct FieldInputs {
  float level = 0.0f;
  float flow = 0.0f;
  bool fb1 = false;
  bool fb2 = false;
  bool trip1 = false;
  bool trip2 = false;
  bool autoSwitch = true;
};

class IoCore {
 public:
  IoCore(uint16_t initialEpoch, uint32_t wdTimeoutMs, uint32_t leaseTtlMs, uint32_t nowMs);

  // One request PDU to one response PDU. Returns the response length. out needs room for 256 bytes.
  size_t handlePdu(const uint8_t *pdu, size_t len, uint8_t *out, uint32_t nowMs);

  // Call every regmap::TICK_MS. Drives the heartbeat, watchdog, ACK pulse and reservation timeout.
  void tick(uint32_t nowMs);

  void setField(const FieldInputs &field) { field_ = field; }
  bool output(int index) const { return outputs_[index]; }
  bool watchdogTripped() const { return wdTripped_; }
  uint16_t epoch() const { return epoch_; }

 private:
  size_t exception(uint8_t function, uint8_t code, uint8_t *out) const;
  uint16_t inputRegister(uint16_t addr, uint32_t nowMs) const;
  const uint16_t *holdingBlock(uint16_t addr, uint16_t count) const;
  uint8_t writeBlock(uint16_t addr, const uint16_t *words, uint16_t count, uint32_t nowMs);
  bool tokenOk(uint16_t token);
  uint8_t controlWrite(const uint16_t *words, uint32_t nowMs);
  uint8_t leaseRequest(uint16_t node, uint16_t expectedEpoch, uint32_t nowMs);
  uint8_t leaseRelease(uint16_t node, uint16_t epoch, uint16_t nextNode, uint32_t nowMs);
  uint8_t writeSetpoints(const uint16_t *words);

  FieldInputs field_;
  uint32_t wdTimeoutMs_;
  uint32_t leaseTtlMs_;
  uint32_t bootMs_;
  uint16_t epoch_;
  uint16_t holder_ = 0;
  uint16_t reservedFor_ = 0;
  uint32_t reservedUntil_ = 0;
  uint32_t lastControlMs_ = 0;
  bool leaseTimerStarted_ = false;
  bool haveControl_ = false;
  bool outputs_[2] = {false, false};
  bool wdTripped_ = false;
  uint16_t rejected_ = 0;
  uint16_t accepted_ = 0;
  uint16_t wdTrips_ = 0;
  uint16_t grants_ = 0;
  uint16_t heartbeat_ = 0;
  bool ack_ = false;
  uint32_t ackSince_ = 0;
  uint16_t setpoints_[regmap::BLOCK_SETPOINTS_COUNT];
  uint16_t control_[regmap::BLOCK_CONTROL_COUNT] = {};
  uint16_t checkpoint_[regmap::BLOCK_CHECKPOINT_COUNT] = {};
};
