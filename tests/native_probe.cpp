// Test-only SDK driver. Never included in the skill's runtime or a plugin installer.
#include "../framework/common.h"
#include "zwapi_cmd.h"
#include "zwapi_ui_ribbon.h"
#include <cstring>
using namespace hub;

static HMODULE self;
static fs::path target, output;
static bool registered;
static UINT_PTR selectionTimer;
static unsigned selectionChecks;

static void initializeVisibility(szwRibbonActionListVisibleData& data);
static void groupVisibility(std::string& report, const std::string& name) {
    int visible = -1;
    auto rc = ZwUiRibbonActionVisibleGet("ZwPluginHubPage", name.c_str(), nullptr, &visible);
    report += "group-window|" + name + "|" + std::to_string((int)rc) + "|" +
              std::to_string(visible) + "\n";
    szwRibbonActionListVisibleData group;
    initializeVisibility(group);
    strcpy(group.ribbonPageName, "ZwPluginHubPage");
    strcpy(group.groupName, name.c_str());
    rc = ZwUiRibbonActionListVisibleGet(1, &group);
    report += "group|" + name + "|" + std::to_string((int)rc) + "|" +
              std::to_string(group.visibility) + "\n";
}
static void initializeVisibility(szwRibbonActionListVisibleData& data) {
    auto rc = ZwUiRibbonActionListVisibleDataInit(&data);
    require(rc == 0, "SDK ribbon visibility data initialization failed: " +
                         std::to_string((int)rc));
    data.visibility = -1;
}
static void negativeControls(std::string& report) {
    int visible = -1;
    auto rc = ZwUiRibbonPageVisibleGet("ZzHubAcceptanceMissingPage", &visible);
    report += "negative|page|" + std::to_string((int)rc) + "|" +
              std::to_string(visible) + "\n";
    visible = -1;
    rc = ZwUiRibbonActionVisibleGet("ZwPluginHubPage", "ZzHubAcceptanceMissingGroup", nullptr,
                                    &visible);
    report += "negative|group|" + std::to_string((int)rc) + "|" +
              std::to_string(visible) + "\n";
    visible = -1;
    rc = ZwUiRibbonActionVisibleGet("ZwPluginHubPage", "HubManagementGroup",
                                    "ZzHubAcceptanceMissingControl", &visible);
    report += "negative|control|" + std::to_string((int)rc) + "|" +
              std::to_string(visible) + "\n";
    // The batch API must not leave a default/sentinel value looking like a real control.
    szwRibbonActionListVisibleData missing;
    initializeVisibility(missing);
    strcpy(missing.ribbonPageName, "ZwPluginHubPage");
    strcpy(missing.groupName, "HubManagementGroup");
    strcpy(missing.controlName, "ZzHubAcceptanceMissingControl");
    rc = ZwUiRibbonActionListVisibleGet(1, &missing);
    report += "negative|control-list|" + std::to_string((int)rc) + "|" +
              std::to_string(missing.visibility) + "\n";
}

