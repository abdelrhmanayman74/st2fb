#include "IO_GUARD_fbt.h"

#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_real.h"
#include "forte/datatypes/forte_time.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"
#include "forte/iec61131_functions/func_ADD.h"
#include "forte/iec61131_functions/func_AND.h"
#include "forte/iec61131_functions/func_EQ.h"
#include "forte/iec61131_functions/func_GE.h"
#include "forte/iec61131_functions/func_LE.h"
#include "forte/iec61131_functions/func_MINUS.h"
#include "forte/iec61131_functions/func_NE.h"
#include "forte/iec61131_functions/func_NOT.h"
#include "forte/iec61131_functions/func_OR.h"
#include "forte/iec61131_functions/func_SUB.h"

using namespace forte::literals;

namespace forte::st2fb {
  namespace {
    const auto cEventInputNames = std::array{"REQ"_STRID};
    const auto cEventOutputNames = std::array{"CNF"_STRID};
    const auto cDataInputNames = std::array{"R_AUTO"_STRID, "R_ACK"_STRID, "R_FB_1"_STRID, "R_FB_2"_STRID, "R_TRIP_1"_STRID, "R_TRIP_2"_STRID, "HEARTBEAT"_STRID, "RAW_LEVEL"_STRID, "STUCK_EPS"_STRID, "COMMS_TIMEOUT"_STRID, "STUCK_TIME"_STRID, "SCAN_DT"_STRID};
    const auto cDataOutputNames = std::array{"AUTO_MODE"_STRID, "ACK"_STRID, "FB_1"_STRID, "FB_2"_STRID, "TRIP_1"_STRID, "TRIP_2"_STRID, "COMMS_OK"_STRID, "SENSOR_FAULT"_STRID};
    const auto cInternalsNames = std::array{"LAST_HEARTBEAT"_STRID, "LAST_LEVEL"_STRID, "SEEN_BEAT"_STRID, "UNCHANGED"_STRID, "DELTA"_STRID, "ST2FB_NOW"_STRID, "COMMS_TIMER_IN"_STRID, "COMMS_TIMER_PT"_STRID, "COMMS_TIMER_Q"_STRID, "COMMS_TIMER_ET"_STRID, "COMMS_TIMER_STATE"_STRID, "COMMS_TIMER_PREV_IN"_STRID, "COMMS_TIMER_START_TIME"_STRID, "STUCK_TIMER_IN"_STRID, "STUCK_TIMER_PT"_STRID, "STUCK_TIMER_Q"_STRID, "STUCK_TIMER_ET"_STRID, "STUCK_TIMER_STATE"_STRID, "STUCK_TIMER_PREV_IN"_STRID, "STUCK_TIMER_START_TIME"_STRID, "ACK_EDGE_CLK"_STRID, "ACK_EDGE_Q"_STRID, "ACK_EDGE_M"_STRID, "FAULT_LATCH_S1"_STRID, "FAULT_LATCH_R"_STRID, "FAULT_LATCH_Q1"_STRID};
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

  DEFINE_FIRMWARE_FB(FORTE_IO_GUARD, "st2fb::IO_GUARD"_STRID)

