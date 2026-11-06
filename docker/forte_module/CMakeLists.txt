# Out-of-tree slot for exactly one exported FB. The Dockerfile copies this folder to
# modules/st2fb and hooks it into modules/CMakeLists.txt. forte_run overwrites fb.cpp per FB,
# so only this file recompiles and forte relinks; the rest of FORTE stays cached in the image.
add_library(st2fb-fb fb.cpp)
target_include_directories(st2fb-fb PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(st2fb-fb PUBLIC forte-core)
# WHOLE_ARCHIVE keeps the FB's static registrar, which nothing references directly.
target_link_libraries(forte PUBLIC $<LINK_LIBRARY:WHOLE_ARCHIVE,st2fb-fb>)
