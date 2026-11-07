// Hand-written diagnostic FB, not migrated from ST: migrated FBs must never read a clock, this one exists
// to read it. It shows what the cycle really does, against the SCAN_DT constant the control logic assumes.
//   REQ  arrival of the cycle event (E_CYCLE.EO); emits CNF to start the scan.
//   END  all of the scan's work is done, including the blocking Modbus write.
// Optional raw log: set ST2FB_SCAN_LOG to a path; see SCAN_PROBE_fbt.cpp for the record format.
#pragma once

#include "forte/basicfb.h"
#include "forte/datatypes/forte_uint.h"

namespace forte::st2fb {
  class FORTE_SCAN_PROBE final : public CBasicFB {
      DECLARE_FIRMWARE_FB(FORTE_SCAN_PROBE)

    private:
      static const TEventID scmEventREQID = 0;
      static const TEventID scmEventENDID = 1;
      static const TEventID scmEventCNFID = 0;

      unsigned long long mLastReqNs = 0;
      unsigned long long mScanStartNs = 0;
      unsigned mLastExecUs = 0;

      CIEC_ANY *getVarInternal(size_t) override;
      void executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) override;
      void readInputData(TEventID paEIID) override;
      void writeOutputData(TEventID paEIID) override;
      void setInitialValues() override;

    public:
      FORTE_SCAN_PROBE(StringId paInstanceNameId, CFBContainer &paContainer);

      CIEC_UINT var_LAST_DT_10US;
      CIEC_UINT var_MAX_DT_10US;
      CIEC_UINT var_LAST_EXEC_US;
      CIEC_UINT var_SCAN_COUNT;

      CEventConnection conn_CNF;

      COutDataConnection<CIEC_UINT> conn_LAST_DT_10US;
      COutDataConnection<CIEC_UINT> conn_MAX_DT_10US;
      COutDataConnection<CIEC_UINT> conn_LAST_EXEC_US;
      COutDataConnection<CIEC_UINT> conn_SCAN_COUNT;

      CIEC_ANY *getDI(size_t) override;
      CIEC_ANY *getDO(size_t) override;
      CEventConnection *getEOConUnchecked(TPortId) override;
      CDataConnection **getDIConUnchecked(TPortId) override;
      CDataConnection *getDOConUnchecked(TPortId) override;
  };
} // namespace forte::st2fb
