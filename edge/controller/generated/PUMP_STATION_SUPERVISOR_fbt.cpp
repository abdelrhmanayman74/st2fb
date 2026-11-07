#include "PUMP_STATION_SUPERVISOR_fbt.h"

#include "forte/datatypes/forte_bool.h"
#include "forte/datatypes/forte_dint.h"
#include "forte/datatypes/forte_int.h"
#include "forte/datatypes/forte_real.h"
#include "forte/datatypes/forte_time.h"
#include "forte/datatypes/forte_uint.h"
#include "forte/forte_st_util.h"
#include "forte/iec61131_functions/func_ADD.h"
#include "forte/iec61131_functions/func_AND.h"
#include "forte/iec61131_functions/func_EQ.h"
#include "forte/iec61131_functions/func_GE.h"
#include "forte/iec61131_functions/func_GT.h"
#include "forte/iec61131_functions/func_LE.h"
#include "forte/iec61131_functions/func_LT.h"
#include "forte/iec61131_functions/func_MUL.h"
#include "forte/iec61131_functions/func_NE.h"
#include "forte/iec61131_functions/func_NOT.h"
#include "forte/iec61131_functions/func_OR.h"
#include "forte/iec61131_functions/func_SUB.h"

using namespace forte::literals;

namespace forte::st2fb {
  namespace {
    const auto cEventInputNames = std::array{"REQ"_STRID};
    const auto cEventOutputNames = std::array{"CNF"_STRID};
    const auto cDataInputNames = std::array{"AUTO_MODE"_STRID, "ACK"_STRID, "RAW_LEVEL"_STRID, "STOP_LEVEL"_STRID, "START_LEVEL"_STRID, "LAG_LEVEL"_STRID, "HIGH_LEVEL"_STRID, "FB_1"_STRID, "FB_2"_STRID, "TRIP_1"_STRID, "TRIP_2"_STRID, "FLOW"_STRID, "SCAN_HOURS"_STRID, "PULSE_SIZE"_STRID, "PROOF_TIME"_STRID, "ALARM_DELAY"_STRID, "SCAN_DT"_STRID};
    const auto cDataOutputNames = std::array{"STATE_NO"_STRID, "PUMP_1"_STRID, "PUMP_2"_STRID, "LEAD_IS_2"_STRID, "HIGH_ALARM"_STRID, "STATION_FAULT"_STRID, "FILTERED_LEVEL"_STRID, "TOTAL"_STRID, "PULSES"_STRID, "STARTS"_STRID};
    const auto cInternalsNames = std::array{"PASSES"_STRID, "I"_STRID, "STEP_SIZE"_STRID, "PENDING"_STRID, "LEAD_RUNNING_FB"_STRID, "LEAD_FAILED"_STRID, "LAG_FAILED"_STRID, "ST2FB_NOW"_STRID, "FAILED_1_S1"_STRID, "FAILED_1_R"_STRID, "FAILED_1_Q1"_STRID, "FAILED_2_S1"_STRID, "FAILED_2_R"_STRID, "FAILED_2_Q1"_STRID, "PROOF_TIMER_IN"_STRID, "PROOF_TIMER_PT"_STRID, "PROOF_TIMER_Q"_STRID, "PROOF_TIMER_ET"_STRID, "PROOF_TIMER_STATE"_STRID, "PROOF_TIMER_PREV_IN"_STRID, "PROOF_TIMER_START_TIME"_STRID, "ALARM_TIMER_IN"_STRID, "ALARM_TIMER_PT"_STRID, "ALARM_TIMER_Q"_STRID, "ALARM_TIMER_ET"_STRID, "ALARM_TIMER_STATE"_STRID, "ALARM_TIMER_PREV_IN"_STRID, "ALARM_TIMER_START_TIME"_STRID, "ACK_EDGE_CLK"_STRID, "ACK_EDGE_Q"_STRID, "ACK_EDGE_M"_STRID};
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

  DEFINE_FIRMWARE_FB(FORTE_PUMP_STATION_SUPERVISOR, "st2fb::PUMP_STATION_SUPERVISOR"_STRID)

