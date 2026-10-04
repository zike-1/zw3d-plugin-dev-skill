#pragma once

constexpr int VX_CODE_GENERAL = 0;

extern "C" int cvxCmdFunc(const char* name, void* callback, int kind);
extern "C" int cvxCmdFuncUnload(const char* name);
extern "C" int cvxCmdBuffer(const char* command, int option);
