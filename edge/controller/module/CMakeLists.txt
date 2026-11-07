# Out-of-tree FORTE module holding the migrated FBs and the scan probe. The Dockerfile copies this
# folder to modules/st2fb_edge. WHOLE_ARCHIVE keeps each FB's static registrar, which nothing references.
add_library(st2fb-edge
  PUMP_STATION_SUPERVISOR_fbt.cpp
  IO_GUARD_fbt.cpp
  OUTPUT_PACK_fbt.cpp
  SCAN_PROBE_fbt.cpp
)
target_include_directories(st2fb-edge PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(st2fb-edge PUBLIC forte-core)
target_link_libraries(forte PUBLIC $<LINK_LIBRARY:WHOLE_ARCHIVE,st2fb-edge>)