  FORTE_PUMP_STATION_SUPERVISOR::FORTE_PUMP_STATION_SUPERVISOR(const StringId paInstanceNameId, CFBContainer &paContainer) :
      CBasicFB(paContainer, cFBInterfaceSpec, paInstanceNameId, cInternalsNames),
      var_PASSES(0_INT),
      var_I(0_INT),
      var_STEP_SIZE(0_REAL),
      var_PENDING(0_REAL),
      var_LEAD_RUNNING_FB(0_BOOL),
      var_LEAD_FAILED(0_BOOL),
      var_LAG_FAILED(0_BOOL),
      var_ST2FB_NOW(0_TIME),
      var_FAILED_1_S1(0_BOOL),
      var_FAILED_1_R(0_BOOL),
      var_FAILED_1_Q1(0_BOOL),
      var_FAILED_2_S1(0_BOOL),
      var_FAILED_2_R(0_BOOL),
      var_FAILED_2_Q1(0_BOOL),
      var_PROOF_TIMER_IN(0_BOOL),
      var_PROOF_TIMER_PT(0_TIME),
      var_PROOF_TIMER_Q(0_BOOL),
      var_PROOF_TIMER_ET(0_TIME),
      var_PROOF_TIMER_STATE(0_INT),
      var_PROOF_TIMER_PREV_IN(0_BOOL),
      var_PROOF_TIMER_START_TIME(0_TIME),
      var_ALARM_TIMER_IN(0_BOOL),
      var_ALARM_TIMER_PT(0_TIME),
      var_ALARM_TIMER_Q(0_BOOL),
      var_ALARM_TIMER_ET(0_TIME),
      var_ALARM_TIMER_STATE(0_INT),
      var_ALARM_TIMER_PREV_IN(0_BOOL),
      var_ALARM_TIMER_START_TIME(0_TIME),
      var_ACK_EDGE_CLK(0_BOOL),
      var_ACK_EDGE_Q(0_BOOL),
      var_ACK_EDGE_M(0_BOOL),
      var_AUTO_MODE(0_BOOL),
      var_ACK(0_BOOL),
      var_RAW_LEVEL(0_REAL),
      var_STOP_LEVEL(0_REAL),
      var_START_LEVEL(0_REAL),
      var_LAG_LEVEL(0_REAL),
      var_HIGH_LEVEL(0_REAL),
      var_FB_1(0_BOOL),
      var_FB_2(0_BOOL),
      var_TRIP_1(0_BOOL),
      var_TRIP_2(0_BOOL),
      var_FLOW(0_REAL),
      var_SCAN_HOURS(0_REAL),
      var_PULSE_SIZE(0_REAL),
      var_PROOF_TIME(0_TIME),
      var_ALARM_DELAY(0_TIME),
      var_SCAN_DT(0_TIME),
      var_STATE_NO(0_INT),
      var_PUMP_1(0_BOOL),
      var_PUMP_2(0_BOOL),
      var_LEAD_IS_2(0_BOOL),
      var_HIGH_ALARM(0_BOOL),
      var_STATION_FAULT(0_BOOL),
      var_FILTERED_LEVEL(0_REAL),
      var_TOTAL(0_REAL),
      var_PULSES(0_DINT),
      var_STARTS(0_UINT),
      conn_CNF(*this, 0),
      conn_AUTO_MODE(nullptr),
      conn_ACK(nullptr),
      conn_RAW_LEVEL(nullptr),
      conn_STOP_LEVEL(nullptr),
      conn_START_LEVEL(nullptr),
      conn_LAG_LEVEL(nullptr),
      conn_HIGH_LEVEL(nullptr),
      conn_FB_1(nullptr),
      conn_FB_2(nullptr),
      conn_TRIP_1(nullptr),
      conn_TRIP_2(nullptr),
      conn_FLOW(nullptr),
      conn_SCAN_HOURS(nullptr),
      conn_PULSE_SIZE(nullptr),
      conn_PROOF_TIME(nullptr),
      conn_ALARM_DELAY(nullptr),
      conn_SCAN_DT(nullptr),
      conn_STATE_NO(*this, 0, var_STATE_NO),
      conn_PUMP_1(*this, 1, var_PUMP_1),
      conn_PUMP_2(*this, 2, var_PUMP_2),
      conn_LEAD_IS_2(*this, 3, var_LEAD_IS_2),
      conn_HIGH_ALARM(*this, 4, var_HIGH_ALARM),
      conn_STATION_FAULT(*this, 5, var_STATION_FAULT),
      conn_FILTERED_LEVEL(*this, 6, var_FILTERED_LEVEL),
      conn_TOTAL(*this, 7, var_TOTAL),
      conn_PULSES(*this, 8, var_PULSES),
      conn_STARTS(*this, 9, var_STARTS) {
  }

