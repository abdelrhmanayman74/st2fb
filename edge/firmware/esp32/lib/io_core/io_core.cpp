#include "io_core.h"

#include <math.h>
#include <string.h>

namespace {
constexpr uint8_t EX_ILLEGAL_FUNCTION = 1;
constexpr uint8_t EX_ILLEGAL_ADDRESS = 2;
constexpr uint8_t EX_ILLEGAL_VALUE = 3;
constexpr uint8_t EX_BUSY = 6;
constexpr uint8_t OK = 0;

uint16_t get16(const uint8_t *p) { return static_cast<uint16_t>((p[0] << 8) | p[1]); }

void put16(uint8_t *p, uint16_t value) {
  p[0] = static_cast<uint8_t>(value >> 8);
  p[1] = static_cast<uint8_t>(value & 0xFF);
}

void floatToWords(float value, uint16_t *words) {
  uint32_t raw;
  memcpy(&raw, &value, sizeof(raw));
  words[0] = static_cast<uint16_t>(raw >> 16);
  words[1] = static_cast<uint16_t>(raw & 0xFFFF);
}

float wordsToFloat(const uint16_t *words) {
  const uint32_t raw = (static_cast<uint32_t>(words[0]) << 16) | words[1];
  float value;
  memcpy(&value, &raw, sizeof(value));
  return value;
}
}  // namespace

IoCore::IoCore(uint16_t initialEpoch, uint32_t wdTimeoutMs, uint32_t leaseTtlMs, uint32_t nowMs)
    : wdTimeoutMs_(wdTimeoutMs), leaseTtlMs_(leaseTtlMs), bootMs_(nowMs), epoch_(initialEpoch == 0 ? 1 : initialEpoch) {
  floatToWords(regmap::STOP_LEVEL_DEFAULT, &setpoints_[0]);
  floatToWords(regmap::START_LEVEL_DEFAULT, &setpoints_[2]);
  floatToWords(regmap::LAG_LEVEL_DEFAULT, &setpoints_[4]);
  floatToWords(regmap::HIGH_LEVEL_DEFAULT, &setpoints_[6]);
}

void IoCore::tick(uint32_t nowMs) {
  ++heartbeat_;
  if (ack_ && nowMs - ackSince_ >= regmap::ACK_PULSE_MS) {
    ack_ = false;
  }
  if (reservedFor_ != 0 && static_cast<int32_t>(nowMs - reservedUntil_) >= 0) {
    reservedFor_ = 0;
  }
  if (haveControl_ && !wdTripped_ && nowMs - lastControlMs_ > wdTimeoutMs_) {
    wdTripped_ = true;
    ++wdTrips_;
    outputs_[0] = outputs_[1] = false;
  }
}

uint16_t IoCore::inputRegister(uint16_t addr, uint32_t nowMs) const {
  uint16_t words[2];
  switch (addr) {
    case regmap::IR_RAW_LEVEL: floatToWords(field_.level, words); return words[0];
    case regmap::IR_RAW_LEVEL + 1: floatToWords(field_.level, words); return words[1];
    case regmap::IR_FLOW: floatToWords(field_.flow, words); return words[0];
    case regmap::IR_FLOW + 1: floatToWords(field_.flow, words); return words[1];
    case regmap::IR_FB_1: return field_.fb1;
    case regmap::IR_FB_2: return field_.fb2;
    case regmap::IR_TRIP_1: return field_.trip1;
    case regmap::IR_TRIP_2: return field_.trip2;
    case regmap::IR_AUTO_SWITCH: return field_.autoSwitch;
    case regmap::IR_HEARTBEAT: return heartbeat_;
    case regmap::IR_ACK_MIRROR: return ack_;
    case regmap::IR_LEASE_EPOCH: return epoch_;
    case regmap::IR_LEASE_HOLDER: return holder_;
    case regmap::IR_LEASE_AGE_MS: {
      if (!leaseTimerStarted_) return 65535;
      const uint32_t age = nowMs - lastControlMs_;
      return age > 65535 ? 65535 : static_cast<uint16_t>(age);
    }
    case regmap::IR_WD_TRIPPED: return wdTripped_;
    case regmap::IR_OUTPUT_1: return outputs_[0];
    case regmap::IR_OUTPUT_2: return outputs_[1];
    case regmap::IR_REJECTED: return rejected_;
    case regmap::IR_ACCEPTED: return accepted_;
    case regmap::IR_WD_TRIPS: return wdTrips_;
    case regmap::IR_GRANTS: return grants_;
    case regmap::IR_UPTIME_S: return static_cast<uint16_t>((nowMs - bootMs_) / 1000);
    case regmap::IR_MAP_VERSION: return regmap::MAP_VERSION_VALUE;
    case regmap::IR_WD_TIMEOUT_MS: return static_cast<uint16_t>(wdTimeoutMs_);
    case regmap::IR_LEASE_TTL_MS: return static_cast<uint16_t>(leaseTtlMs_);
    case regmap::IR_RESERVED_FOR: return reservedFor_;
    default: return 0;
  }
}

