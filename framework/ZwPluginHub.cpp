#include "common.h"
#include "zwapi_cmd.h"
#include "zwapi_global_apply.h"
#include <array>
#include <cstring>
#include <utility>
using namespace hub;

namespace {
HMODULE self = nullptr;
fs::path target;
std::vector<std::string> registered;
struct ExternalCommand {
    Fields plugin;
    int command;
};
std::vector<ExternalCommand> external;
std::string loads;
bool initialized = false;
bool pluginsStarted = false;
bool pluginsBlocked = false;

bool startProcess(const fs::path& executable, const std::wstring& args, bool wait,
                  bool elevate = false) {
    SHELLEXECUTEINFOW s = {sizeof(s)};
    s.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI;
    s.lpVerb = elevate ? L"runas" : L"open";
    s.lpFile = executable.c_str();
    s.lpParameters = args.c_str();
    s.nShow = wait ? SW_HIDE : SW_SHOWNORMAL;
    if (!ShellExecuteExW(&s))
        return false;
    Handle process(s.hProcess);
    if (!wait)
        return true;
    if (WaitForSingleObject(process.value, 30000) != WAIT_OBJECT_0)
        return false;
    DWORD code = 1;
    GetExitCodeProcess(process.value, &code);
    return code == 0;
}
void manage() {
    if (!startProcess(store(target) / L"HubManager.exe", L"/target=" + quote(target), false))
        MessageBoxW(nullptr, L"管理器未能打开，请检查工具箱安装。", L"扩展工具", MB_ICONERROR);
}
bool launchTool(const fs::path& file, std::wstring args, const fs::path& data, bool wait) {
    std::vector<std::wstring> values;
    wchar_t* inherited = GetEnvironmentStringsW();
    if (!inherited)
        return false;
    for (auto p = inherited; *p; p += wcslen(p) + 1) {
        std::wstring entry = p;
        if (entry.size() < 19 || _wcsnicmp(entry.c_str(), L"ZW_PLUGIN_DATA_DIR=", 19) != 0)
            values.push_back(entry);
    }
    FreeEnvironmentStringsW(inherited);
    values.push_back(L"ZW_PLUGIN_DATA_DIR=" + data.wstring());
    std::sort(values.begin(), values.end(),
              [](auto& a, auto& b) { return _wcsicmp(a.c_str(), b.c_str()) < 0; });
    std::vector<wchar_t> environment;
    for (auto& s : values) {
        environment.insert(environment.end(), s.begin(), s.end());
        environment.push_back(0);
    }
    environment.push_back(0);
    std::wstring command = quote(file) + (args.empty() ? L"" : L" " + args);
    STARTUPINFOW startup = {sizeof(startup)};
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = wait ? SW_HIDE : SW_SHOWNORMAL;
    PROCESS_INFORMATION process = {};
    if (!CreateProcessW(file.c_str(), command.data(), nullptr, nullptr, FALSE,
                        CREATE_UNICODE_ENVIRONMENT, environment.data(), file.parent_path().c_str(),
                        &startup, &process))
        return false;
    Handle thread(process.hThread), child(process.hProcess);
    if (!wait)
        return true;
    if (WaitForSingleObject(child.value, 30000) != WAIT_OBJECT_0)
        return false;
    DWORD code = 1;
    return GetExitCodeProcess(child.value, &code) && code == 0;
}
void launch(size_t index) {
    if (index >= external.size())
        return;
    auto& c = external[index];
    auto& f = c.plugin;
    auto file =
        store(target) / L"plugins" / wide(f.at("id")) / wide(f.at("version")) / wide(f.at("entry"));
    auto key = "cmd." + std::to_string(c.command) + ".arguments";
    auto a = f.find(key);
    std::wstring args = a == f.end() ? L"" : wide(a->second);
    if (!launchTool(file, args, userData(target, f.at("id")), false))
        MessageBoxW(nullptr, L"工具启动失败，请在插件管理中检查安装。", L"扩展工具",
                    MB_ICONERROR);
}
template <size_t N> void externalCallback() {
    try {
        launch(N);
    } catch (...) {
        MessageBoxW(nullptr, L"工具启动失败，请检查插件文件与设置。", L"扩展工具",
                    MB_ICONERROR);
    }
}
template <size_t... N> auto callbacks(std::index_sequence<N...>) {
    return std::array<void (*)(), sizeof...(N)>{externalCallback<N>...};
}
const auto externalCallbacks = callbacks(std::make_index_sequence<128>{});
void add(const std::string& name, void (*callback)()) {
    require(cvxCmdFunc(name.c_str(), reinterpret_cast<void*>(callback), VX_CODE_GENERAL) == 0,
            "Command already registered: " + name);
    registered.push_back(name);
}
void loadPlugins() {
    if (pluginsStarted || pluginsBlocked)
        return;
    pluginsStarted = true;
    try {
        std::vector<RegistryIssue> issues;
        auto records = installed(target, &issues);
        for (const auto& issue : issues)
            loads += "failed|registry:" + issue.file + "|" + issue.error + "\n";
        for (auto& f : records) {
            size_t registrationStart = registered.size(), externalStart = external.size();
            try {
                auto dir = store(target) / L"plugins" / wide(f.at("id")) / wide(f.at("version"));
                for (auto line : split(read(dir / L"files.txt"), '\n')) {
                    if (!line.empty() && line.back() == '\r')
                        line.pop_back();
                    if (line.empty())
                        continue;
                    auto item = split(line, '|');
                    require(item.size() == 3 && sha(read(within(dir, item[0]))) == item[2],
                            "Installed plugin integrity failed");
                }
                if (f.at("type") == "dll") {
                    auto file = store(target) / L"plugins" / wide(f.at("id")) /
                                wide(f.at("version")) / wide(f.at("entry"));
                    szwPluginData data;
                    auto rc = ZwPluginDataInit(utf8(file.wstring()).c_str(), &data);
                    if (rc == 0)
                        rc = ZwPluginLoad(data);
                    loads += "load|" + f.at("id") + "|" + std::to_string((int)rc) + "\n";
                } else {
                    loads += "ready|" + f.at("id") + "|exe\n";
                    for (int i = 0; i < std::stoi(f.at("commands")); ++i) {
                        require(external.size() < externalCallbacks.size(),
                                "v1 supports at most 128 EXE commands per host");
                        size_t slot = external.size();
                        external.push_back({f, i});
                        add(f.at("cmd." + std::to_string(i) + ".id"), externalCallbacks[slot]);
                    }
                }
            } catch (const std::exception& e) {
                for (size_t i = registrationStart; i < registered.size(); ++i)
                    cvxCmdFuncUnload(registered[i].c_str());
                registered.resize(registrationStart);
                external.resize(externalStart);
                loads += "failed|" + f.at("id") + "|" + e.what() + "\n";
            }
        }
    } catch (const std::exception& e) {
        loads += "failed|registry|" + std::string(e.what()) + "\n";
    }
    try {
        atomicWrite(userData(target, "org.zwtools.plugin-hub") / L"startup.log", loads);
    } catch (...) {
    }
}
} // namespace