  void FORTE_PUMP_STATION_SUPERVISOR::setInitialValues() {
    CBasicFB::setInitialValues();
    var_PASSES = 0_INT;
    var_I = 0_INT;
    var_STEP_SIZE = 0_REAL;
    var_PENDING = 0_REAL;
    var_LEAD_RUNNING_FB = 0_BOOL;
    var_LEAD_FAILED = 0_BOOL;
    var_LAG_FAILED = 0_BOOL;
    var_ST2FB_NOW = 0_TIME;
    var_FAILED_1_S1 = 0_BOOL;
    var_FAILED_1_R = 0_BOOL;
    var_FAILED_1_Q1 = 0_BOOL;
    var_FAILED_2_S1 = 0_BOOL;
    var_FAILED_2_R = 0_BOOL;
    var_FAILED_2_Q1 = 0_BOOL;
    var_PROOF_TIMER_IN = 0_BOOL;
    var_PROOF_TIMER_PT = 0_TIME;
    var_PROOF_TIMER_Q = 0_BOOL;
    var_PROOF_TIMER_ET = 0_TIME;
    var_PROOF_TIMER_STATE = 0_INT;
    var_PROOF_TIMER_PREV_IN = 0_BOOL;
    var_PROOF_TIMER_START_TIME = 0_TIME;
    var_ALARM_TIMER_IN = 0_BOOL;
    var_ALARM_TIMER_PT = 0_TIME;
    var_ALARM_TIMER_Q = 0_BOOL;
    var_ALARM_TIMER_ET = 0_TIME;
    var_ALARM_TIMER_STATE = 0_INT;
    var_ALARM_TIMER_PREV_IN = 0_BOOL;
    var_ALARM_TIMER_START_TIME = 0_TIME;
    var_ACK_EDGE_CLK = 0_BOOL;
    var_ACK_EDGE_Q = 0_BOOL;
    var_ACK_EDGE_M = 0_BOOL;
    var_AUTO_MODE = 0_BOOL;
    var_ACK = 0_BOOL;
    var_RAW_LEVEL = 0_REAL;
    var_STOP_LEVEL = 0_REAL;
    var_START_LEVEL = 0_REAL;
    var_LAG_LEVEL = 0_REAL;
    var_HIGH_LEVEL = 0_REAL;
    var_FB_1 = 0_BOOL;
    var_FB_2 = 0_BOOL;
    var_TRIP_1 = 0_BOOL;
    var_TRIP_2 = 0_BOOL;
    var_FLOW = 0_REAL;
    var_SCAN_HOURS = 0_REAL;
    var_PULSE_SIZE = 0_REAL;
    var_PROOF_TIME = 0_TIME;
    var_ALARM_DELAY = 0_TIME;
    var_SCAN_DT = 0_TIME;
    var_STATE_NO = 0_INT;
    var_PUMP_1 = 0_BOOL;
    var_PUMP_2 = 0_BOOL;
    var_LEAD_IS_2 = 0_BOOL;
    var_HIGH_ALARM = 0_BOOL;
    var_STATION_FAULT = 0_BOOL;
    var_FILTERED_LEVEL = 0_REAL;
    var_TOTAL = 0_REAL;
    var_PULSES = 0_DINT;
    var_STARTS = 0_UINT;
  }

