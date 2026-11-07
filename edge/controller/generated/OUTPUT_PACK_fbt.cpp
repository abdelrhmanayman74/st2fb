#include "OUTPUT_PACK_fbt.h"

#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"
#include "forte/iec61131_functions/func_BOOL_TO_UINT.h"
#include "forte/iec61131_functions/func_INT_TO_UINT.h"

using namespace forte::literals;

namespace forte::st2fb {
  namespace {
    const auto cEventInputNames = std::array{"REQ"_STRID};
    const auto cEventOutputNames = std::array{"CNF"_STRID};
    const auto cDataInputNames = std::array{"EPOCH"_STRID, "PUMP_1"_STRID, "PUMP_2"_STRID, "STATE_NO"_STRID, "LEAD_IS_2"_STRID, "HIGH_ALARM"_STRID, "STATION_FAULT"_STRID, "COMMS_OK"_STRID, "SENSOR_FAULT"_STRID};
    const auto cDataOutputNames = std::array{"W_TOKEN"_STRID, "W_PUMP_1"_STRID, "W_PUMP_2"_STRID, "W_STATE_NO"_STRID, "W_LEAD_IS_2"_STRID, "W_HIGH_ALARM"_STRID, "W_STATION_FAULT"_STRID, "W_COMMS_OK"_STRID, "W_SENSOR_FAULT"_STRID};
    const std::array<StringId, 0> cInternalsNames{};
    const SFBInterfaceSpec cFBInterfaceSpec = {
        .mEINames = cEventInputNames,
        .mEITypeNames = {},
        .mEONames = cEventOutputNames,
        .mEOTypeNames = {},
        .mDINames = cDataInputNames,
        .mDONames = cDataOutputNames,
        .mDIONames = {},
        .mSocketNames = {},
        .mPlugNames = {},
    };
  } // namespace

  DEFINE_FIRMWARE_FB(FORTE_OUTPUT_PACK, "st2fb::OUTPUT_PACK"_STRID)

  FORTE_OUTPUT_PACK::FORTE_OUTPUT_PACK(const StringId paInstanceNameId, CFBContainer &paContainer) :
      CBasicFB(paContainer, cFBInterfaceSpec, paInstanceNameId, cInternalsNames),
      var_EPOCH(0_UINT),
      var_PUMP_1(0_BOOL),
      var_PUMP_2(0_BOOL),
      var_STATE_NO(0_INT),
      var_LEAD_IS_2(0_BOOL),
      var_HIGH_ALARM(0_BOOL),
      var_STATION_FAULT(0_BOOL),
      var_COMMS_OK(0_BOOL),
      var_SENSOR_FAULT(0_BOOL),
      var_W_TOKEN(0_UINT),
      var_W_PUMP_1(0_UINT),
      var_W_PUMP_2(0_UINT),
      var_W_STATE_NO(0_UINT),
      var_W_LEAD_IS_2(0_UINT),
      var_W_HIGH_ALARM(0_UINT),
      var_W_STATION_FAULT(0_UINT),
      var_W_COMMS_OK(0_UINT),
      var_W_SENSOR_FAULT(0_UINT),
      conn_CNF(*this, 0),
      conn_EPOCH(nullptr),
      conn_PUMP_1(nullptr),
      conn_PUMP_2(nullptr),
      conn_STATE_NO(nullptr),
      conn_LEAD_IS_2(nullptr),
      conn_HIGH_ALARM(nullptr),
      conn_STATION_FAULT(nullptr),
      conn_COMMS_OK(nullptr),
      conn_SENSOR_FAULT(nullptr),
      conn_W_TOKEN(*this, 0, var_W_TOKEN),
      conn_W_PUMP_1(*this, 1, var_W_PUMP_1),
      conn_W_PUMP_2(*this, 2, var_W_PUMP_2),
      conn_W_STATE_NO(*this, 3, var_W_STATE_NO),
      conn_W_LEAD_IS_2(*this, 4, var_W_LEAD_IS_2),
      conn_W_HIGH_ALARM(*this, 5, var_W_HIGH_ALARM),
      conn_W_STATION_FAULT(*this, 6, var_W_STATION_FAULT),
      conn_W_COMMS_OK(*this, 7, var_W_COMMS_OK),
      conn_W_SENSOR_FAULT(*this, 8, var_W_SENSOR_FAULT) {
  }

