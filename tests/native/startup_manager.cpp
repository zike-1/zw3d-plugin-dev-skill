#include "startup_event.h"
#include <shellapi.h>
#include <filesystem>

int wmain() {
    FixtureEvent("MANAGER_STARTED");
    int count = 0;
    wchar_t** arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    bool apply = false, parent = false;
    std::filesystem::path target;
    for (int i = 1; i < count; ++i) {
        std::wstring argument = arguments[i];
        apply |= argument == L"/apply";
        parent |= argument.rfind(L"/startup-parent=", 0) == 0;
        if (argument.rfind(L"/target=", 0) == 0)
            target = argument.substr(8);
    }
    LocalFree(arguments);
    if (!apply || !parent || target.empty()) {
        FixtureEvent("MANAGER_BAD_PROTOCOL");
        return 21;
    }
    if (std::filesystem::exists(target / L"apilibs" / L"ZwPluginHub" / L"transaction" / L"journal.txt"))
        FixtureEvent("MANAGER_SAW_UNFINISHED_TRANSACTION");
    wchar_t scenario[80]{};
    GetEnvironmentVariableW(L"ZW_HUB_FIXTURE_SCENARIO", scenario, 80);
    if (!wcscmp(scenario, L"timeout"))
        Sleep(1000);
    if (!wcscmp(scenario, L"failure")) {
        FixtureEvent("MANAGER_FINISHED_FAILURE");
        return 13;
    }
    FixtureEvent("MANAGER_FINISHED_SUCCESS");
    return 0;
}