  void FORTE_PUMP_STATION_SUPERVISOR::executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) {
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

  void FORTE_PUMP_STATION_SUPERVISOR::enterStateSTART(CEventChainExecutionThread *const ) {
    mECCState = scmStateSTART;
  }

  void FORTE_PUMP_STATION_SUPERVISOR::enterStateRUN(CEventChainExecutionThread *const paECET) {
    mECCState = scmStateRUN;
    alg_scan();
    sendOutputEvent(scmEventCNFID, paECET);
  }

  void FORTE_PUMP_STATION_SUPERVISOR::readInputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventREQID: {
        readData(0, var_AUTO_MODE, conn_AUTO_MODE);
        readData(1, var_ACK, conn_ACK);
        readData(2, var_RAW_LEVEL, conn_RAW_LEVEL);
        readData(3, var_STOP_LEVEL, conn_STOP_LEVEL);
        readData(4, var_START_LEVEL, conn_START_LEVEL);
        readData(5, var_LAG_LEVEL, conn_LAG_LEVEL);
        readData(6, var_HIGH_LEVEL, conn_HIGH_LEVEL);
        readData(7, var_FB_1, conn_FB_1);
        readData(8, var_FB_2, conn_FB_2);
        readData(9, var_TRIP_1, conn_TRIP_1);
        readData(10, var_TRIP_2, conn_TRIP_2);
        readData(11, var_FLOW, conn_FLOW);
        readData(12, var_SCAN_HOURS, conn_SCAN_HOURS);
        readData(13, var_PULSE_SIZE, conn_PULSE_SIZE);
        readData(14, var_PROOF_TIME, conn_PROOF_TIME);
        readData(15, var_ALARM_DELAY, conn_ALARM_DELAY);
        readData(16, var_SCAN_DT, conn_SCAN_DT);
        break;
      }
      default: break;
    }
  }

  void FORTE_PUMP_STATION_SUPERVISOR::writeOutputData(const TEventID paEIID) {
    switch (paEIID) {
      case scmEventCNFID: {
        writeData(cFBInterfaceSpec.getNumDIs() + 0, var_STATE_NO, conn_STATE_NO);
        writeData(cFBInterfaceSpec.getNumDIs() + 1, var_PUMP_1, conn_PUMP_1);
        writeData(cFBInterfaceSpec.getNumDIs() + 2, var_PUMP_2, conn_PUMP_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 3, var_LEAD_IS_2, conn_LEAD_IS_2);
        writeData(cFBInterfaceSpec.getNumDIs() + 4, var_HIGH_ALARM, conn_HIGH_ALARM);
        writeData(cFBInterfaceSpec.getNumDIs() + 5, var_STATION_FAULT, conn_STATION_FAULT);
        writeData(cFBInterfaceSpec.getNumDIs() + 6, var_FILTERED_LEVEL, conn_FILTERED_LEVEL);
        writeData(cFBInterfaceSpec.getNumDIs() + 7, var_TOTAL, conn_TOTAL);
        writeData(cFBInterfaceSpec.getNumDIs() + 8, var_PULSES, conn_PULSES);
        writeData(cFBInterfaceSpec.getNumDIs() + 9, var_STARTS, conn_STARTS);
        break;
      }
      default: break;
    }
  }

  CIEC_ANY *FORTE_PUMP_STATION_SUPERVISOR::getDI(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_AUTO_MODE;
      case 1: return &var_ACK;
      case 2: return &var_RAW_LEVEL;
      case 3: return &var_STOP_LEVEL;
      case 4: return &var_START_LEVEL;
      case 5: return &var_LAG_LEVEL;
      case 6: return &var_HIGH_LEVEL;
      case 7: return &var_FB_1;
      case 8: return &var_FB_2;
      case 9: return &var_TRIP_1;
      case 10: return &var_TRIP_2;
      case 11: return &var_FLOW;
      case 12: return &var_SCAN_HOURS;
      case 13: return &var_PULSE_SIZE;
      case 14: return &var_PROOF_TIME;
      case 15: return &var_ALARM_DELAY;
      case 16: return &var_SCAN_DT;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_PUMP_STATION_SUPERVISOR::getDO(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_STATE_NO;
      case 1: return &var_PUMP_1;
      case 2: return &var_PUMP_2;
      case 3: return &var_LEAD_IS_2;
      case 4: return &var_HIGH_ALARM;
      case 5: return &var_STATION_FAULT;
      case 6: return &var_FILTERED_LEVEL;
      case 7: return &var_TOTAL;
      case 8: return &var_PULSES;
      case 9: return &var_STARTS;
    }
    return nullptr;
  }

  CEventConnection *FORTE_PUMP_STATION_SUPERVISOR::getEOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_CNF;
    }
    return nullptr;
  }

  CDataConnection **FORTE_PUMP_STATION_SUPERVISOR::getDIConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_AUTO_MODE;
      case 1: return &conn_ACK;
      case 2: return &conn_RAW_LEVEL;
      case 3: return &conn_STOP_LEVEL;
      case 4: return &conn_START_LEVEL;
      case 5: return &conn_LAG_LEVEL;
      case 6: return &conn_HIGH_LEVEL;
      case 7: return &conn_FB_1;
      case 8: return &conn_FB_2;
      case 9: return &conn_TRIP_1;
      case 10: return &conn_TRIP_2;
      case 11: return &conn_FLOW;
      case 12: return &conn_SCAN_HOURS;
      case 13: return &conn_PULSE_SIZE;
      case 14: return &conn_PROOF_TIME;
      case 15: return &conn_ALARM_DELAY;
      case 16: return &conn_SCAN_DT;
    }
    return nullptr;
  }

  CDataConnection *FORTE_PUMP_STATION_SUPERVISOR::getDOConUnchecked(const TPortId paIndex) {
    switch (paIndex) {
      case 0: return &conn_STATE_NO;
      case 1: return &conn_PUMP_1;
      case 2: return &conn_PUMP_2;
      case 3: return &conn_LEAD_IS_2;
      case 4: return &conn_HIGH_ALARM;
      case 5: return &conn_STATION_FAULT;
      case 6: return &conn_FILTERED_LEVEL;
      case 7: return &conn_TOTAL;
      case 8: return &conn_PULSES;
      case 9: return &conn_STARTS;
    }
    return nullptr;
  }

  CIEC_ANY *FORTE_PUMP_STATION_SUPERVISOR::getVarInternal(const size_t paIndex) {
    switch (paIndex) {
      case 0: return &var_PASSES;
      case 1: return &var_I;
      case 2: return &var_STEP_SIZE;
      case 3: return &var_PENDING;
      case 4: return &var_LEAD_RUNNING_FB;
      case 5: return &var_LEAD_FAILED;
      case 6: return &var_LAG_FAILED;
      case 7: return &var_ST2FB_NOW;
      case 8: return &var_FAILED_1_S1;
      case 9: return &var_FAILED_1_R;
      case 10: return &var_FAILED_1_Q1;
      case 11: return &var_FAILED_2_S1;
      case 12: return &var_FAILED_2_R;
      case 13: return &var_FAILED_2_Q1;
      case 14: return &var_PROOF_TIMER_IN;
      case 15: return &var_PROOF_TIMER_PT;
      case 16: return &var_PROOF_TIMER_Q;
      case 17: return &var_PROOF_TIMER_ET;
      case 18: return &var_PROOF_TIMER_STATE;
      case 19: return &var_PROOF_TIMER_PREV_IN;
      case 20: return &var_PROOF_TIMER_START_TIME;
      case 21: return &var_ALARM_TIMER_IN;
      case 22: return &var_ALARM_TIMER_PT;
      case 23: return &var_ALARM_TIMER_Q;
      case 24: return &var_ALARM_TIMER_ET;
      case 25: return &var_ALARM_TIMER_STATE;
      case 26: return &var_ALARM_TIMER_PREV_IN;
      case 27: return &var_ALARM_TIMER_START_TIME;
      case 28: return &var_ACK_EDGE_CLK;
      case 29: return &var_ACK_EDGE_Q;
      case 30: return &var_ACK_EDGE_M;
    }
    return nullptr;
  }

  void FORTE_PUMP_STATION_SUPERVISOR::alg_scan(void) {
#line 1 "PUMP_STATION_SUPERVISOR.fbt"
    var_ST2FB_NOW = func_ADD<CIEC_TIME>(var_ST2FB_NOW, var_SCAN_DT);
#line 2 "PUMP_STATION_SUPERVISOR.fbt"
    var_STEP_SIZE = func_SUB<CIEC_REAL>(var_RAW_LEVEL, var_FILTERED_LEVEL);
#line 3 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_OR<CIEC_BOOL>(func_GT(var_STEP_SIZE, 1.0_REAL), func_LT(var_STEP_SIZE, (-1.0_REAL)))) {
#line 4 "PUMP_STATION_SUPERVISOR.fbt"
      var_PASSES = 4_INT;
    } else {
#line 6 "PUMP_STATION_SUPERVISOR.fbt"
      var_PASSES = 1_INT;
    }