extern "C" __declspec(dllexport) int ZwPluginHubInit() {
    if (initialized)
        return 0;
    try {
        target = modulePath(self).parent_path().parent_path();
        validateTarget(target);
        auto pending = store(target) / L"pending";
        auto maintenance = store(target) / L"maintenance";
        bool hasPending = (fs::exists(pending) && !fs::is_empty(pending)) ||
                          (fs::exists(maintenance) && !fs::is_empty(maintenance));
        bool needsRepair = hasPending || fs::exists(store(target) / L"transaction");
        auto args = L"/quiet /apply /target=" + quote(target) + L" /startup-parent=" +
                    std::to_wstring(GetCurrentProcessId());
        // Always cross the installer lock and recover interrupted writes before loading.
        // A timed-out manager may still be working; block this session rather than race it.
        pluginsBlocked = !startProcess(store(target) / L"HubManager.exe", args, true,
                                       needsRepair && !elevated());
        loads += pluginsBlocked ? "startup|blocked\n" : "startup|ready\n";
        if (hasPending)
            loads += pluginsBlocked ? "pending|deferred\n" : "pending|applied\n";
        add("ZwPluginHubManage", manage);
        add("ZwPluginHubStart", loadPlugins);
        initialized = true;
        cvxCmdBuffer("~ZwPluginHubStart", 0);
        if (pluginsBlocked)
            atomicWrite(userData(target, "org.zwtools.plugin-hub") / L"startup.log", loads);
        return 0;
    } catch (const std::exception& e) {
        for (auto& name : registered)
            cvxCmdFuncUnload(name.c_str());
        registered.clear();
        external.clear();
        try {
            atomicWrite(userData(target, "org.zwtools.plugin-hub") / L"startup.log", e.what());
        } catch (...) {
        }
        MessageBoxW(nullptr, L"插件工具箱加载失败，请查看启动日志。", L"扩展工具",
                    MB_ICONERROR);
        return 1;
    }
}
extern "C" __declspec(dllexport) int ZwPluginHubExit() {
    // Native business plugins are owned by the official loader, and are not forcibly unloaded.
    for (auto& name : registered)
        cvxCmdFuncUnload(name.c_str());
    registered.clear();
    external.clear();
    initialized = false;
    pluginsStarted = false;
    pluginsBlocked = false;
    loads.clear();
    return 0;
}
extern "C" __declspec(dllexport) int ZwPluginHubDataDirectory(const char* id, wchar_t* buffer,
                                                              int count) {
    try {
        require(id && buffer && count > 0 && safeId(id), "Invalid data request");
        bool known = false;
        std::vector<RegistryIssue> issues;
        for (auto& f : installed(target, &issues))
            if (f.at("id") == id)
                known = true;
        require(known, "Unknown plugin");
        auto path = userData(target, id).wstring();
        require(path.size() < (size_t)count && noLinks(path), "Data path unavailable");
        std::copy(path.begin(), path.end(), buffer);
        buffer[path.size()] = 0;
        return 0;
    } catch (...) {
        return 1;
    }
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        self = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