const uint16_t *IoCore::holdingBlock(uint16_t addr, uint16_t count) const {
  struct Block {
    uint16_t base, size;
    const uint16_t *data;
  };
  const Block blocks[] = {
      {regmap::BLOCK_SETPOINTS_ADDR, regmap::BLOCK_SETPOINTS_COUNT, setpoints_},
      {regmap::BLOCK_CONTROL_ADDR, regmap::BLOCK_CONTROL_COUNT, control_},
      {regmap::BLOCK_CHECKPOINT_ADDR, regmap::BLOCK_CHECKPOINT_COUNT, checkpoint_},
  };
  for (const Block &block : blocks) {
    if (block.base <= addr && addr + count <= block.base + block.size) {
      return block.data + (addr - block.base);
    }
  }
  return nullptr;
}

size_t IoCore::exception(uint8_t function, uint8_t code, uint8_t *out) const {
  out[0] = function | 0x80;
  out[1] = code;
  return 2;
}

size_t IoCore::handlePdu(const uint8_t *pdu, size_t len, uint8_t *out, uint32_t nowMs) {
  if (len < 1) {
    return exception(0, EX_ILLEGAL_VALUE, out);
  }
  const uint8_t function = pdu[0];
  switch (function) {
    case 3:
    case 4: {
      if (len < 5) return exception(function, EX_ILLEGAL_VALUE, out);
      const uint16_t addr = get16(pdu + 1);
      const uint16_t count = get16(pdu + 3);
      if (count < 1 || count > 125) return exception(function, EX_ILLEGAL_VALUE, out);
      const uint16_t *block = nullptr;
      if (function == 3) {
        block = holdingBlock(addr, count);
        if (block == nullptr) return exception(function, EX_ILLEGAL_ADDRESS, out);
      } else if (addr + count > 32) {  // Same image size as the simulation: unused addresses read as 0.
        return exception(function, EX_ILLEGAL_ADDRESS, out);
      }
      out[0] = function;
      out[1] = static_cast<uint8_t>(2 * count);
      for (uint16_t i = 0; i < count; ++i) {
        put16(out + 2 + 2 * i, function == 3 ? block[i] : inputRegister(addr + i, nowMs));
      }
      return 2 + 2 * static_cast<size_t>(count);
    }
    case 1: {
      if (len < 5) return exception(function, EX_ILLEGAL_VALUE, out);
      if (get16(pdu + 1) != regmap::COIL_ACK || get16(pdu + 3) != 1) return exception(function, EX_ILLEGAL_ADDRESS, out);
      out[0] = 1;
      out[1] = 1;
      out[2] = ack_ ? 1 : 0;
      return 3;
    }
    case 5: {
      if (len < 5) return exception(function, EX_ILLEGAL_VALUE, out);
      if (get16(pdu + 1) != regmap::COIL_ACK) return exception(function, EX_ILLEGAL_ADDRESS, out);
      const uint16_t value = get16(pdu + 3);
      if (value != 0 && value != 0xFF00) return exception(function, EX_ILLEGAL_VALUE, out);
      ack_ = value != 0;
      if (ack_) {
        ackSince_ = nowMs;
      }
      memcpy(out, pdu, 5);
      return 5;
    }
    case 16: {
      if (len < 6) return exception(function, EX_ILLEGAL_VALUE, out);
      const uint16_t addr = get16(pdu + 1);
      const uint16_t count = get16(pdu + 3);
      const uint8_t size = pdu[5];
      if (size != 2 * count || len != static_cast<size_t>(6 + size) || count > 123) {
        return exception(function, EX_ILLEGAL_VALUE, out);
      }
      uint16_t words[123];
      for (uint16_t i = 0; i < count; ++i) {
        words[i] = get16(pdu + 6 + 2 * i);
      }
      const uint8_t code = writeBlock(addr, words, count, nowMs);
      if (code != OK) return exception(function, code, out);
      memcpy(out, pdu, 5);
      return 5;
    }
    default: return exception(function, EX_ILLEGAL_FUNCTION, out);
  }
}