#line 8 "PUMP_STATION_SUPERVISOR.fbt"
    for (var_I = 1_INT; func_LE(var_I, var_PASSES); var_I = func_ADD<CIEC_INT>(var_I, 1_INT)) {
#line 9 "PUMP_STATION_SUPERVISOR.fbt"
      var_FILTERED_LEVEL = func_ADD<CIEC_REAL>(var_FILTERED_LEVEL, func_MUL<CIEC_REAL>(0.25_REAL, func_SUB<CIEC_REAL>(var_RAW_LEVEL, var_FILTERED_LEVEL)));
    }
#line 11 "PUMP_STATION_SUPERVISOR.fbt"
    var_ACK_EDGE_CLK = var_ACK;
#line 12 "PUMP_STATION_SUPERVISOR.fbt"
    var_ACK_EDGE_Q = func_AND<CIEC_BOOL>(var_ACK_EDGE_CLK, func_NOT<CIEC_BOOL>(var_ACK_EDGE_M));
#line 13 "PUMP_STATION_SUPERVISOR.fbt"
    var_ACK_EDGE_M = var_ACK_EDGE_CLK;
#line 14 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_1_S1 = func_OR<CIEC_BOOL>(var_TRIP_1, func_AND<CIEC_BOOL>(var_PROOF_TIMER_Q, func_NOT<CIEC_BOOL>(var_LEAD_IS_2)));
#line 15 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_1_R = var_ACK_EDGE_Q;
#line 16 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_1_Q1 = func_OR<CIEC_BOOL>(var_FAILED_1_S1, func_AND<CIEC_BOOL>(func_NOT<CIEC_BOOL>(var_FAILED_1_R), var_FAILED_1_Q1));
#line 17 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_2_S1 = func_OR<CIEC_BOOL>(var_TRIP_2, func_AND<CIEC_BOOL>(var_PROOF_TIMER_Q, var_LEAD_IS_2));
#line 18 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_2_R = var_ACK_EDGE_Q;
#line 19 "PUMP_STATION_SUPERVISOR.fbt"
    var_FAILED_2_Q1 = func_OR<CIEC_BOOL>(var_FAILED_2_S1, func_AND<CIEC_BOOL>(func_NOT<CIEC_BOOL>(var_FAILED_2_R), var_FAILED_2_Q1));