  FORTE_IO_GUARD::FORTE_IO_GUARD(const StringId paInstanceNameId, CFBContainer &paContainer) :
      CBasicFB(paContainer, cFBInterfaceSpec, paInstanceNameId, cInternalsNames),
      var_LAST_HEARTBEAT(0_UINT),
      var_LAST_LEVEL(0_REAL),
      var_SEEN_BEAT(0_BOOL),
      var_UNCHANGED(0_BOOL),
      var_DELTA(0_REAL),
      var_ST2FB_NOW(0_TIME),
      var_COMMS_TIMER_IN(0_BOOL),
      var_COMMS_TIMER_PT(0_TIME),
      var_COMMS_TIMER_Q(0_BOOL),
      var_COMMS_TIMER_ET(0_TIME),
      var_COMMS_TIMER_STATE(0_INT),
      var_COMMS_TIMER_PREV_IN(0_BOOL),
      var_COMMS_TIMER_START_TIME(0_TIME),
      var_STUCK_TIMER_IN(0_BOOL),
      var_STUCK_TIMER_PT(0_TIME),
      var_STUCK_TIMER_Q(0_BOOL),
      var_STUCK_TIMER_ET(0_TIME),
      var_STUCK_TIMER_STATE(0_INT),
      var_STUCK_TIMER_PREV_IN(0_BOOL),
      var_STUCK_TIMER_START_TIME(0_TIME),
      var_ACK_EDGE_CLK(0_BOOL),
      var_ACK_EDGE_Q(0_BOOL),
      var_ACK_EDGE_M(0_BOOL),
      var_FAULT_LATCH_S1(0_BOOL),
      var_FAULT_LATCH_R(0_BOOL),
      var_FAULT_LATCH_Q1(0_BOOL),
      var_R_AUTO(0_UINT),
      var_R_ACK(0_UINT),
      var_R_FB_1(0_UINT),
      var_R_FB_2(0_UINT),
      var_R_TRIP_1(0_UINT),
      var_R_TRIP_2(0_UINT),
      var_HEARTBEAT(0_UINT),
      var_RAW_LEVEL(0_REAL),
      var_STUCK_EPS(0_REAL),
      var_COMMS_TIMEOUT(0_TIME),
      var_STUCK_TIME(0_TIME),
      var_SCAN_DT(0_TIME),
      var_AUTO_MODE(0_BOOL),
      var_ACK(0_BOOL),
      var_FB_1(0_BOOL),
      var_FB_2(0_BOOL),
      var_TRIP_1(0_BOOL),
      var_TRIP_2(0_BOOL),
      var_COMMS_OK(0_BOOL),
      var_SENSOR_FAULT(0_BOOL),
      conn_CNF(*this, 0),
      conn_R_AUTO(nullptr),
      conn_R_ACK(nullptr),
      conn_R_FB_1(nullptr),
      conn_R_FB_2(nullptr),
      conn_R_TRIP_1(nullptr),
      conn_R_TRIP_2(nullptr),
      conn_HEARTBEAT(nullptr),
      conn_RAW_LEVEL(nullptr),
      conn_STUCK_EPS(nullptr),
      conn_COMMS_TIMEOUT(nullptr),
      conn_STUCK_TIME(nullptr),
      conn_SCAN_DT(nullptr),
      conn_AUTO_MODE(*this, 0, var_AUTO_MODE),
      conn_ACK(*this, 1, var_ACK),
      conn_FB_1(*this, 2, var_FB_1),
      conn_FB_2(*this, 3, var_FB_2),
      conn_TRIP_1(*this, 4, var_TRIP_1),
      conn_TRIP_2(*this, 5, var_TRIP_2),
      conn_COMMS_OK(*this, 6, var_COMMS_OK),
      conn_SENSOR_FAULT(*this, 7, var_SENSOR_FAULT) {
  }