  void FORTE_OUTPUT_PACK::setInitialValues() {
    CBasicFB::setInitialValues();
    var_EPOCH = 0_UINT;
    var_PUMP_1 = 0_BOOL;
    var_PUMP_2 = 0_BOOL;
    var_STATE_NO = 0_INT;
    var_LEAD_IS_2 = 0_BOOL;
    var_HIGH_ALARM = 0_BOOL;
    var_STATION_FAULT = 0_BOOL;
    var_COMMS_OK = 0_BOOL;
    var_SENSOR_FAULT = 0_BOOL;
    var_W_TOKEN = 0_UINT;
    var_W_PUMP_1 = 0_UINT;
    var_W_PUMP_2 = 0_UINT;
    var_W_STATE_NO = 0_UINT;
    var_W_LEAD_IS_2 = 0_UINT;
    var_W_HIGH_ALARM = 0_UINT;
    var_W_STATION_FAULT = 0_UINT;
    var_W_COMMS_OK = 0_UINT;
    var_W_SENSOR_FAULT = 0_UINT;
  }

  void FORTE_OUTPUT_PACK::executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) {
    do {
      switch (mECCState) {
        case scmStateSTART:
          if (scmEventREQID == paEIID)
            enterStateRUN(paECET);
          else
            return; // no transition cleared
          break;
        case scmStateRUN:
          if (1)
            enterStateSTART(paECET);
          else
            return; // no transition cleared
          break;
        default:
          DEVLOG_ERROR("The state is not in the valid range! The state value is: %d. The max value can be: 2.",
                       mECCState.operator TForteUInt16());
          mECCState = 0; // 0 is always the initial state
          return;
      }
      paEIID = cgInvalidEventID; // we have to clear the event after the first check in order to ensure correct behavior
    } while (true);
  }

  void FORTE_OUTPUT_PACK::enterStateSTART(CEventChainExecutionThread *const ) {
    mECCState = scmStateSTART;
  }

  void FORTE_OUTPUT_PACK::enterStateRUN(CEventChainExecutionThread *const paECET) {
    mECCState = scmStateRUN;
    alg_scan();
    sendOutputEvent(scmEventCNFID, paECET);
  }

  void FORTE_OUTPUT_PACK::readInputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventREQID: {
        readData(0, var_EPOCH, conn_EPOCH);
        readData(1, var_PUMP_1, conn_PUMP_1);
        readData(2, var_PUMP_2, conn_PUMP_2);
        readData(3, var_STATE_NO, conn_STATE_NO);
        readData(4, var_LEAD_IS_2, conn_LEAD_IS_2);
        readData(5, var_HIGH_ALARM, conn_HIGH_ALARM);
        readData(6, var_STATION_FAULT, conn_STATION_FAULT);
        readData(7, var_COMMS_OK, conn_COMMS_OK);
        readData(8, var_SENSOR_FAULT, conn_SENSOR_FAULT);
        break;
      }
      default: break;
    }
  }

  void FORTE_OUTPUT_PACK::writeOutputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventCNFID: {
        writeData(cFBInterfaceSpec.getNumDIs() + 0, var_W_TOKEN, conn_W_TOKEN);
        writeData(cFBInterfaceSpec.getNumDIs() + 1, var_W_PUMP_1, conn_W_PUMP_1);
        writeData(cFBInterfaceSpec.getNumDIs() + 2, var_W_PUMP_2, conn_W_PUMP_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 3, var_W_STATE_NO, conn_W_STATE_NO);
        writeData(cFBInterfaceSpec.getNumDIs() + 4, var_W_LEAD_IS_2, conn_W_LEAD_IS_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 5, var_W_HIGH_ALARM, conn_W_HIGH_ALARM);
        writeData(cFBInterfaceSpec.getNumDIs() + 6, var_W_STATION_FAULT, conn_W_STATION_FAULT);
        writeData(cFBInterfaceSpec.getNumDIs() + 7, var_W_COMMS_OK, conn_W_COMMS_OK);
        writeData(cFBInterfaceSpec.getNumDIs() + 8, var_W_SENSOR_FAULT, conn_W_SENSOR_FAULT);
        break;
      }
      default: break;
    }
  }

  CIEC_ANY *FORTE_OUTPUT_PACK::getDI(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_EPOCH;
      case 1: return &var_PUMP_1;
      case 2: return &var_PUMP_2;
      case 3: return &var_STATE_NO;
      case 4: return &var_LEAD_IS_2;
      case 5: return &var_HIGH_ALARM;
      case 6: return &var_STATION_FAULT;
      case 7: return &var_COMMS_OK;
      case 8: return &var_SENSOR_FAULT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_OUTPUT_PACK::getDO(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_W_TOKEN;
      case 1: return &var_W_PUMP_1;
      case 2: return &var_W_PUMP_2;
      case 3: return &var_W_STATE_NO;
      case 4: return &var_W_LEAD_IS_2;
      case 5: return &var_W_HIGH_ALARM;
      case 6: return &var_W_STATION_FAULT;
      case 7: return &var_W_COMMS_OK;
      case 8: return &var_W_SENSOR_FAULT;
    }
    return nullptr;
  }

  CEventConnection *FORTE_OUTPUT_PACK::getEOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_CNF;
    }
    return nullptr;
  }

  CDataConnection **FORTE_OUTPUT_PACK::getDIConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_EPOCH;
      case 1: return &conn_PUMP_1;
      case 2: return &conn_PUMP_2;
      case 3: return &conn_STATE_NO;
      case 4: return &conn_LEAD_IS_2;
      case 5: return &conn_HIGH_ALARM;
      case 6: return &conn_STATION_FAULT;
      case 7: return &conn_COMMS_OK;
      case 8: return &conn_SENSOR_FAULT;
    }
    return nullptr;
  }

  CDataConnection *FORTE_OUTPUT_PACK::getDOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_W_TOKEN;
      case 1: return &conn_W_PUMP_1;
      case 2: return &conn_W_PUMP_2;
      case 3: return &conn_W_STATE_NO;
      case 4: return &conn_W_LEAD_IS_2;
      case 5: return &conn_W_HIGH_ALARM;
      case 6: return &conn_W_STATION_FAULT;
      case 7: return &conn_W_COMMS_OK;
      case 8: return &conn_W_SENSOR_FAULT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_OUTPUT_PACK::getVarInternal(const size_t) {
    return nullptr;
  }

  void FORTE_OUTPUT_PACK::alg_scan(void) {
#line 1 "OUTPUT_PACK.fbt"
    var_W_TOKEN = var_EPOCH;
#line 2 "OUTPUT_PACK.fbt"
    var_W_PUMP_1 = func_BOOL_TO_UINT(var_PUMP_1);
#line 3 "OUTPUT_PACK.fbt"
    var_W_PUMP_2 = func_BOOL_TO_UINT(var_PUMP_2);
#line 4 "OUTPUT_PACK.fbt"
    var_W_STATE_NO = func_INT_TO_UINT(var_STATE_NO);
#line 5 "OUTPUT_PACK.fbt"
    var_W_LEAD_IS_2 = func_BOOL_TO_UINT(var_LEAD_IS_2);
#line 6 "OUTPUT_PACK.fbt"
    var_W_HIGH_ALARM = func_BOOL_TO_UINT(var_HIGH_ALARM);
#line 7 "OUTPUT_PACK.fbt"
    var_W_STATION_FAULT = func_BOOL_TO_UINT(var_STATION_FAULT);
#line 8 "OUTPUT_PACK.fbt"
    var_W_COMMS_OK = func_BOOL_TO_UINT(var_COMMS_OK);
#line 9 "OUTPUT_PACK.fbt"
    var_W_SENSOR_FAULT = func_BOOL_TO_UINT(var_SENSOR_FAULT);
  }

} // namespace forte::st2fb
