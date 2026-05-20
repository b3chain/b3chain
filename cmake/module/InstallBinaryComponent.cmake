# Copyright (c) 2025-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

include_guard(GLOBAL)
include(GNUInstallDirs)

function(install_binary_component component)
  cmake_parse_arguments(PARSE_ARGV 1
    IC                          # prefix
    "HAS_MANPAGE;INTERNAL"      # options
    ""                          # one_value_keywords
    ""                          # multi_value_keywords
  )
  set(target_name ${component})
  if(IC_INTERNAL)
    set(runtime_dest ${CMAKE_INSTALL_LIBEXECDIR})
  else()
    set(runtime_dest ${CMAKE_INSTALL_BINDIR})
  endif()
  install(TARGETS ${target_name}
    RUNTIME DESTINATION ${runtime_dest}
    COMPONENT ${component}
  )
  if(INSTALL_MAN AND IC_HAS_MANPAGE)
    # b3chain renames the upstream Bitcoin Core executables (e.g. CMake
    # target `bitcoin-qt` -> output `b3chain-qt`).  The man pages live
    # under the *output* name, not the CMake target name, so use the
    # target's OUTPUT_NAME property if it has been set.  Without this
    # the install step fails on the macOS arm64 sqlite-only-gui job
    # with "file INSTALL cannot find /.../doc/man/bitcoin-qt.1".
    get_target_property(_man_basename ${target_name} OUTPUT_NAME)
    if(NOT _man_basename)
      set(_man_basename ${target_name})
    endif()
    install(FILES ${PROJECT_SOURCE_DIR}/doc/man/${_man_basename}.1
      DESTINATION ${CMAKE_INSTALL_MANDIR}/man1
      COMPONENT ${component}
    )
  endif()
endfunction()