  void FORTE_IO_GUARD::setInitialValues() {
    CBasicFB::setInitialValues();
    var_LAST_HEARTBEAT = 0_UINT;
    var_LAST_LEVEL = 0_REAL;
    var_SEEN_BEAT = 0_BOOL;
    var_UNCHANGED = 0_BOOL;
    var_DELTA = 0_REAL;
    var_ST2FB_NOW = 0_TIME;
    var_COMMS_TIMER_IN = 0_BOOL;
    var_COMMS_TIMER_PT = 0_TIME;
    var_COMMS_TIMER_Q = 0_BOOL;
    var_COMMS_TIMER_ET = 0_TIME;
    var_COMMS_TIMER_STATE = 0_INT;
    var_COMMS_TIMER_PREV_IN = 0_BOOL;
    var_COMMS_TIMER_START_TIME = 0_TIME;
    var_STUCK_TIMER_IN = 0_BOOL;
    var_STUCK_TIMER_PT = 0_TIME;
    var_STUCK_TIMER_Q = 0_BOOL;
    var_STUCK_TIMER_ET = 0_TIME;
    var_STUCK_TIMER_STATE = 0_INT;
    var_STUCK_TIMER_PREV_IN = 0_BOOL;
    var_STUCK_TIMER_START_TIME = 0_TIME;
    var_ACK_EDGE_CLK = 0_BOOL;
    var_ACK_EDGE_Q = 0_BOOL;
    var_ACK_EDGE_M = 0_BOOL;
    var_FAULT_LATCH_S1 = 0_BOOL;
    var_FAULT_LATCH_R = 0_BOOL;
    var_FAULT_LATCH_Q1 = 0_BOOL;
    var_R_AUTO = 0_UINT;
    var_R_ACK = 0_UINT;
    var_R_FB_1 = 0_UINT;
    var_R_FB_2 = 0_UINT;
    var_R_TRIP_1 = 0_UINT;
    var_R_TRIP_2 = 0_UINT;
    var_HEARTBEAT = 0_UINT;
    var_RAW_LEVEL = 0_REAL;
    var_STUCK_EPS = 0_REAL;
    var_COMMS_TIMEOUT = 0_TIME;
    var_STUCK_TIME = 0_TIME;
    var_SCAN_DT = 0_TIME;
    var_AUTO_MODE = 0_BOOL;
    var_ACK = 0_BOOL;
    var_FB_1 = 0_BOOL;
    var_FB_2 = 0_BOOL;
    var_TRIP_1 = 0_BOOL;
    var_TRIP_2 = 0_BOOL;
    var_COMMS_OK = 0_BOOL;
    var_SENSOR_FAULT = 0_BOOL;
  }