#line 20 "PUMP_STATION_SUPERVISOR.fbt"
    if (var_LEAD_IS_2) {
#line 21 "PUMP_STATION_SUPERVISOR.fbt"
      var_LEAD_FAILED = var_FAILED_2_Q1;
#line 22 "PUMP_STATION_SUPERVISOR.fbt"
      var_LAG_FAILED = var_FAILED_1_Q1;
#line 23 "PUMP_STATION_SUPERVISOR.fbt"
      var_LEAD_RUNNING_FB = var_FB_2;
    } else {
#line 25 "PUMP_STATION_SUPERVISOR.fbt"
      var_LEAD_FAILED = var_FAILED_1_Q1;
#line 26 "PUMP_STATION_SUPERVISOR.fbt"
      var_LAG_FAILED = var_FAILED_2_Q1;
#line 27 "PUMP_STATION_SUPERVISOR.fbt"
      var_LEAD_RUNNING_FB = var_FB_1;
    }
#line 29 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_AND<CIEC_BOOL>(func_NOT<CIEC_BOOL>(var_AUTO_MODE), func_NE(var_STATE_NO, 5_INT))) {
#line 30 "PUMP_STATION_SUPERVISOR.fbt"
      var_STATE_NO = 0_INT;
    }
#line 32 "PUMP_STATION_SUPERVISOR.fbt"
    {
      const CIEC_INT st_case_1 = var_STATE_NO;
      if (func_EQ(st_case_1, 0_INT)) {
#line 34 "PUMP_STATION_SUPERVISOR.fbt"
        if (var_AUTO_MODE) {
#line 35 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 1_INT;
        }
      } else if (func_EQ(st_case_1, 1_INT)) {
#line 38 "PUMP_STATION_SUPERVISOR.fbt"
        if (func_AND<CIEC_BOOL>(var_LEAD_FAILED, var_LAG_FAILED)) {
#line 39 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 5_INT;
        } else if (var_LEAD_FAILED) {
#line 41 "PUMP_STATION_SUPERVISOR.fbt"
          var_LEAD_IS_2 = func_NOT<CIEC_BOOL>(var_LEAD_IS_2);
        } else if (func_GE(var_FILTERED_LEVEL, var_START_LEVEL)) {
#line 43 "PUMP_STATION_SUPERVISOR.fbt"
          var_STARTS = func_ADD<CIEC_UINT>(var_STARTS, 1_UINT);
#line 44 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 2_INT;
        }
      } else if (func_EQ(st_case_1, 2_INT)) {
#line 47 "PUMP_STATION_SUPERVISOR.fbt"
        if (var_LEAD_FAILED) {
#line 48 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 1_INT;
        } else if (var_LEAD_RUNNING_FB) {
#line 50 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 3_INT;
        }
      } else if (func_EQ(st_case_1, 3_INT)) {
#line 53 "PUMP_STATION_SUPERVISOR.fbt"
        if (var_LEAD_FAILED) {
#line 54 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 1_INT;
        } else if (func_LE(var_FILTERED_LEVEL, var_STOP_LEVEL)) {
#line 56 "PUMP_STATION_SUPERVISOR.fbt"
          var_LEAD_IS_2 = func_NOT<CIEC_BOOL>(var_LEAD_IS_2);
#line 57 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 1_INT;
        } else if (func_AND<CIEC_BOOL>(func_GE(var_FILTERED_LEVEL, var_LAG_LEVEL), func_NOT<CIEC_BOOL>(var_LAG_FAILED))) {
#line 59 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 4_INT;
        }
      } else if (func_EQ(st_case_1, 4_INT)) {
#line 62 "PUMP_STATION_SUPERVISOR.fbt"
        if (var_LEAD_FAILED) {
#line 63 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 1_INT;
        } else if (func_OR<CIEC_BOOL>(var_LAG_FAILED, func_LT(var_FILTERED_LEVEL, var_LAG_LEVEL))) {
#line 65 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 3_INT;
        }
      } else if (func_EQ(st_case_1, 5_INT)) {
#line 68 "PUMP_STATION_SUPERVISOR.fbt"
        if (func_NOT<CIEC_BOOL>(func_OR<CIEC_BOOL>(var_LEAD_FAILED, var_LAG_FAILED))) {
#line 69 "PUMP_STATION_SUPERVISOR.fbt"
          var_STATE_NO = 0_INT;
        }
      } else {
#line 72 "PUMP_STATION_SUPERVISOR.fbt"
        var_STATE_NO = 0_INT;
      }
    }
