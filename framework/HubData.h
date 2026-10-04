#pragma once
#include <string>
#include <windows.h>

// The framework resolves a per-host, per-plugin, per-user directory.
// It does not create files or move user preferences as a side effect.
inline std::wstring HubDataDirectory(const char* pluginId) {
    using Getter = int (*)(const char*, wchar_t*, int);
    auto module = GetModuleHandleW(L"ZwPluginHub.dll");
    auto get = module ? reinterpret_cast<Getter>(GetProcAddress(module, "ZwPluginHubDataDirectory"))
                      : nullptr;
    wchar_t path[32768]{};
    return get && get(pluginId, path, 32768) == 0 ? path : L"";
}

// Standalone EXE tools receive this variable only in their own child process.
inline std::wstring HubExternalDataDirectory() {
    wchar_t path[32768]{};
    const auto n = GetEnvironmentVariableW(L"ZW_PLUGIN_DATA_DIR", path, 32768);
    return n && n < 32768 ? path : L"";
}