uint8_t IoCore::writeBlock(uint16_t addr, const uint16_t *words, uint16_t count, uint32_t nowMs) {
  if (addr == regmap::BLOCK_LEASE_REQUEST_ADDR && count == regmap::BLOCK_LEASE_REQUEST_COUNT) {
    return leaseRequest(words[0], words[1], nowMs);
  }
  if (addr == regmap::BLOCK_LEASE_RELEASE_ADDR && count == regmap::BLOCK_LEASE_RELEASE_COUNT) {
    return leaseRelease(words[0], words[1], words[2], nowMs);
  }
  if (addr == regmap::BLOCK_SETPOINTS_ADDR && count == regmap::BLOCK_SETPOINTS_COUNT) {
    return writeSetpoints(words);
  }
  if (addr == regmap::BLOCK_CONTROL_ADDR && count == regmap::BLOCK_CONTROL_COUNT) {
    return controlWrite(words, nowMs);
  }
  if (addr == regmap::BLOCK_CHECKPOINT_ADDR && count == regmap::BLOCK_CHECKPOINT_COUNT) {
    if (!tokenOk(words[0])) return EX_BUSY;
    memcpy(checkpoint_, words, sizeof(checkpoint_));
    return OK;
  }
  return EX_ILLEGAL_ADDRESS;
}

bool IoCore::tokenOk(uint16_t token) {
  if (holder_ != 0 && token == epoch_) {
    return true;
  }
  ++rejected_;
  return false;
}

uint8_t IoCore::controlWrite(const uint16_t *words, uint32_t nowMs) {
  if (!tokenOk(words[0])) {
    return EX_BUSY;
  }
  memcpy(control_, words, sizeof(control_));
  ++accepted_;
  lastControlMs_ = nowMs;
  leaseTimerStarted_ = true;
  haveControl_ = true;
  wdTripped_ = false;
  outputs_[0] = words[regmap::HR_PUMP_1 - regmap::HR_TOKEN] != 0;
  outputs_[1] = words[regmap::HR_PUMP_2 - regmap::HR_TOKEN] != 0;
  return OK;
}

uint8_t IoCore::leaseRequest(uint16_t node, uint16_t expectedEpoch, uint32_t nowMs) {
  if (node == 0 || expectedEpoch != epoch_) {
    return EX_BUSY;
  }
  const bool isFree = holder_ != 0 ? nowMs - lastControlMs_ > leaseTtlMs_ : (reservedFor_ == 0 || reservedFor_ == node);
  if (!isFree) {
    return EX_BUSY;
  }
  epoch_ = epoch_ < 0xFFFF ? epoch_ + 1 : 1;
  holder_ = node;
  reservedFor_ = 0;
  lastControlMs_ = nowMs;
  leaseTimerStarted_ = true;
  ++grants_;
  return OK;
}

uint8_t IoCore::leaseRelease(uint16_t node, uint16_t epoch, uint16_t nextNode, uint32_t nowMs) {
  if (node == 0 || node != holder_ || epoch != epoch_) {
    return EX_BUSY;
  }
  holder_ = 0;
  reservedFor_ = nextNode;
  reservedUntil_ = nowMs + leaseTtlMs_;
  return OK;
}

uint8_t IoCore::writeSetpoints(const uint16_t *words) {
  float values[4];
  for (int i = 0; i < 4; ++i) {
    values[i] = wordsToFloat(&words[2 * i]);
    if (!isfinite(values[i]) || values[i] < regmap::SETPOINT_MIN || values[i] > regmap::SETPOINT_MAX) {
      return EX_ILLEGAL_VALUE;
    }
  }
  if (!(values[0] < values[1] && values[1] < values[2] && values[2] < values[3])) {
    return EX_ILLEGAL_VALUE;
  }
  memcpy(setpoints_, words, sizeof(setpoints_));
  return OK;
}
