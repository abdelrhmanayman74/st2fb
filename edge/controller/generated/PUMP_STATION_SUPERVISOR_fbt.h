#pragma once

#include "forte/basicfb.h"
#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_dint.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_real.h"
#include "forte/datatypes/forte_time.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"

namespace forte::st2fb {
  class FORTE_PUMP_STATION_SUPERVISOR final : public CBasicFB {
      DECLARE_FIRMWARE_FB(FORTE_PUMP_STATION_SUPERVISOR)

    private:
      static const TEventID scmEventREQID = 0;
      static const TEventID scmEventCNFID = 0;

      CIEC_INT var_PASSES;
      CIEC_INT var_I;
      CIEC_REAL var_STEP_SIZE;
      CIEC_REAL var_PENDING;
      CIEC_BOOL var_LEAD_RUNNING_FB;
      CIEC_BOOL var_LEAD_FAILED;
      CIEC_BOOL var_LAG_FAILED;
      CIEC_TIME var_ST2FB_NOW;
      CIEC_BOOL var_FAILED_1_S1;
      CIEC_BOOL var_FAILED_1_R;
      CIEC_BOOL var_FAILED_1_Q1;
      CIEC_BOOL var_FAILED_2_S1;
      CIEC_BOOL var_FAILED_2_R;
      CIEC_BOOL var_FAILED_2_Q1;
      CIEC_BOOL var_PROOF_TIMER_IN;
      CIEC_TIME var_PROOF_TIMER_PT;
      CIEC_BOOL var_PROOF_TIMER_Q;
      CIEC_TIME var_PROOF_TIMER_ET;
      CIEC_INT var_PROOF_TIMER_STATE;
      CIEC_BOOL var_PROOF_TIMER_PREV_IN;
      CIEC_TIME var_PROOF_TIMER_START_TIME;
      CIEC_BOOL var_ALARM_TIMER_IN;
      CIEC_TIME var_ALARM_TIMER_PT;
      CIEC_BOOL var_ALARM_TIMER_Q;
      CIEC_TIME var_ALARM_TIMER_ET;
      CIEC_INT var_ALARM_TIMER_STATE;
      CIEC_BOOL var_ALARM_TIMER_PREV_IN;
      CIEC_TIME var_ALARM_TIMER_START_TIME;
      CIEC_BOOL var_ACK_EDGE_CLK;
      CIEC_BOOL var_ACK_EDGE_Q;
      CIEC_BOOL var_ACK_EDGE_M;

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
      FORTE_PUMP_STATION_SUPERVISOR(StringId paInstanceNameId, CFBContainer &paContainer);

      CIEC_BOOL var_AUTO_MODE;
      CIEC_BOOL var_ACK;
      CIEC_REAL var_RAW_LEVEL;
      CIEC_REAL var_STOP_LEVEL;
      CIEC_REAL var_START_LEVEL;
      CIEC_REAL var_LAG_LEVEL;
      CIEC_REAL var_HIGH_LEVEL;
      CIEC_BOOL var_FB_1;
      CIEC_BOOL var_FB_2;
      CIEC_BOOL var_TRIP_1;
      CIEC_BOOL var_TRIP_2;
      CIEC_REAL var_FLOW;
      CIEC_REAL var_SCAN_HOURS;
      CIEC_REAL var_PULSE_SIZE;
      CIEC_TIME var_PROOF_TIME;
      CIEC_TIME var_ALARM_DELAY;
      CIEC_TIME var_SCAN_DT;
      CIEC_INT var_STATE_NO;
      CIEC_BOOL var_PUMP_1;
      CIEC_BOOL var_PUMP_2;
      CIEC_BOOL var_LEAD_IS_2;
      CIEC_BOOL var_HIGH_ALARM;
      CIEC_BOOL var_STATION_FAULT;
      CIEC_REAL var_FILTERED_LEVEL;
      CIEC_REAL var_TOTAL;
      CIEC_DINT var_PULSES;
      CIEC_UINT var_STARTS;

      CEventConnection conn_CNF;

      CDataConnection *conn_AUTO_MODE;
      CDataConnection *conn_ACK;
      CDataConnection *conn_RAW_LEVEL;
      CDataConnection *conn_STOP_LEVEL;
      CDataConnection *conn_START_LEVEL;
      CDataConnection *conn_LAG_LEVEL;
      CDataConnection *conn_HIGH_LEVEL;
      CDataConnection *conn_FB_1;
      CDataConnection *conn_FB_2;
      CDataConnection *conn_TRIP_1;
      CDataConnection *conn_TRIP_2;
      CDataConnection *conn_FLOW;
      CDataConnection *conn_SCAN_HOURS;
      CDataConnection *conn_PULSE_SIZE;
      CDataConnection *conn_PROOF_TIME;
      CDataConnection *conn_ALARM_DELAY;
      CDataConnection *conn_SCAN_DT;

      COutDataConnection<CIEC_INT> conn_STATE_NO;
      COutDataConnection<CIEC_BOOL> conn_PUMP_1;
      COutDataConnection<CIEC_BOOL> conn_PUMP_2;
      COutDataConnection<CIEC_BOOL> conn_LEAD_IS_2;
      COutDataConnection<CIEC_BOOL> conn_HIGH_ALARM;
      COutDataConnection<CIEC_BOOL> conn_STATION_FAULT;
      COutDataConnection<CIEC_REAL> conn_FILTERED_LEVEL;
      COutDataConnection<CIEC_REAL> conn_TOTAL;
      COutDataConnection<CIEC_DINT> conn_PULSES;
      COutDataConnection<CIEC_UINT> conn_STARTS;

      CIEC_ANY *getDI(size_t) override;
      CIEC_ANY *getDO(size_t) override;
      CEventConnection *getEOConUnchecked(TPortId) override;
      CDataConnection **getDIConUnchecked(TPortId) override;
      CDataConnection *getDOConUnchecked(TPortId) override;
  };
} // namespace forte::st2fb
