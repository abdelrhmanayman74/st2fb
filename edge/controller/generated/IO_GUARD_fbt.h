#pragma once

#include "forte/basicfb.h"
#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_real.h"
#include "forte/datatypes/forte_time.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"

namespace forte::st2fb {
  class FORTE_IO_GUARD final : public CBasicFB {
      DECLARE_FIRMWARE_FB(FORTE_IO_GUARD)

    private:
      static const TEventID scmEventREQID = 0;
      static const TEventID scmEventCNFID = 0;

      CIEC_UINT var_LAST_HEARTBEAT;
      CIEC_REAL var_LAST_LEVEL;
      CIEC_BOOL var_SEEN_BEAT;
      CIEC_BOOL var_UNCHANGED;
      CIEC_REAL var_DELTA;
      CIEC_TIME var_ST2FB_NOW;
      CIEC_BOOL var_COMMS_TIMER_IN;
      CIEC_TIME var_COMMS_TIMER_PT;
      CIEC_BOOL var_COMMS_TIMER_Q;
      CIEC_TIME var_COMMS_TIMER_ET;
      CIEC_INT var_COMMS_TIMER_STATE;
      CIEC_BOOL var_COMMS_TIMER_PREV_IN;
      CIEC_TIME var_COMMS_TIMER_START_TIME;
      CIEC_BOOL var_STUCK_TIMER_IN;
      CIEC_TIME var_STUCK_TIMER_PT;
      CIEC_BOOL var_STUCK_TIMER_Q;
      CIEC_TIME var_STUCK_TIMER_ET;
      CIEC_INT var_STUCK_TIMER_STATE;
      CIEC_BOOL var_STUCK_TIMER_PREV_IN;
      CIEC_TIME var_STUCK_TIMER_START_TIME;
      CIEC_BOOL var_ACK_EDGE_CLK;
      CIEC_BOOL var_ACK_EDGE_Q;
      CIEC_BOOL var_ACK_EDGE_M;
      CIEC_BOOL var_FAULT_LATCH_S1;
      CIEC_BOOL var_FAULT_LATCH_R;
      CIEC_BOOL var_FAULT_LATCH_Q1;

      CIEC_ANY *getVarInternal(size_t) override;

      void alg_scan(void);

      static const TForteInt16 scmStateSTART = 0;
      static const TForteInt16 scmStateRUN = 1;

      void enterStateSTART(CEventChainExecutionThread *const paECET);
      void enterStateRUN(CEventChainExecutionThread *const paECET);

      void executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) override;

      void readInputData(TEventID paEIID) override;
      void writeOutputData(TEventID paEIID) override;
      void setInitialValues() override;

    public:
      FORTE_IO_GUARD(StringId paInstanceNameId, CFBContainer &paContainer);

      CIEC_UINT var_R_AUTO;
      CIEC_UINT var_R_ACK;
      CIEC_UINT var_R_FB_1;
      CIEC_UINT var_R_FB_2;
      CIEC_UINT var_R_TRIP_1;
      CIEC_UINT var_R_TRIP_2;
      CIEC_UINT var_HEARTBEAT;
      CIEC_REAL var_RAW_LEVEL;
      CIEC_REAL var_STUCK_EPS;
      CIEC_TIME var_COMMS_TIMEOUT;
      CIEC_TIME var_STUCK_TIME;
      CIEC_TIME var_SCAN_DT;
      CIEC_BOOL var_AUTO_MODE;
      CIEC_BOOL var_ACK;
      CIEC_BOOL var_FB_1;
      CIEC_BOOL var_FB_2;
      CIEC_BOOL var_TRIP_1;
      CIEC_BOOL var_TRIP_2;
      CIEC_BOOL var_COMMS_OK;
      CIEC_BOOL var_SENSOR_FAULT;

      CEventConnection conn_CNF;

      CDataConnection *conn_R_AUTO;
      CDataConnection *conn_R_ACK;
      CDataConnection *conn_R_FB_1;
      CDataConnection *conn_R_FB_2;
      CDataConnection *conn_R_TRIP_1;
      CDataConnection *conn_R_TRIP_2;
      CDataConnection *conn_HEARTBEAT;
      CDataConnection *conn_RAW_LEVEL;
      CDataConnection *conn_STUCK_EPS;
      CDataConnection *conn_COMMS_TIMEOUT;
      CDataConnection *conn_STUCK_TIME;
      CDataConnection *conn_SCAN_DT;

      COutDataConnection<CIEC_BOOL> conn_AUTO_MODE;
      COutDataConnection<CIEC_BOOL> conn_ACK;
      COutDataConnection<CIEC_BOOL> conn_FB_1;
      COutDataConnection<CIEC_BOOL> conn_FB_2;
      COutDataConnection<CIEC_BOOL> conn_TRIP_1;
      COutDataConnection<CIEC_BOOL> conn_TRIP_2;
      COutDataConnection<CIEC_BOOL> conn_COMMS_OK;
      COutDataConnection<CIEC_BOOL> conn_SENSOR_FAULT;

      CIEC_ANY *getDI(size_t) override;
      CIEC_ANY *getDO(size_t) override;
      CEventConnection *getEOConUnchecked(TPortId) override;
      CDataConnection **getDIConUnchecked(TPortId) override;
      CDataConnection *getDOConUnchecked(TPortId) override;
  };
} // namespace forte::st2fb
