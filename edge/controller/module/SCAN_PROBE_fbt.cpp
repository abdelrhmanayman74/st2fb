#include "SCAN_PROBE_fbt.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>

using namespace forte::literals;

namespace forte::st2fb {
  namespace {
    const auto cEventInputNames = std::array{"REQ"_STRID, "END"_STRID};
    const auto cEventOutputNames = std::array{"CNF"_STRID};
    const auto cDataOutputNames =
        std::array{"LAST_DT_10US"_STRID, "MAX_DT_10US"_STRID, "LAST_EXEC_US"_STRID, "SCAN_COUNT"_STRID};
    const SFBInterfaceSpec cFBInterfaceSpec = {
        .mEINames = cEventInputNames,
        .mEITypeNames = {},
        .mEONames = cEventOutputNames,
        .mEOTypeNames = {},
        .mDINames = {},
        .mDONames = cDataOutputNames,
        .mDIONames = {},
        .mSocketNames = {},
        .mPlugNames = {},
    };

    constexpr uint16_t saturate16(unsigned long long value) {
      return value > 65535 ? 65535 : static_cast<uint16_t>(value);
    }

    unsigned long long nowNs() {
      timespec ts;
      clock_gettime(CLOCK_MONOTONIC, &ts);
      return static_cast<unsigned long long>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
    }

    // One record per cycle event: u64 CLOCK_MONOTONIC ns of this event, u32 execution time in us of the
    // previous scan (0 when its write was gated off), u32 reserved. Capped so it cannot fill the tmpfs.
    constexpr unsigned long cMaxRecords = 1UL << 20;
    constexpr unsigned cFlushEvery = 10;

    void logRecord(unsigned long long paTimeNs, unsigned paExecUs) {
      static FILE *const file = [] {
        const char *path = std::getenv("ST2FB_SCAN_LOG");
        return path != nullptr ? std::fopen(path, "wb") : nullptr;
      }();
      static unsigned long records = 0;
      if (file == nullptr || records >= cMaxRecords) {
        return;
      }
      const uint64_t time = paTimeNs;
      const uint32_t exec[2] = {paExecUs, 0};
      std::fwrite(&time, sizeof(time), 1, file);
      std::fwrite(exec, sizeof(exec), 1, file);
      if (++records % cFlushEvery == 0) {
        std::fflush(file);
      }
    }
  } // namespace

  DEFINE_FIRMWARE_FB(FORTE_SCAN_PROBE, "st2fb::SCAN_PROBE"_STRID)

  FORTE_SCAN_PROBE::FORTE_SCAN_PROBE(const StringId paInstanceNameId, CFBContainer &paContainer) :
      CBasicFB(paContainer, cFBInterfaceSpec, paInstanceNameId, {}),
      var_LAST_DT_10US(0_UINT),
      var_MAX_DT_10US(0_UINT),
      var_LAST_EXEC_US(0_UINT),
      var_SCAN_COUNT(0_UINT),
      conn_CNF(*this, 0),
      conn_LAST_DT_10US(*this, 0, var_LAST_DT_10US),
      conn_MAX_DT_10US(*this, 1, var_MAX_DT_10US),
      conn_LAST_EXEC_US(*this, 2, var_LAST_EXEC_US),
      conn_SCAN_COUNT(*this, 3, var_SCAN_COUNT) {
  }

  void FORTE_SCAN_PROBE::setInitialValues() {
    CBasicFB::setInitialValues();
    var_LAST_DT_10US = 0_UINT;
    var_MAX_DT_10US = 0_UINT;
    var_LAST_EXEC_US = 0_UINT;
    var_SCAN_COUNT = 0_UINT;
  }

  void FORTE_SCAN_PROBE::executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) {
    if (paEIID == scmEventREQID) {
      const unsigned long long now = nowNs();
      logRecord(now, mLastExecUs);
      if (mLastReqNs != 0) {
        const uint16_t dt = saturate16((now - mLastReqNs) / 10000); // 10 us units: a 16-bit us count stops at 65 ms.
        var_LAST_DT_10US = CIEC_UINT(dt);
        var_MAX_DT_10US = CIEC_UINT(std::max<uint16_t>(dt, static_cast<CIEC_UINT::TValueType>(var_MAX_DT_10US)));
      }
      var_LAST_EXEC_US = CIEC_UINT(saturate16(mLastExecUs));
      var_SCAN_COUNT = CIEC_UINT(static_cast<uint16_t>(static_cast<CIEC_UINT::TValueType>(var_SCAN_COUNT) + 1));
      mLastReqNs = now;
      mScanStartNs = now;
      mLastExecUs = 0;
      sendOutputEvent(scmEventCNFID, paECET);
    } else if (paEIID == scmEventENDID) {
      mLastExecUs = static_cast<unsigned>((nowNs() - mScanStartNs) / 1000);
    }
  }

  void FORTE_SCAN_PROBE::readInputData(const TEventID) {
  }

  void FORTE_SCAN_PROBE::writeOutputData(const TEventID paEIID) {
    if (paEIID == scmEventCNFID) {
      writeData(cFBInterfaceSpec.getNumDIs() + 0, var_LAST_DT_10US, conn_LAST_DT_10US);
      writeData(cFBInterfaceSpec.getNumDIs() + 1, var_MAX_DT_10US, conn_MAX_DT_10US);
      writeData(cFBInterfaceSpec.getNumDIs() + 2, var_LAST_EXEC_US, conn_LAST_EXEC_US);
      writeData(cFBInterfaceSpec.getNumDIs() + 3, var_SCAN_COUNT, conn_SCAN_COUNT);
    }
  }

  CIEC_ANY *FORTE_SCAN_PROBE::getDI(const size_t) {
    return nullptr;
  }

  CIEC_ANY *FORTE_SCAN_PROBE::getDO(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_LAST_DT_10US;
      case 1: return &var_MAX_DT_10US;
      case 2: return &var_LAST_EXEC_US;
      case 3: return &var_SCAN_COUNT;
    }
    return nullptr;
  }

  CEventConnection *FORTE_SCAN_PROBE::getEOConUnchecked(const TPortId paIndex) {
    return paIndex == 0 ? &conn_CNF : nullptr;
  }

  CDataConnection **FORTE_SCAN_PROBE::getDIConUnchecked(const TPortId) {
    return nullptr;
  }

  CDataConnection *FORTE_SCAN_PROBE::getDOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_LAST_DT_10US;
      case 1: return &conn_MAX_DT_10US;
      case 2: return &conn_LAST_EXEC_US;
      case 3: return &conn_SCAN_COUNT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_SCAN_PROBE::getVarInternal(const size_t) {
    return nullptr;
  }
} // namespace forte::st2fb
