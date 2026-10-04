// Compile the actual production translation unit with fixture-only Win32 and SDK boundaries.
// The production source receives no test hooks and the real CAD executable is never started.
#include "startup_event.h"
#include <shellapi.h>
#include <algorithm>
#include <cstring>
#include <deque>
#include <map>
#include <vector>

static HANDLE fixtureManager = nullptr;
static std::map<std::string, void*> fixtureCommands;
static std::deque<std::string> fixtureQueue;
static std::vector<HMODULE> fixtureBusiness;
static int fixtureStartQueued = 0;

static BOOL FixtureExecute(SHELLEXECUTEINFOW* request) {
    FixtureEvent("MANAGER_DISPATCH");
    auto copy = *request;
    // UAC is not part of this isolated handshake test.
    copy.lpVerb = L"open";
    const BOOL result = ShellExecuteExW(&copy);
    *request = copy;
    if (result && copy.hProcess)
        DuplicateHandle(GetCurrentProcess(), copy.hProcess, GetCurrentProcess(), &fixtureManager,
                        0, FALSE, DUPLICATE_SAME_ACCESS);
    return result;
}
static DWORD FixtureWait(HANDLE process, DWORD productionBudget) {
    wchar_t scenario[80]{};
    GetEnvironmentVariableW(L"ZW_HUB_FIXTURE_SCENARIO", scenario, 80);
    const DWORD budget = !wcscmp(scenario, L"timeout") ? 200 : 5000;
    const DWORD result = WaitForSingleObject(process, std::min(productionBudget, budget));
    FixtureEvent(result == WAIT_OBJECT_0 ? "HANDSHAKE_PROCESS_ENDED" : "HANDSHAKE_TIMED_OUT");
    return result;
}
static int FixtureMessage(HWND, LPCWSTR, LPCWSTR, UINT) {
    FixtureEvent("MESSAGE_REPORTED");
    return IDOK;
}

#define ShellExecuteExW FixtureExecute
#define WaitForSingleObject FixtureWait
#define MessageBoxW FixtureMessage
#include "ZwPluginHub.cpp"
#undef MessageBoxW
#undef WaitForSingleObject
#undef ShellExecuteExW

extern "C" int cvxCmdFunc(const char* name, void* callback, int) {
    return fixtureCommands.emplace(name, callback).second ? 0 : 1;
}
extern "C" int cvxCmdFuncUnload(const char* name) {
    fixtureCommands.erase(name);
    return 0;
}
extern "C" int cvxCmdBuffer(const char* command, int) {
    fixtureQueue.emplace_back(command);
    if (!strcmp(command, "~ZwPluginHubStart")) {
        ++fixtureStartQueued;
        FixtureEvent("QUEUE_BUSINESS_START");
    }
    return 0;
}
extern "C" int ZwPluginDataInit(const char* path, szwPluginData* data) {
    FixtureEvent("SDK_DATA_INIT");
    if (strlen(path) >= sizeof(data->path))
        return 1;
    strcpy(data->path, path);
    return 0;
}
extern "C" int ZwPluginLoad(szwPluginData data) {
    FixtureEvent("SDK_BUSINESS_LOAD");
    HMODULE module = LoadLibraryW(hub::wide(data.path).c_str());
    if (!module)
        return 1;
    fixtureBusiness.push_back(module);
    const auto init = reinterpret_cast<int (*)()>(GetProcAddress(module, "ArtFixtureInit"));
    return init ? init() : 1;
}
extern "C" __declspec(dllexport) void FixtureDrainQueue() {
    for (int i = 0; i < 100 && !fixtureQueue.empty(); ++i) {
        auto command = fixtureQueue.front();
        fixtureQueue.pop_front();
        if (!command.empty() && command.front() == '~')
            command.erase(command.begin());
        auto found = fixtureCommands.find(command);
        if (found != fixtureCommands.end())
            reinterpret_cast<void (*)()>(found->second)();
    }
}
extern "C" __declspec(dllexport) void FixtureForceBusinessStart() {
    auto found = fixtureCommands.find("ZwPluginHubStart");
    if (found != fixtureCommands.end()) {
        FixtureEvent("FORCE_REGISTERED_START");
        reinterpret_cast<void (*)()>(found->second)();
    }
}
extern "C" __declspec(dllexport) int FixtureBusinessLoads() {
    return static_cast<int>(fixtureBusiness.size());
}
extern "C" __declspec(dllexport) int FixtureStartQueued() {
    return fixtureStartQueued;
}
extern "C" __declspec(dllexport) int FixtureManagerRegistered() {
    return fixtureCommands.count("ZwPluginHubManage") ? 1 : 0;
}
extern "C" __declspec(dllexport) int FixtureManagerAlive() {
    return fixtureManager && WaitForSingleObject(fixtureManager, 0) == WAIT_TIMEOUT;
}
extern "C" __declspec(dllexport) void FixtureFinishManager() {
    if (fixtureManager) {
        if (WaitForSingleObject(fixtureManager, 5000) != WAIT_OBJECT_0)
            TerminateProcess(fixtureManager, 99);  // Only the fake helper spawned by this fixture.
        CloseHandle(fixtureManager);
        fixtureManager = nullptr;
    }
}