static void finish() {
    try {
        auto plugins = installed(target);
        std::string report = "Hub SDK acceptance\n";
        auto log = userData(target, "org.zwtools.plugin-hub") / L"startup.log";
        if (fs::exists(log))
            report += read(log);
        int visible = -1;
        auto rc = ZwUiRibbonPageVisibleGet("ZwPluginHubPage", &visible);
        report += "page|" + std::to_string((int)rc) + "|" + std::to_string(visible) + "\n";
        visible = -1;
        rc = ZwUiRibbonActionVisibleGet("QuickPrimer", "Start", nullptr, &visible);
        report += "reference-group-window|" + std::to_string((int)rc) + "|" +
                  std::to_string(visible) + "\n";
        szwRibbonActionListVisibleData reference;
        initializeVisibility(reference);
        strcpy(reference.ribbonPageName, "QuickPrimer");
        strcpy(reference.groupName, "Start");
        rc = ZwUiRibbonActionListVisibleGet(1, &reference);
        report += "reference-group|" + std::to_string((int)rc) + "|" +
                  std::to_string(reference.visibility) + "\n";
        groupVisibility(report, "HubManagementGroup");
        for (auto& plugin : plugins) {
            report += "installed|" + plugin.at("id") + "|" + plugin.at("version") + "\n";
            if (plugin.at("type") == "dll") {
                auto file = fs::path(wide(plugin.at("entry"))).filename();
                report += "module|" + plugin.at("prefix") + "|" +
                          (GetModuleHandleW(file.c_str()) ? "1" : "0") + "\n";
            }
            groupVisibility(report, "HubPlugin_" + plugin.at("prefix"));
            for (int i = 0; i < std::stoi(plugin.at("commands")); ++i) {
                szwRibbonActionListVisibleData item;
                initializeVisibility(item);
                strcpy(item.ribbonPageName, "ZwPluginHubPage");
                strcpy(item.groupName, ("HubPlugin_" + plugin.at("prefix")).c_str());
                auto id = plugin.at("cmd." + std::to_string(i) + ".id");
                strcpy(item.controlName, action(id).c_str());
                rc = ZwUiRibbonActionListVisibleGet(1, &item);
                report += "action|" + id + "|" + std::to_string((int)rc) + "|" +
                          std::to_string(item.visibility) + "\n";
            }
        }
        szwRibbonActionListVisibleData manager;
        initializeVisibility(manager);
        strcpy(manager.ribbonPageName, "ZwPluginHubPage");
        strcpy(manager.groupName, "HubManagementGroup");
        strcpy(manager.controlName, "ID_ZpHub_ZwPluginHubManage");
        rc = ZwUiRibbonActionListVisibleGet(1, &manager);
        report +=
            "manager|" + std::to_string((int)rc) + "|" + std::to_string(manager.visibility) + "\n";
        negativeControls(report);
        wchar_t exeLog[32768]{};
        DWORD n = GetEnvironmentVariableW(L"ZW_HUB_EXE_PROBE", exeLog, 32768);
        bool hasNotes = std::any_of(plugins.begin(), plugins.end(),
                                    [](auto& p) { return p.at("id") == "org.zwtools.art-notes"; });
        if (hasNotes && n && n < 32768)
            for (int i = 0; i < 50 && !fs::exists(exeLog); ++i)
                Sleep(100);
        atomicWrite(output, report);
    } catch (const std::exception& e) {
        try {
            atomicWrite(output, "FAILED|" + std::string(e.what()));
        } catch (...) {
        }
    }
}
static void run() {
    try {
        for (auto& p : installed(target)) {
            if (p.at("id") == "org.zwtools.art-hello")
                cvxCmdBuffer("~ArtHelloShow", 0);
            if (p.at("id") == "org.zwtools.art-notes") {
                // The complete editor has normal interactive behavior. Test its explicit
                // CLI probe separately; do not pretend this clicks the real toolbar button.
                wchar_t log[32768]{};
                DWORD count = GetEnvironmentVariableW(L"ZW_HUB_EXE_PROBE", log, 32768);
                require(count && count < 32768, "Missing EXE probe path");
                auto file = within(store(target) / L"plugins" / wide(p.at("id")) /
                                       wide(p.at("version")), p.at("entry"));
                auto command = quote(file) + L" /probe=" + quote(fs::path(log));
                STARTUPINFOW startup = {sizeof(startup)};
                startup.dwFlags = STARTF_USESHOWWINDOW; startup.wShowWindow = SW_HIDE;
                PROCESS_INFORMATION process = {};
                require(CreateProcessW(file.c_str(), command.data(), nullptr, nullptr, FALSE,
                                       CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process),
                        "EXE probe failed to start");
                Handle child(process.hProcess), thread(process.hThread);
                require(WaitForSingleObject(child.value, 10000) == WAIT_OBJECT_0, "EXE probe timeout");
                DWORD code = 1;
                require(GetExitCodeProcess(child.value, &code) && code == 0, "EXE probe failed");
            }
        }
        cvxCmdBuffer("~ZzHubAcceptanceFinish", 0);
    } catch (...) {
        finish();
    }
}
static void start() {
    // Observe the Hub's normal startup; never start business loading on its behalf.
    cvxCmdBuffer("~ZzHubAcceptanceRun", 0);
}
static void CALLBACK waitForPage(HWND, UINT, UINT_PTR timer, DWORD) {
    bool visible = true;
    try {
        for (auto name : {std::string("HubManagementGroup")}) {
            int state = -1;
            visible = visible && ZwUiRibbonActionVisibleGet("ZwPluginHubPage", name.c_str(),
                                                            nullptr, &state) == 0 && state == 1;
        }
        for (auto& plugin : installed(target)) {
            int state = -1;
            auto name = "HubPlugin_" + plugin.at("prefix");
            visible = visible && ZwUiRibbonActionVisibleGet("ZwPluginHubPage", name.c_str(),
                                                            nullptr, &state) == 0 && state == 1;
        }
    } catch (...) {
        visible = false;
    }
    if (visible || ++selectionChecks >= 120) {
        KillTimer(nullptr, timer);
        selectionTimer = 0;
        // A timeout records the actual flags; it cannot manufacture a visible page.
        cvxCmdBuffer("~ZzHubAcceptanceRun", 0);
    }
}
extern "C" __declspec(dllexport) int ZzHubAcceptanceProbeInit() {
    wchar_t p[32768]{};
    DWORD n = GetEnvironmentVariableW(L"ZW_HUB_PROBE", p, 32768);
    if (!n || n >= 32768)
        return 0;
    output = p;
    target = modulePath(self).parent_path().parent_path();
    if (cvxCmdFunc("ZzHubAcceptanceStart", (void*)start, VX_CODE_GENERAL) ||
        cvxCmdFunc("ZzHubAcceptanceRun", (void*)run, VX_CODE_GENERAL) ||
        cvxCmdFunc("ZzHubAcceptanceFinish", (void*)finish, VX_CODE_GENERAL))
        return 1;
    registered = true;
    if (GetEnvironmentVariableW(L"ZW_HUB_REQUIRE_PAGE_SELECTION", nullptr, 0)) {
        selectionChecks = 0;
        selectionTimer = SetTimer(nullptr, 0, 1000, waitForPage);
        if (!selectionTimer)
            return 1;
    } else
        cvxCmdBuffer("~ZzHubAcceptanceStart", 0);
    return 0;
}
extern "C" __declspec(dllexport) int ZzHubAcceptanceProbeExit() {
    if (selectionTimer) {
        KillTimer(nullptr, selectionTimer);
        selectionTimer = 0;
    }
    if (registered)
        for (auto name : {"ZzHubAcceptanceStart", "ZzHubAcceptanceRun", "ZzHubAcceptanceFinish"})
            cvxCmdFuncUnload(name);
    registered = false;
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH)
        self = instance;
    return TRUE;
}