  void FORTE_IO_GUARD::executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) {
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

  void FORTE_IO_GUARD::enterStateSTART(CEventChainExecutionThread *const ) {
    mECCState = scmStateSTART;
  }

  void FORTE_IO_GUARD::enterStateRUN(CEventChainExecutionThread *const paECET) {
    mECCState = scmStateRUN;
    alg_scan();
    sendOutputEvent(scmEventCNFID, paECET);
  }

  void FORTE_IO_GUARD::readInputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventREQID: {
        readData(0, var_R_AUTO, conn_R_AUTO);
        readData(1, var_R_ACK, conn_R_ACK);
        readData(2, var_R_FB_1, conn_R_FB_1);
        readData(3, var_R_FB_2, conn_R_FB_2);
        readData(4, var_R_TRIP_1, conn_R_TRIP_1);
        readData(5, var_R_TRIP_2, conn_R_TRIP_2);
        readData(6, var_HEARTBEAT, conn_HEARTBEAT);
        readData(7, var_RAW_LEVEL, conn_RAW_LEVEL);
        readData(8, var_STUCK_EPS, conn_STUCK_EPS);
        readData(9, var_COMMS_TIMEOUT, conn_COMMS_TIMEOUT);
        readData(10, var_STUCK_TIME, conn_STUCK_TIME);
        readData(11, var_SCAN_DT, conn_SCAN_DT);
        break;
      }
      default: break;
    }
  }

  void FORTE_IO_GUARD::writeOutputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventCNFID: {
        writeData(cFBInterfaceSpec.getNumDIs() + 0, var_AUTO_MODE, conn_AUTO_MODE);
        writeData(cFBInterfaceSpec.getNumDIs() + 1, var_ACK, conn_ACK);
        writeData(cFBInterfaceSpec.getNumDIs() + 2, var_FB_1, conn_FB_1);
        writeData(cFBInterfaceSpec.getNumDIs() + 3, var_FB_2, conn_FB_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 4, var_TRIP_1, conn_TRIP_1);
        writeData(cFBInterfaceSpec.getNumDIs() + 5, var_TRIP_2, conn_TRIP_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 6, var_COMMS_OK, conn_COMMS_OK);
        writeData(cFBInterfaceSpec.getNumDIs() + 7, var_SENSOR_FAULT, conn_SENSOR_FAULT);
        break;
      }
      default: break;
    }
  }

  CIEC_ANY *FORTE_IO_GUARD::getDI(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_R_AUTO;
      case 1: return &var_R_ACK;
      case 2: return &var_R_FB_1;
      case 3: return &var_R_FB_2;
      case 4: return &var_R_TRIP_1;
      case 5: return &var_R_TRIP_2;
      case 6: return &var_HEARTBEAT;
      case 7: return &var_RAW_LEVEL;
      case 8: return &var_STUCK_EPS;
      case 9: return &var_COMMS_TIMEOUT;
      case 10: return &var_STUCK_TIME;
      case 11: return &var_SCAN_DT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_IO_GUARD::getDO(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_AUTO_MODE;
      case 1: return &var_ACK;
      case 2: return &var_FB_1;
      case 3: return &var_FB_2;
      case 4: return &var_TRIP_1;
      case 5: return &var_TRIP_2;
      case 6: return &var_COMMS_OK;
      case 7: return &var_SENSOR_FAULT;
    }
    return nullptr;
  }

  CEventConnection *FORTE_IO_GUARD::getEOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_CNF;
    }
    return nullptr;
  }

  CDataConnection **FORTE_IO_GUARD::getDIConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_R_AUTO;
      case 1: return &conn_R_ACK;
      case 2: return &conn_R_FB_1;
      case 3: return &conn_R_FB_2;
      case 4: return &conn_R_TRIP_1;
      case 5: return &conn_R_TRIP_2;
      case 6: return &conn_HEARTBEAT;
      case 7: return &conn_RAW_LEVEL;
      case 8: return &conn_STUCK_EPS;
      case 9: return &conn_COMMS_TIMEOUT;
      case 10: return &conn_STUCK_TIME;
      case 11: return &conn_SCAN_DT;
    }
    return nullptr;
  }

  CDataConnection *FORTE_IO_GUARD::getDOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_AUTO_MODE;
      case 1: return &conn_ACK;
      case 2: return &conn_FB_1;
      case 3: return &conn_FB_2;
      case 4: return &conn_TRIP_1;
      case 5: return &conn_TRIP_2;
      case 6: return &conn_COMMS_OK;
      case 7: return &conn_SENSOR_FAULT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_IO_GUARD::getVarInternal(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_LAST_HEARTBEAT;
      case 1: return &var_LAST_LEVEL;
      case 2: return &var_SEEN_BEAT;
      case 3: return &var_UNCHANGED;
      case 4: return &var_DELTA;
      case 5: return &var_ST2FB_NOW;
      case 6: return &var_COMMS_TIMER_IN;
      case 7: return &var_COMMS_TIMER_PT;
      case 8: return &var_COMMS_TIMER_Q;
      case 9: return &var_COMMS_TIMER_ET;
      case 10: return &var_COMMS_TIMER_STATE;
      case 11: return &var_COMMS_TIMER_PREV_IN;
      case 12: return &var_COMMS_TIMER_START_TIME;
      case 13: return &var_STUCK_TIMER_IN;
      case 14: return &var_STUCK_TIMER_PT;
      case 15: return &var_STUCK_TIMER_Q;
      case 16: return &var_STUCK_TIMER_ET;
      case 17: return &var_STUCK_TIMER_STATE;
      case 18: return &var_STUCK_TIMER_PREV_IN;
      case 19: return &var_STUCK_TIMER_START_TIME;
      case 20: return &var_ACK_EDGE_CLK;
      case 21: return &var_ACK_EDGE_Q;
      case 22: return &var_ACK_EDGE_M;
      case 23: return &var_FAULT_LATCH_S1;
      case 24: return &var_FAULT_LATCH_R;
      case 25: return &var_FAULT_LATCH_Q1;
    }
    return nullptr;
  }

  void FORTE_IO_GUARD::alg_scan(void) {
#line 1 "IO_GUARD.fbt"
    var_ST2FB_NOW = func_ADD<CIEC_TIME>(var_ST2FB_NOW, var_SCAN_DT);
#line 2 "IO_GUARD.fbt"
    if (func_NE(var_HEARTBEAT, var_LAST_HEARTBEAT)) {
#line 3 "IO_GUARD.fbt"
      var_SEEN_BEAT = true_BOOL;
    }
#line 5 "IO_GUARD.fbt"
    var_COMMS_TIMER_IN = func_EQ(var_HEARTBEAT, var_LAST_HEARTBEAT);
#line 6 "IO_GUARD.fbt"
    var_COMMS_TIMER_PT = var_COMMS_TIMEOUT;
#line 7 "IO_GUARD.fbt"
    if (func_AND<CIEC_BOOL>(func_AND<CIEC_BOOL>(func_EQ(var_COMMS_TIMER_STATE, 0_INT), func_NOT<CIEC_BOOL>(var_COMMS_TIMER_PREV_IN)), var_COMMS_TIMER_IN)) {
#line 8 "IO_GUARD.fbt"
      var_COMMS_TIMER_STATE = 1_INT;
#line 9 "IO_GUARD.fbt"
      var_COMMS_TIMER_Q = false_BOOL;
#line 10 "IO_GUARD.fbt"
      var_COMMS_TIMER_START_TIME = var_ST2FB_NOW;
    } else {
#line 12 "IO_GUARD.fbt"
      if (func_NOT<CIEC_BOOL>(var_COMMS_TIMER_IN)) {
#line 13 "IO_GUARD.fbt"
        var_COMMS_TIMER_ET = 0_TIME;
#line 14 "IO_GUARD.fbt"
        var_COMMS_TIMER_Q = false_BOOL;
#line 15 "IO_GUARD.fbt"
        var_COMMS_TIMER_STATE = 0_INT;
      } else if (func_EQ(var_COMMS_TIMER_STATE, 1_INT)) {
#line 17 "IO_GUARD.fbt"
        if (func_LE(func_ADD<CIEC_TIME>(var_COMMS_TIMER_START_TIME, var_COMMS_TIMER_PT), var_ST2FB_NOW)) {
#line 18 "IO_GUARD.fbt"
          var_COMMS_TIMER_STATE = 2_INT;
#line 19 "IO_GUARD.fbt"
          var_COMMS_TIMER_Q = true_BOOL;
#line 20 "IO_GUARD.fbt"
          var_COMMS_TIMER_ET = var_COMMS_TIMER_PT;
        } else {
#line 22 "IO_GUARD.fbt"
          var_COMMS_TIMER_ET = func_SUB<CIEC_TIME>(var_ST2FB_NOW, var_COMMS_TIMER_START_TIME);
        }
      }
    }
#line 26 "IO_GUARD.fbt"
    var_COMMS_TIMER_PREV_IN = var_COMMS_TIMER_IN;
#line 27 "IO_GUARD.fbt"
    var_LAST_HEARTBEAT = var_HEARTBEAT;
#line 28 "IO_GUARD.fbt"
    var_COMMS_OK = func_AND<CIEC_BOOL>(var_SEEN_BEAT, func_NOT<CIEC_BOOL>(var_COMMS_TIMER_Q));
#line 29 "IO_GUARD.fbt"
    var_DELTA = func_SUB<CIEC_REAL>(var_RAW_LEVEL, var_LAST_LEVEL);
#line 30 "IO_GUARD.fbt"
    var_UNCHANGED = func_AND<CIEC_BOOL>(func_LE(var_DELTA, var_STUCK_EPS), func_GE(var_DELTA, func_MINUS(var_STUCK_EPS)));
#line 31 "IO_GUARD.fbt"
    var_LAST_LEVEL = var_RAW_LEVEL;
#line 32 "IO_GUARD.fbt"
    var_STUCK_TIMER_IN = func_AND<CIEC_BOOL>(var_UNCHANGED, var_COMMS_OK);
#line 33 "IO_GUARD.fbt"
    var_STUCK_TIMER_PT = var_STUCK_TIME;
#line 34 "IO_GUARD.fbt"
    if (func_AND<CIEC_BOOL>(func_AND<CIEC_BOOL>(func_EQ(var_STUCK_TIMER_STATE, 0_INT), func_NOT<CIEC_BOOL>(var_STUCK_TIMER_PREV_IN)), var_STUCK_TIMER_IN)) {
#line 35 "IO_GUARD.fbt"
      var_STUCK_TIMER_STATE = 1_INT;
#line 36 "IO_GUARD.fbt"
      var_STUCK_TIMER_Q = false_BOOL;
#line 37 "IO_GUARD.fbt"
      var_STUCK_TIMER_START_TIME = var_ST2FB_NOW;
    } else {
#line 39 "IO_GUARD.fbt"
      if (func_NOT<CIEC_BOOL>(var_STUCK_TIMER_IN)) {
#line 40 "IO_GUARD.fbt"
        var_STUCK_TIMER_ET = 0_TIME;
#line 41 "IO_GUARD.fbt"
        var_STUCK_TIMER_Q = false_BOOL;
#line 42 "IO_GUARD.fbt"
        var_STUCK_TIMER_STATE = 0_INT;
      } else if (func_EQ(var_STUCK_TIMER_STATE, 1_INT)) {
#line 44 "IO_GUARD.fbt"
        if (func_LE(func_ADD<CIEC_TIME>(var_STUCK_TIMER_START_TIME, var_STUCK_TIMER_PT), var_ST2FB_NOW)) {
#line 45 "IO_GUARD.fbt"
          var_STUCK_TIMER_STATE = 2_INT;
#line 46 "IO_GUARD.fbt"
          var_STUCK_TIMER_Q = true_BOOL;
#line 47 "IO_GUARD.fbt"
          var_STUCK_TIMER_ET = var_STUCK_TIMER_PT;
        } else {
#line 49 "IO_GUARD.fbt"
          var_STUCK_TIMER_ET = func_SUB<CIEC_TIME>(var_ST2FB_NOW, var_STUCK_TIMER_START_TIME);
        }
      }
    }
#line 53 "IO_GUARD.fbt"
    var_STUCK_TIMER_PREV_IN = var_STUCK_TIMER_IN;
#line 54 "IO_GUARD.fbt"
    var_ACK = func_NE(var_R_ACK, 0_UINT);
#line 55 "IO_GUARD.fbt"
    var_ACK_EDGE_CLK = var_ACK;
#line 56 "IO_GUARD.fbt"
    var_ACK_EDGE_Q = func_AND<CIEC_BOOL>(var_ACK_EDGE_CLK, func_NOT<CIEC_BOOL>(var_ACK_EDGE_M));
#line 57 "IO_GUARD.fbt"
    var_ACK_EDGE_M = var_ACK_EDGE_CLK;
#line 58 "IO_GUARD.fbt"
    var_FAULT_LATCH_S1 = var_STUCK_TIMER_Q;
#line 59 "IO_GUARD.fbt"
    var_FAULT_LATCH_R = var_ACK_EDGE_Q;
#line 60 "IO_GUARD.fbt"
    var_FAULT_LATCH_Q1 = func_OR<CIEC_BOOL>(var_FAULT_LATCH_S1, func_AND<CIEC_BOOL>(func_NOT<CIEC_BOOL>(var_FAULT_LATCH_R), var_FAULT_LATCH_Q1));
#line 61 "IO_GUARD.fbt"
    var_SENSOR_FAULT = var_FAULT_LATCH_Q1;
#line 62 "IO_GUARD.fbt"
    var_AUTO_MODE = func_AND<CIEC_BOOL>(func_AND<CIEC_BOOL>(func_NE(var_R_AUTO, 0_UINT), var_COMMS_OK), func_NOT<CIEC_BOOL>(var_SENSOR_FAULT));
#line 63 "IO_GUARD.fbt"
    var_FB_1 = func_NE(var_R_FB_1, 0_UINT);
#line 64 "IO_GUARD.fbt"
    var_FB_2 = func_NE(var_R_FB_2, 0_UINT);
#line 65 "IO_GUARD.fbt"
    var_TRIP_1 = func_NE(var_R_TRIP_1, 0_UINT);
#line 66 "IO_GUARD.fbt"
    var_TRIP_2 = func_NE(var_R_TRIP_2, 0_UINT);
  }

} // namespace forte::st2fb