#line 74 "PUMP_STATION_SUPERVISOR.fbt"
    var_PROOF_TIMER_IN = func_AND<CIEC_BOOL>(func_EQ(var_STATE_NO, 2_INT), func_NOT<CIEC_BOOL>(var_LEAD_RUNNING_FB));
#line 75 "PUMP_STATION_SUPERVISOR.fbt"
    var_PROOF_TIMER_PT = var_PROOF_TIME;
#line 76 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_AND<CIEC_BOOL>(func_AND<CIEC_BOOL>(func_EQ(var_PROOF_TIMER_STATE, 0_INT), func_NOT<CIEC_BOOL>(var_PROOF_TIMER_PREV_IN)), var_PROOF_TIMER_IN)) {
#line 77 "PUMP_STATION_SUPERVISOR.fbt"
      var_PROOF_TIMER_STATE = 1_INT;
#line 78 "PUMP_STATION_SUPERVISOR.fbt"
      var_PROOF_TIMER_Q = false_BOOL;
#line 79 "PUMP_STATION_SUPERVISOR.fbt"
      var_PROOF_TIMER_START_TIME = var_ST2FB_NOW;
    } else {
#line 81 "PUMP_STATION_SUPERVISOR.fbt"
      if (func_NOT<CIEC_BOOL>(var_PROOF_TIMER_IN)) {
#line 82 "PUMP_STATION_SUPERVISOR.fbt"
        var_PROOF_TIMER_ET = 0_TIME;
#line 83 "PUMP_STATION_SUPERVISOR.fbt"
        var_PROOF_TIMER_Q = false_BOOL;
#line 84 "PUMP_STATION_SUPERVISOR.fbt"
        var_PROOF_TIMER_STATE = 0_INT;
      } else if (func_EQ(var_PROOF_TIMER_STATE, 1_INT)) {
#line 86 "PUMP_STATION_SUPERVISOR.fbt"
        if (func_LE(func_ADD<CIEC_TIME>(var_PROOF_TIMER_START_TIME, var_PROOF_TIMER_PT), var_ST2FB_NOW)) {
#line 87 "PUMP_STATION_SUPERVISOR.fbt"
          var_PROOF_TIMER_STATE = 2_INT;
#line 88 "PUMP_STATION_SUPERVISOR.fbt"
          var_PROOF_TIMER_Q = true_BOOL;
#line 89 "PUMP_STATION_SUPERVISOR.fbt"
          var_PROOF_TIMER_ET = var_PROOF_TIMER_PT;
        } else {
#line 91 "PUMP_STATION_SUPERVISOR.fbt"
          var_PROOF_TIMER_ET = func_SUB<CIEC_TIME>(var_ST2FB_NOW, var_PROOF_TIMER_START_TIME);
        }
      }
    }
#line 95 "PUMP_STATION_SUPERVISOR.fbt"
    var_PROOF_TIMER_PREV_IN = var_PROOF_TIMER_IN;
#line 96 "PUMP_STATION_SUPERVISOR.fbt"
    var_STATION_FAULT = func_EQ(var_STATE_NO, 5_INT);
#line 97 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_AND<CIEC_BOOL>(func_GE(var_STATE_NO, 2_INT), func_LE(var_STATE_NO, 4_INT))) {
#line 98 "PUMP_STATION_SUPERVISOR.fbt"
      var_PUMP_1 = func_OR<CIEC_BOOL>(func_NOT<CIEC_BOOL>(var_LEAD_IS_2), func_EQ(var_STATE_NO, 4_INT));
