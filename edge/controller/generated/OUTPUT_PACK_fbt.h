#pragma once

#include "forte/basicfb.h"
#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"

namespace forte::st2fb {
  class FORTE_OUTPUT_PACK final : public CBasicFB {
      DECLARE_FIRMWARE_FB(FORTE_OUTPUT_PACK)

    private:
      static const TEventID scmEventREQID = 0;
      static const TEventID scmEventCNFID = 0;


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
      FORTE_OUTPUT_PACK(StringId paInstanceNameId, CFBContainer &paContainer);

      CIEC_UINT var_EPOCH;
      CIEC_BOOL var_PUMP_1;
      CIEC_BOOL var_PUMP_2;
      CIEC_INT var_STATE_NO;
      CIEC_BOOL var_LEAD_IS_2;
      CIEC_BOOL var_HIGH_ALARM;
      CIEC_BOOL var_STATION_FAULT;
      CIEC_BOOL var_COMMS_OK;
      CIEC_BOOL var_SENSOR_FAULT;
      CIEC_UINT var_W_TOKEN;
      CIEC_UINT var_W_PUMP_1;
      CIEC_UINT var_W_PUMP_2;
      CIEC_UINT var_W_STATE_NO;
      CIEC_UINT var_W_LEAD_IS_2;
      CIEC_UINT var_W_HIGH_ALARM;
      CIEC_UINT var_W_STATION_FAULT;
      CIEC_UINT var_W_COMMS_OK;
      CIEC_UINT var_W_SENSOR_FAULT;

      CEventConnection conn_CNF;

      CDataConnection *conn_EPOCH;
      CDataConnection *conn_PUMP_1;
      CDataConnection *conn_PUMP_2;
      CDataConnection *conn_STATE_NO;
      CDataConnection *conn_LEAD_IS_2;
      CDataConnection *conn_HIGH_ALARM;
      CDataConnection *conn_STATION_FAULT;
      CDataConnection *conn_COMMS_OK;
      CDataConnection *conn_SENSOR_FAULT;

      COutDataConnection<CIEC_UINT> conn_W_TOKEN;
      COutDataConnection<CIEC_UINT> conn_W_PUMP_1;
      COutDataConnection<CIEC_UINT> conn_W_PUMP_2;
      COutDataConnection<CIEC_UINT> conn_W_STATE_NO;
      COutDataConnection<CIEC_UINT> conn_W_LEAD_IS_2;
      COutDataConnection<CIEC_UINT> conn_W_HIGH_ALARM;
      COutDataConnection<CIEC_UINT> conn_W_STATION_FAULT;
      COutDataConnection<CIEC_UINT> conn_W_COMMS_OK;
      COutDataConnection<CIEC_UINT> conn_W_SENSOR_FAULT;

      CIEC_ANY *getDI(size_t) override;
      CIEC_ANY *getDO(size_t) override;
      CEventConnection *getEOConUnchecked(TPortId) override;
      CDataConnection **getDIConUnchecked(TPortId) override;
      CDataConnection *getDOConUnchecked(TPortId) override;
  };
} // namespace forte::st2fb
