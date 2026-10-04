#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string>

#include "zwapi_cmd.h"

namespace {
HMODULE module = nullptr;
bool commandRegistered = false;
constexpr char commandName[] = "ArtHelloShow";

[[maybe_unused]] std::wstring ModuleDirectory() {
    wchar_t path[32768]{};
    const DWORD length = GetModuleFileNameW(module, path, 32768);
    if (length == 0 || length >= 32768) return {};
    std::wstring result(path, length);
    const auto separator = result.find_last_of(L"\\/");
    return separator == std::wstring::npos ? L"" : result.substr(0, separator);
}

bool IsAbsolutePath(const std::wstring& path) {
    const bool drive = path.size() >= 3 && path[1] == L':' &&
                       (path[2] == L'\\' || path[2] == L'/');
    const bool unc = path.size() >= 3 && path[0] == L'\\' && path[1] == L'\\';
    return drive || unc;
}

// This opt-in test mode never runs during ordinary use.
bool WriteProbeIfRequested() {
    wchar_t path[32768]{};
    const DWORD length = GetEnvironmentVariableW(L"ZW_HUB_DEMO_LOG", path, 32768);
    if (length == 0) return false;
    if (length >= 32768 || !IsAbsolutePath(path)) return true;

    HANDLE file = CreateFileW(path, FILE_APPEND_DATA,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                             OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file != INVALID_HANDLE_VALUE) {
        constexpr char record[] = "dll|ArtHelloShow|ok\n";
        DWORD written = 0;
        WriteFile(file, record, sizeof(record) - 1, &written, nullptr);
        FlushFileBuffers(file);
        CloseHandle(file);
    }
    return true;
}

void Show() {
    if (WriteProbeIfRequested()) return;
    MessageBoxW(nullptr, L"这是一个最小插件示例。它只显示提示，不修改当前模型。",
                L"优雅问候", MB_OK | MB_ICONINFORMATION);
}
}  // namespace

extern "C" __declspec(dllexport) int ArtHelloInit() {
    if (commandRegistered) return 0;
    const int result = static_cast<int>(cvxCmdFunc(commandName,
                                                  reinterpret_cast<void*>(Show),
                                                  VX_CODE_GENERAL));
    // A failed registration belongs to somebody else; never unregister it.
    if (result != 0) return result;
    commandRegistered = true;
    return 0;
}

extern "C" __declspec(dllexport) int ArtHelloExit() {
    if (!commandRegistered) return 0;
    const int result = static_cast<int>(cvxCmdFuncUnload(commandName));
    if (result == 0) commandRegistered = false;
    return result;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) module = instance;
    return TRUE;
}