#line 99 "PUMP_STATION_SUPERVISOR.fbt"
      var_PUMP_2 = func_OR<CIEC_BOOL>(var_LEAD_IS_2, func_EQ(var_STATE_NO, 4_INT));
    } else {
#line 101 "PUMP_STATION_SUPERVISOR.fbt"
      var_PUMP_1 = false_BOOL;
#line 102 "PUMP_STATION_SUPERVISOR.fbt"
      var_PUMP_2 = false_BOOL;
    }
#line 104 "PUMP_STATION_SUPERVISOR.fbt"
    var_ALARM_TIMER_IN = func_GE(var_FILTERED_LEVEL, var_HIGH_LEVEL);
#line 105 "PUMP_STATION_SUPERVISOR.fbt"
    var_ALARM_TIMER_PT = var_ALARM_DELAY;
#line 106 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_AND<CIEC_BOOL>(func_AND<CIEC_BOOL>(func_EQ(var_ALARM_TIMER_STATE, 0_INT), func_NOT<CIEC_BOOL>(var_ALARM_TIMER_PREV_IN)), var_ALARM_TIMER_IN)) {
#line 107 "PUMP_STATION_SUPERVISOR.fbt"
      var_ALARM_TIMER_STATE = 1_INT;
#line 108 "PUMP_STATION_SUPERVISOR.fbt"
      var_ALARM_TIMER_Q = false_BOOL;
#line 109 "PUMP_STATION_SUPERVISOR.fbt"
      var_ALARM_TIMER_START_TIME = var_ST2FB_NOW;
    } else {
#line 111 "PUMP_STATION_SUPERVISOR.fbt"
      if (func_NOT<CIEC_BOOL>(var_ALARM_TIMER_IN)) {
#line 112 "PUMP_STATION_SUPERVISOR.fbt"
        var_ALARM_TIMER_ET = 0_TIME;
#line 113 "PUMP_STATION_SUPERVISOR.fbt"
        var_ALARM_TIMER_Q = false_BOOL;
#line 114 "PUMP_STATION_SUPERVISOR.fbt"
        var_ALARM_TIMER_STATE = 0_INT;
      } else if (func_EQ(var_ALARM_TIMER_STATE, 1_INT)) {
#line 116 "PUMP_STATION_SUPERVISOR.fbt"
        if (func_LE(func_ADD<CIEC_TIME>(var_ALARM_TIMER_START_TIME, var_ALARM_TIMER_PT), var_ST2FB_NOW)) {
#line 117 "PUMP_STATION_SUPERVISOR.fbt"
          var_ALARM_TIMER_STATE = 2_INT;
#line 118 "PUMP_STATION_SUPERVISOR.fbt"
          var_ALARM_TIMER_Q = true_BOOL;
#line 119 "PUMP_STATION_SUPERVISOR.fbt"
          var_ALARM_TIMER_ET = var_ALARM_TIMER_PT;
        } else {
#line 121 "PUMP_STATION_SUPERVISOR.fbt"
          var_ALARM_TIMER_ET = func_SUB<CIEC_TIME>(var_ST2FB_NOW, var_ALARM_TIMER_START_TIME);
        }
      }
    }
#line 125 "PUMP_STATION_SUPERVISOR.fbt"
    var_ALARM_TIMER_PREV_IN = var_ALARM_TIMER_IN;
#line 126 "PUMP_STATION_SUPERVISOR.fbt"
    var_HIGH_ALARM = var_ALARM_TIMER_Q;
#line 127 "PUMP_STATION_SUPERVISOR.fbt"
    if (func_OR<CIEC_BOOL>(var_PUMP_1, var_PUMP_2)) {
#line 128 "PUMP_STATION_SUPERVISOR.fbt"
      var_TOTAL = func_ADD<CIEC_REAL>(var_TOTAL, func_MUL<CIEC_REAL>(var_FLOW, var_SCAN_HOURS));
#line 129 "PUMP_STATION_SUPERVISOR.fbt"
      var_PENDING = func_ADD<CIEC_REAL>(var_PENDING, func_MUL<CIEC_REAL>(var_FLOW, var_SCAN_HOURS));
#line 130 "PUMP_STATION_SUPERVISOR.fbt"
      while (func_GE(var_PENDING, var_PULSE_SIZE)) {
#line 131 "PUMP_STATION_SUPERVISOR.fbt"
        var_PENDING = func_SUB<CIEC_REAL>(var_PENDING, var_PULSE_SIZE);
#line 132 "PUMP_STATION_SUPERVISOR.fbt"
        var_PULSES = func_ADD<CIEC_DINT>(var_PULSES, 1_DINT);
      }
    }
  }

} // namespace forte::st2fb
