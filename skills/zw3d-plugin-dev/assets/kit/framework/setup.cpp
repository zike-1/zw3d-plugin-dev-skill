#include "common.h"
#include "transaction.h"
#include "xml_merge.h"
#include <commdlg.h>
#include <shlobj.h>
using namespace hub;

// A plugin installer and the shared manager use the same state machine.
static fs::path target;
static HWND window = nullptr, rootEdit = nullptr, listbox = nullptr, purgeCheck = nullptr;
static std::vector<std::string> listedIds;
static std::vector<std::string> listedSources;
static fs::path listedTarget;
static bool refreshSucceeded = false;
static HWND incomingLabel = nullptr;
static bool updatingTarget = false;
static HFONT uiFont = nullptr;
static int uiDpi = 96;
static std::string initiatingUser;
static bool cleanupSkipped = false;
static bool quiet = false;
static DWORD startupContext = 0;
static Bytes resource(int id) {
    HMODULE h = GetModuleHandleW(nullptr);
    HRSRC r = FindResourceW(h, MAKEINTRESOURCEW(id), RT_RCDATA);
    require(r != nullptr, "Missing embedded resource");
    DWORD n = SizeofResource(h, r);
    const char* p = (const char*)LockResource(LoadResource(h, r));
    require(p && n, "Empty embedded resource");
    return Bytes(p, n);
}
static std::string status;
static bool statusIsError = false;
static bool deferStatus = false;
static void showStatus() {
    if (!quiet && !status.empty())
        MessageBoxW(window, wide(status).c_str(), L"扩展工具",
                    MB_OK | (statusIsError ? MB_ICONERROR : MB_ICONINFORMATION));
}
static void result(const std::string& text) {
    status = text;
    statusIsError = false;
    if (!deferStatus) showStatus();
}
static void error(const std::string& text) {
    status = "失败：" + text;
    statusIsError = true;
    if (!deferStatus) showStatus();
}
struct FileItem {
    std::string path, hash;
    size_t size;
};
static std::vector<FileItem> fileIndex(const Bytes& bytes) {
    std::vector<FileItem> out;
    std::set<std::string> paths;
    for (auto line : split(bytes, '\n')) {
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        if (line.empty())
            continue;
        auto f = split(line, '|');
        require(f.size() == 3 && safeRelative(f[0]) && paths.insert(lower(f[0])).second,
                "Unsafe or duplicate payload path");
        auto first = lower(split(f[0], '/')[0]);
        require(first != "descriptor.ini" && first != "files.txt",
                "Payload collides with private metadata");
        size_t n = std::stoull(f[1]);
        require(n <= 64 * 1024 * 1024 && f[2].size() == 64 &&
                    std::all_of(
                        f[2].begin(), f[2].end(),
                        [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }),
                "Invalid payload hash");
        out.push_back({f[0], f[2], n});
    }
    require(!out.empty() && out.size() <= 256, "Invalid payload file count");
    return out;
}
struct Lock {
    Handle mutex;
    explicit Lock()
        : mutex(CreateMutexW(
              nullptr, FALSE,
              wide("Local\\ZwPluginHub." + sha(lower(utf8(target.wstring()))).substr(0, 24))
                  .c_str())) {
        require(mutex.value != nullptr, "Mutex unavailable");
        auto rc = WaitForSingleObject(mutex.value, 30000);
        require(rc == WAIT_OBJECT_0 || rc == WAIT_ABANDONED, "Another installation is in progress");
    }
    ~Lock() {
        ReleaseMutex(mutex.value);
    }
};
static std::string relStore(const std::string& s) {
    return "apilibs/ZwPluginHub/" + s;
}
static std::string stateRel(const std::string& id) {
    return relStore("state/" + id + ".ini");
}
static std::string versionRel(const Fields& f) {
    return relStore("plugins/" + f.at("id") + "/" + f.at("version") + "/");
}
static std::vector<Fields> registrations(bool includePending,
                                           std::vector<RegistryIssue>* issues = nullptr) {
    auto out = installed(target, issues);
    auto pending = store(target) / L"pending";
    if (includePending && fs::exists(pending))
        for (auto& e : fs::directory_iterator(pending))
            if (e.is_directory() && fs::exists(e.path() / L"operation.ini")) {
                try {
                require(noLinks(e.path()), "Linked pending operation");
                auto f = parse(read(e.path() / L"operation.ini"));
                validDescriptor(f);
                require(e.path().filename() == wide(f.at("id")) && f.count("operation") &&
                            (f.at("operation") == "install" || f.at("operation") == "remove" ||
                             f.at("operation") == "purge"), "Invalid pending identity or operation");
                auto it = std::find_if(out.begin(), out.end(),
                                       [&](const auto& p) { return p.at("id") == f.at("id"); });
                if (it != out.end())
                    *it = f;
                else
                    out.push_back(f);
                } catch (const std::exception& e2) {
                    if (!issues) throw;
                    issues->push_back({utf8(e.path().filename().wstring()) + "/operation.ini", e2.what()});
                }
            }
    return out;
}
static void conflicts(const Fields& f) {
    require(lower(f.at("prefix")).rfind("hub", 0) != 0 &&
                lower(f.at("prefix")).rfind("zwpluginhub", 0) != 0,
            "Reserved framework prefix");
    for (auto& current : installed(target))
        if (current.at("id") == f.at("id")) {
            require(current.at("prefix") == f.at("prefix") && current.at("type") == f.at("type") &&
                        current.at("entry") == f.at("entry"),
                    "Plugin identity cannot change during an update");
            auto version = [](const std::string& v) {
                std::vector<int> n;
                for (auto s : split(v, '.'))
                    n.push_back(std::stoi(s));
                return n;
            };
            require(version(f.at("version")) >= version(current.at("version")),
                    "Plugin downgrade is not supported in v1");
        }
    int externalCount = f.at("type") == "exe" ? std::stoi(f.at("commands")) : 0;
    for (auto& current : registrations(true))
        if (current.at("id") != f.at("id") && current.at("type") == "exe")
            externalCount += std::stoi(current.at("commands"));
    require(externalCount <= 128, "v1 supports at most 128 EXE commands per host");
    for (auto& other : registrations(true)) {
        if (other.at("id") == f.at("id"))
            continue;
        require(lower(other.at("prefix")) != lower(f.at("prefix")),
                "Another plugin owns this prefix");
        for (int i = 0; i < std::stoi(f.at("commands")); ++i)
            for (int j = 0; j < std::stoi(other.at("commands")); ++j)
                require(lower(f.at("cmd." + std::to_string(i) + ".id")) !=
                            lower(other.at("cmd." + std::to_string(j) + ".id")),
                        "Command collision");
    }
}
static void merge(Transaction& tx, const std::string& rel, const Bytes& xml) {
    auto p = within(target, rel);
    std::wstring merged;
    require(MergeOwnedXml(fs::exists(p) ? wide(read(p)) : L"", wide(xml), false, merged),
            "Cannot safely merge interface: " + rel);
    tx.put(rel, utf8(merged));
}
static std::string iconRel(const std::string& command) {
    require(symbol(command), "Invalid icon command identity");
    return "apilibs/icons/~ZpHub_" + command + ".png";
}
static void menus(Transaction& tx, std::vector<Fields> plugins) {
    std::sort(plugins.begin(), plugins.end(), [](const auto& a, const auto& b) {
        return a.at("id") < b.at("id");
    });
    Bytes actions = "<Actions name=\"ZW3D\" version=\"1700\" system=\"false\"><Action "
                    "name=\"ID_ZpHub_ZwPluginHubManage\" "
                    "type=\"button\"><Text><Ribbon>插件管理</Ribbon><Menu>插件管理</Menu></"
                    "Text><Icon>~ZpHub_ZwPluginHubManage</Icon><Hint>查看、更新和卸载插件</Hint>"
                    "<Script>~ZwPluginHubManage</Script></Action>";
    tx.put(iconRel("ZwPluginHubManage"), resource(903));
    Bytes page = "<RibbonPages><RibbonPage name=\"ZwPluginHubPage\" text=\"扩展工具\" "
                 "visible=\"true\"><RibbonGroup name=\"HubManagementGroup\" text=\"插件管理\" "
                 "visible=\"true\"><GroupPanel "
                 "name=\"HubManagementCommands\"><Control action=\"ID_ZpHub_ZwPluginHubManage\" "
                 "visible=\"true\" buttonStyle=\"4\"/></GroupPanel></RibbonGroup>";
    for (auto& f : plugins) {
        page += "<RibbonGroup name=\"HubPlugin_" + escape(f.at("prefix")) + "\" text=\"" +
                escape(f.at("name")) + "\" visible=\"true\"><GroupPanel name=\"HubCommands_" +
                escape(f.at("prefix")) + "\">";
        for (int i = 0; i < std::stoi(f.at("commands")); ++i) {
            auto b = "cmd." + std::to_string(i) + ".";
            auto id = f.at(b + "id");
            actions += "<Action name=\"" + action(id) + "\" type=\"button\"><Text><Ribbon>" +
                       escape(f.at(b + "label")) + "</Ribbon><Menu>" + escape(f.at(b + "label")) +
                       "</Menu></Text><Icon>~ZpHub_" + id + "</Icon>";
            auto hint = f.find(b + "tooltip");
            actions += "<Hint>" + escape(hint == f.end() ? f.at(b + "label") : hint->second) +
                       "</Hint><Script>~" + id + "</Script></Action>";
            auto image = f.find(b + "icon");
            if (image != f.end()) {
                auto source = within(store(target) / L"plugins" / wide(f.at("id")) /
                                         wide(f.at("version")), image->second);
                auto change = tx.changes.find(versionRel(f) + image->second);
                tx.put(iconRel(id), change != tx.changes.end() && change->second ?
                                        *change->second : read(source));
            } else {
                // One framework-owned default, copied to each stable command icon.
                tx.put(iconRel(id), resource(903));
            }
            page += "<Control name=\"" + action(id) + "\" action=\"" + action(id) +
                    "\" visible=\"true\" buttonStyle=\"4\"/>";
        }
        page += "</GroupPanel></RibbonGroup>";
    }
    actions += "</Actions>";
    page += "</RibbonPage></RibbonPages>";
    merge(tx, "apilibs/Settings/Default/ResourcePool/ZwPluginHubActions.zcui", actions);
    merge(tx, "apilibs/Settings/Default/ResourcePool/RibbonPagesUser.zcui", page);
    struct Env {
        const char* number;
        const char* folder;
        const char* layout;
    };
    const Env environments[] = {{"0", "Top", "Top"},
                                {"1", "Root", "Root"},
                                {"10", "Part", "Part"},
                                {"11", "ECAD Assembly", "EcadAsm"},
                                {"12", "ECAD Part", "EcadPart"},
                                {"13", "Assembly", "Asm"},
                                {"17", "Master Layout", "MasLayPrt"},
                                {"19", "Cam", "CAM2"},
                                {"2", "Z3", "Z3"},
                                {"3", "Sketch", "Sketch"},
                                {"4", "Sheet", "Sheet"},
                                {"5", "Packet", "Packet"},
                                {"6", "Cam", "CAM"},
                                {"7", "Animation", "Animation"},
                                {"8", "ExplodedView", "ExpView"},
                                {"9", "3DSketch", "Sketch3D"}};
    for (auto& e : environments) {
        std::string n = e.number;
        Bytes xml = "<Strategy profileType=\"UIProfile\" environment=\"" + n +
                    "\" role=\"#AllRoles\"><DefaultCustomizations><Insert type=\"RibbonPage\" "
                    "name=\"ZwPluginHubPage\" topCollection=\"Layout_" +
                    n + "_" + e.layout +
                    "\" leftSibling=\"#InsertAtLast\"/></DefaultCustomizations></Strategy>";
        merge(tx,
              "apilibs/Settings/Default/Strategy/Environment-" + n + "-" + e.folder +
                  "/LayoutStrategy.zcui",
              xml);
    }
}
static void verifyFiles(const Fields& f, const Bytes& index, const std::vector<Bytes>& blobs) {
    auto items = fileIndex(index);
    require(items.size() == blobs.size(), "Payload count differs");
    bool entry = false;
    for (size_t i = 0; i < items.size(); ++i) {
        require(items[i].size == blobs[i].size() && items[i].hash == sha(blobs[i]),
                "Payload integrity failed");
        if (items[i].path == f.at("entry"))
            entry = true;
    }
    require(entry, "Entry not in payload");
}
static void compatible(const Fields& f) {
    auto it = f.find("api.count");
    require(it != f.end(), "Compatibility metadata is missing");
    int count = std::stoi(it->second);
    require(count >= 0 && count <= 10000, "Invalid API count");
    HMODULE host =
        LoadLibraryExW((target / L"ZW3D.dll").c_str(), nullptr, DONT_RESOLVE_DLL_REFERENCES);
    require(host != nullptr, "Host interface library unavailable");
    bool ok = true;
    for (int i = 0; i < count; ++i) {
        auto name = f.find("api." + std::to_string(i));
        if (name == f.end() || !GetProcAddress(host, name->second.c_str())) {
            ok = false;
            break;
        }
    }
    FreeLibrary(host);
    require(ok, "Plugin interfaces are not present in this host");
}
#include "framework_update.h"
static Fields versionIdentity(Fields f) {
    // Host/framework import checks can grow without changing a plugin release.
    for (auto it = f.begin(); it != f.end();) {
        if (it->first.rfind("api.", 0) == 0) it = f.erase(it);
        else ++it;
    }
    return f;
}
static void installNow(const Fields& f, const Bytes& index, const std::vector<Bytes>& blobs,
                       bool embedded) {
    validDescriptor(f);
    conflicts(f);
    compatible(f);
    verifyFiles(f, index, blobs);
    Transaction tx(target);
    if (embedded)
        bootstrap(tx);
    auto items = fileIndex(index);
    for (size_t i = 0; i < items.size(); ++i) {
        auto rel = versionRel(f) + items[i].path;
        auto p = within(target, rel);
        if (fs::exists(p))
            require(sha(read(p)) == items[i].hash,
                    "An immutable version differs; increment plugin version");
        else
            tx.put(rel, blobs[i]);
    }
    auto descriptorPath = within(target, versionRel(f) + "descriptor.ini");
    if (fs::exists(descriptorPath)) {
        require(versionIdentity(parse(read(descriptorPath))) == versionIdentity(f) &&
                    read(within(target, versionRel(f) + "files.txt")) == index,
                "同一版本的清单或文件集合不同，请增加插件版本号。");
    }
    tx.put(versionRel(f) + "descriptor.ini", encode(f));
    tx.put(versionRel(f) + "files.txt", index);
    tx.put(stateRel(f.at("id")), encode(f));
    auto active = installed(target);
    for (const auto& previous : active) {
        if (previous.at("id") != f.at("id")) continue;
        for (int i = 0; i < std::stoi(previous.at("commands")); ++i) {
            auto oldId = previous.at("cmd." + std::to_string(i) + ".id");
            bool retained = false;
            for (int j = 0; j < std::stoi(f.at("commands")); ++j)
                retained = retained || lower(f.at("cmd." + std::to_string(j) + ".id")) == lower(oldId);
            if (!retained) tx.erase(iconRel(oldId));
        }
    }
    active.erase(std::remove_if(active.begin(), active.end(),
                                [&](const auto& a) { return a.at("id") == f.at("id"); }),
                 active.end());
    active.push_back(f);
    menus(tx, active);
    tx.commit();
}
static void purgeData(const std::string& id) {
    auto p = userData(target, id);
    require(safeId(id) && noLinks(p), "Invalid data cleanup path");
    if (!fs::exists(p))
        return;
    for (auto& e : fs::recursive_directory_iterator(p))
        require(noLinks(e.path()), "Data cleanup contains linked files");
    fs::remove_all(p);
}
static bool emptyDirectoryTree(const fs::path& root) {
    require(noLinks(root), "Linked version folder");
    for (auto& e : fs::recursive_directory_iterator(root)) {
        require(noLinks(e.path()), "Linked version content");
        if (!e.is_directory())
            return false;
    }
    return true;
}
static void pruneEmptyDirectories(const fs::path& root) {
    if (!fs::exists(root))
        return;
    require(noLinks(root), "Linked version directory");
    std::vector<fs::path> dirs{root};
    for (auto& e : fs::recursive_directory_iterator(root)) {
        require(noLinks(e.path()), "Linked version content");
        if (e.is_directory())
            dirs.push_back(e.path());
    }
    std::sort(dirs.begin(), dirs.end(),
              [](auto& a, auto& b) { return a.wstring().size() > b.wstring().size(); });
    for (auto& p : dirs)
        if (fs::exists(p) && fs::is_empty(p))
            fs::remove(p);
}
static void removeNow(const Fields& f, bool purge) {
    validDescriptor(f);
    auto id = f.at("id");
    Transaction tx(target);
    auto active = installed(target);
    active.erase(std::remove_if(active.begin(), active.end(),
                                [&](const auto& a) { return a.at("id") == id; }),
                 active.end());
    auto versions = store(target) / L"plugins" / wide(id);
    if (fs::exists(versions))
        for (auto& e : fs::directory_iterator(versions)) {
            require(e.is_directory() && noLinks(e.path()), "Invalid version folder");
            if (!fs::exists(e.path() / L"descriptor.ini")) {
                require(emptyDirectoryTree(e.path()), "Incomplete version data");
                continue;
            }
            auto desc = parse(read(e.path() / L"descriptor.ini"));
            validDescriptor(desc);
            require(desc.at("id") == id, "Version identity differs");
            auto index = read(e.path() / L"files.txt");
            for (auto& file : fileIndex(index)) {
                auto rel = versionRel(desc) + file.path;
                auto p = within(target, rel);
                if (fs::exists(p))
                    require(sha(read(p)) == file.hash,
                            "Plugin file was externally changed; uninstall stopped");
                tx.erase(rel);
            }
            tx.erase(versionRel(desc) + "descriptor.ini");
            tx.erase(versionRel(desc) + "files.txt");
        }
    for (int i = 0; i < std::stoi(f.at("commands")); ++i)
        tx.erase(iconRel(f.at("cmd." + std::to_string(i) + ".id")));
    tx.erase(stateRel(id));
    menus(tx, active);
    tx.commit();
    try {
        pruneEmptyDirectories(versions);
        if (purge) {
            auto owner = f.find("purge.user");
            if (owner != f.end() && owner->second != currentUserSid()) cleanupSkipped = true;
            else purgeData(id);
        }
    } catch (const std::exception& e) {
        throw std::runtime_error("程序和入口已卸载，但目录或个人数据未完全清理：" + std::string(e.what()));
    }
}
static void discardPending(const std::string& id) {
    auto dir = store(target) / L"pending" / wide(id);
    require(safeId(id) && noLinks(dir), "Invalid pending directory");
    if (fs::exists(dir)) {
        for (auto& e : fs::recursive_directory_iterator(dir))
            require(noLinks(e.path()), "Linked pending payload");
        fs::remove_all(dir);
    }
}
static void stagePending(Fields f, const std::string& op, const Bytes& index = {},
                         const std::vector<Bytes>& blobs = {}, bool embedded = false) {
    auto id = f.at("id");
    validDescriptor(f);
    conflicts(f);
    Transaction tx(target);
    auto base = relStore("pending/" + id + "/");
    if (op == "install") {
        compatible(f);
        verifyFiles(f, index, blobs);
        if (embedded && hostProcesses(target).empty())
            bootstrap(tx);
        auto items = fileIndex(index);
        for (size_t i = 0; i < items.size(); ++i)
            tx.put(base + "payload/" + items[i].path, blobs[i]);
        tx.put(base + "files.txt", index);
    }
    if (op == "install") {
        auto existing = within(target, versionRel(f) + "descriptor.ini");
        if (fs::exists(existing))
            require(versionIdentity(parse(read(existing))) == versionIdentity(f) && read(within(target, versionRel(f) + "files.txt")) == index,
                    "同一版本内容不同，请增加版本号。");
        auto pending = store(target) / L"pending" / wide(id) / L"operation.ini";
        if (fs::exists(pending)) {
            auto previous = parse(read(pending));
            if (previous.at("operation") == "install") {
                require(previous.at("prefix") == f.at("prefix") && previous.at("type") == f.at("type") &&
                            previous.at("entry") == f.at("entry"), "待安装插件的稳定身份不能改变。");
                require(frameworkVersion(previous) <= frameworkVersion(f),
                        "不能用旧版本覆盖待更新版本；如需保留当前版本，请先取消待处理请求。");
            }
            if (previous.at("operation") == "install" && previous.at("version") == f.at("version")) {
                previous.erase("operation");
                require(versionIdentity(previous) == versionIdentity(f) && read(pending.parent_path() / L"files.txt") == index,
                        "同一待安装版本内容不同，请增加版本号。");
            }
        }
    }
    if (embedded && !hostProcesses(target).empty() && frameworkNeedsUpdate()) stageFramework(tx);
    f["operation"] = op;
    tx.put(base + "operation.ini", encode(f));
    tx.commit();
}
static void applyMaintenance();
static void applyPending(DWORD startupPid) {
    require(hostProcesses(target).empty() || startupSafe(target, startupPid),
            "Pending changes can only be applied before managed DLLs load");
    require(!fs::exists(store(target) / L"framework-next" / L"metadata.ini"),
            "工具箱正在等待升级。请关闭中望3D，待升级完成后重新启动。");
    applyMaintenance();
    auto dir = store(target) / L"pending";
    if (!fs::exists(dir))
        return;
    std::vector<fs::path> entries;
    for (auto& e : fs::directory_iterator(dir))
        if (e.is_directory())
            entries.push_back(e.path());
    for (auto& p : entries) {
        if (!fs::exists(p / L"operation.ini"))
            continue;
        require(noLinks(p), "Linked pending operation");
        auto f = parse(read(p / L"operation.ini"));
        validDescriptor(f);
        auto op = f.at("operation");
        f.erase("operation");
        if (op == "install") {
            auto idx = read(p / L"files.txt");
            std::vector<Bytes> blobs;
            for (auto& i : fileIndex(idx))
                blobs.push_back(read(within(p / L"payload", i.path)));
            installNow(f, idx, blobs, false);
        } else {
            require(op == "remove" || op == "purge", "Unknown pending operation");
            removeNow(f, op == "purge");
        }
        discardPending(f.at("id"));
    }
}
static void installEmbedded() {
    auto f = parse(resource(2000));
    validDescriptor(f);
    auto index = resource(1000);
    std::vector<Bytes> blobs;
    for (size_t i = 0; i < fileIndex(index).size(); ++i)
        blobs.push_back(resource(1001 + (int)i));
    verifyFiles(f, index, blobs);
    if (hostProcesses(target).empty()) {
        applyFramework();
        installNow(f, index, blobs, true);
        discardPending(f.at("id"));
        result("安装完成。重新打开2027，在“扩展工具”功能区使用。");
    } else {
        bool upgrade = frameworkNeedsUpdate();
        require(!upgrade || !fs::exists(target / L"apilibs" / L"ZwPluginHub.dll") ||
                    fs::exists(store(target) / L"framework.ini"),
                "这一次旧工具箱迁移需要先关闭中望3D，再运行安装包。进入新版后支持等待重启升级。");
        stagePending(f, "install", index, blobs, true);
        if (upgrade) startFrameworkWorker();
        result(upgrade ? "插件和工具箱升级已暂存。关闭中望3D后自动更新，再启动生效。" :
                         "已登记，等待重启中望3D后安装。");
    }
}
static void removeId(const std::string& id, bool purge) {
    require(safeId(id), "Invalid plugin ID");
    auto all = registrations(true);
    auto it = std::find_if(all.begin(), all.end(), [&](const auto& f) { return f.at("id") == id; });
    require(it != all.end(), "Plugin is not installed");
    if (purge) {
        require(initiatingUser.empty() || initiatingUser == currentUserSid(),
                "管理员账户与使用账户不同，彻底清理已停止。请使用普通卸载，或由原账户清理设置。");
        (*it)["purge.user"] = currentUserSid();
    }
    if (hostProcesses(target).empty()) {
        removeNow(*it, purge);
        discardPending(id);
        result(purge ? "插件已卸载，当前账户的数据已清理。" : "插件已卸载，个人设置和日志已保留。");
    } else {
        stagePending(*it, purge ? "purge" : "remove");
        result("卸载已登记，等待重启。其他插件继续可用。");
    }
}
#include "maintenance.h"
static std::vector<fs::path> detect() {
    std::vector<fs::path> out;
    for (wchar_t drive = L'C'; drive <= L'Z'; ++drive)
        for (auto program : {L"Program Files", L"Program Files (x86)"}) {
            fs::path base = std::wstring(1, drive) + L":\\" + program + L"\\ZWSOFT";
            std::error_code ec;
            if (!fs::is_directory(base, ec))
                continue;
            for (auto& e : fs::directory_iterator(base, ec)) {
                try {
                    validateTarget(e.path());
                    out.push_back(e.path());
                } catch (...) {
                }
            }
        }
    return out;
}
static void refresh() {
    refreshSucceeded = false;
    SendMessageW(listbox, LB_RESETCONTENT, 0, 0);
    listedIds.clear(); listedSources.clear(); listedTarget.clear();
    SendMessageW(purgeCheck, BM_SETCHECK, BST_UNCHECKED, 0);
    std::vector<RegistryIssue> issues;
    auto records = registrations(true, &issues);
    Bytes log;
    auto logFile = userData(target, "org.zwtools.plugin-hub") / L"startup.log";
    if (fs::exists(logFile)) log = read(logFile);
    for (auto& f : records) {
        std::wstring state = L"已安装；尚未确认本次加载";
        std::wstring version = wide(f.at("version"));
        if (f.count("operation")) {
            auto op = f.at("operation");
            state = op == "install" ? L"待安装／更新，等待重启" :
                    op == "purge" ? L"待卸载并清理数据，等待重启" : L"待卸载，等待重启";
            auto current = store(target) / L"state" / wide(f.at("id") + ".ini");
            if (op == "install" && fs::exists(current)) {
                try {
                    auto previous = parse(read(current));
                    validDescriptor(previous);
                    version = wide(previous.at("version")) + L" → " + version;
                } catch (const std::exception&) {
                    version = L"当前登记损坏 → " + version;
                }
            }
        } else {
            auto id = f.at("id");
            if (log.find("failed|" + id + "|") != Bytes::npos) state = L"最近启动：加载失败";
            else if (log.find("ready|" + id + "|") != Bytes::npos ||
                     log.find("load|" + id + "|0\n") != Bytes::npos ||
                     log.find("load|" + id + "|-311\n") != Bytes::npos) state = L"最近启动：入口已加载";
            else if (log.find("load|" + id + "|") != Bytes::npos) state = L"最近启动：加载返回异常，请查看日志";
        }
        auto line = wide(f.at("name")) + L"  " + version + L"  [" + state + L"]";
        SendMessageW(listbox, LB_ADDSTRING, 0, (LPARAM)line.c_str());
        listedIds.push_back(f.at("id"));
        listedSources.push_back("");
    }
    for (auto& issue : issues) {
        auto line = L"登记损坏：" + wide(issue.file) + L" — " + wide(issue.error);
        auto source = (issue.file.find('/') == std::string::npos ? "state/" : "pending/") + issue.file;
        if (fs::exists(within(target, maintenanceRel(source)))) line += L" [待修复／隔离，等待重启]";
        SendMessageW(listbox, LB_ADDSTRING, 0, (LPARAM)line.c_str()); listedIds.push_back("");
        listedSources.push_back(source);
    }
    auto maintenance = within(store(target), "maintenance");
    if (fs::exists(maintenance)) for (auto& e : fs::directory_iterator(maintenance)) {
        try {
            require(noLinks(e.path()), "Linked maintenance request");
            auto f = parse(read(e.path()));
            auto source = f.at("source"); stateSource(source);
            if (std::find(listedSources.begin(), listedSources.end(), source) != listedSources.end()) continue;
            auto line = L"待修复／隔离：" + wide(source) + L" [等待重启；如登记已变化，请取消并重新检查]";
            SendMessageW(listbox, LB_ADDSTRING, 0, (LPARAM)line.c_str());
            listedIds.push_back(""); listedSources.push_back(source);
        } catch (const std::exception& e2) {
            auto line = L"修复请求损坏：" + wide(e2.what());
            SendMessageW(listbox, LB_ADDSTRING, 0, (LPARAM)line.c_str());
            listedIds.push_back(""); listedSources.push_back("");
        }
    }
    listedTarget = target;
    refreshSucceeded = true;
    EnableWindow(GetDlgItem(window, 103), TRUE);
    EnableWindow(GetDlgItem(window, 105), TRUE);
    EnableWindow(GetDlgItem(window, 107), FALSE);
    EnableWindow(GetDlgItem(window, 108), FALSE);
}
static void useTarget() {
    wchar_t p[32768];
    GetWindowTextW(rootEdit, p, 32768);
    target = fs::absolute(p).lexically_normal();
    validateTarget(target);
}
static void runOperation(const std::function<void()>& body) {
    status.clear();
    deferStatus = true;
    try {
        useTarget();
        {
            Lock lock;
            Transaction(target, startupContext).restore();
            body();
            refresh();
        }  // Release the installation mutex before showing an outcome dialog.
    } catch (const std::exception& e) {
        error(e.what());
        try { refresh(); } catch (...) {}
    }
    deferStatus = false;
    showStatus();
}
static void cancelId(const std::string& id) {
    require(safeId(id), "Invalid plugin ID");
    discardPending(id);
    result("待处理请求已取消，当前已安装版本保持不变。");
}
static void actionGui(const std::wstring& operation) {
    if (elevated()) {
        runOperation([&] {
            if (operation == L"/install") installEmbedded();
            else if (operation.rfind(L"/cancel=", 0) == 0) cancelId(utf8(operation.substr(8)));
            else if (operation.rfind(L"/repair=", 0) == 0) maintainRecord(utf8(operation.substr(8)), "repair");
            else if (operation.rfind(L"/isolate=", 0) == 0) maintainRecord(utf8(operation.substr(9)), "isolate");
            else if (operation.rfind(L"/cancel-maintenance=", 0) == 0) cancelMaintenance(utf8(operation.substr(20)));
            else removeId(utf8(operation.substr(11)),
                          SendMessageW(purgeCheck, BM_GETCHECK, 0, 0) == BST_CHECKED);
        });
        return;
    }
    useTarget();
    auto args = operation;
    for (auto prefix : {L"/repair=", L"/isolate=", L"/cancel-maintenance="}) {
        std::wstring key = prefix;
        if (operation.rfind(key, 0) == 0) args = key + quote(fs::path(operation.substr(key.size())));
    }
    args += L" /target=" + quote(target);
    args += L" /initiator=" + wide(currentUserSid());
    if (operation.rfind(L"/uninstall=", 0) == 0 && SendMessageW(purgeCheck, BM_GETCHECK, 0, 0) == BST_CHECKED)
        args += L" /purge";
    auto file = modulePath();
    SHELLEXECUTEINFOW se = {sizeof(se)}; se.fMask = SEE_MASK_NOCLOSEPROCESS;
    se.lpVerb = L"runas"; se.lpFile = file.c_str(); se.lpParameters = args.c_str(); se.nShow = SW_SHOWNORMAL;
    if (!ShellExecuteExW(&se)) { error("操作未启动；取消授权后没有修改插件。"); return; }
    if (se.hProcess) { WaitForSingleObject(se.hProcess, INFINITE); CloseHandle(se.hProcess); }
    refresh();
}
static void layoutManager(HWND h) {
    if (!rootEdit || !listbox || !purgeCheck) return;
    RECT r; GetClientRect(h, &r);
    auto px = [](int n) { return MulDiv(n, uiDpi, 96); };
    int margin = px(20), width = r.right - margin * 2;
    MoveWindow(rootEdit, margin, px(42), width - px(100), px(28), TRUE);
    MoveWindow(GetDlgItem(h, 101), r.right - margin - px(88), px(42), px(88), px(28), TRUE);
    MoveWindow(listbox, margin, px(86), width, r.bottom - px(278), TRUE);
    int x = margin;
    for (auto pair : std::vector<std::pair<int,int>>{{102,138},{104,100},{103,145},{105,118},{106,135}}) {
        auto item = GetDlgItem(h, pair.first);
        if (!item) continue;
        MoveWindow(item, x, r.bottom - px(178), px(pair.second), px(32), TRUE);
        x += px(pair.second + 12);
    }
    MoveWindow(GetDlgItem(h, 107), margin, r.bottom - px(136), px(145), px(32), TRUE);
    MoveWindow(GetDlgItem(h, 108), margin + px(157), r.bottom - px(136), px(155), px(32), TRUE);
    MoveWindow(purgeCheck, margin, r.bottom - px(90), width, px(26), TRUE);
    if (incomingLabel) MoveWindow(incomingLabel, margin, r.bottom - px(48), width, px(26), TRUE);
}
static LRESULT CALLBACK procedure(HWND h, UINT message, WPARAM wp, LPARAM lp) {
    if (message == WM_SIZE) { layoutManager(h); return 0; }
    if (message == WM_GETMINMAXINFO) {
        auto info = (MINMAXINFO*)lp;
        info->ptMinTrackSize = {MulDiv(850, uiDpi, 96), MulDiv(450, uiDpi, 96)};
        return 0;
    }
    if (message == WM_COMMAND) {
        if ((HWND)lp == rootEdit && HIWORD(wp) == EN_CHANGE && !updatingTarget) {
            listedTarget.clear(); listedIds.clear(); listedSources.clear();
            SendMessageW(listbox, LB_RESETCONTENT, 0, 0);
            EnableWindow(GetDlgItem(window, 103), FALSE);
            EnableWindow(GetDlgItem(window, 105), FALSE);
            EnableWindow(GetDlgItem(window, 107), FALSE);
            EnableWindow(GetDlgItem(window, 108), FALSE);
            SendMessageW(purgeCheck, BM_SETCHECK, BST_UNCHECKED, 0);
        }
        if ((HWND)lp == listbox && HIWORD(wp) == LBN_SELCHANGE) {
            SendMessageW(purgeCheck, BM_SETCHECK, BST_UNCHECKED, 0);
            int selection = (int)SendMessageW(listbox, LB_GETCURSEL, 0, 0);
            bool damaged = selection >= 0 && (size_t)selection < listedSources.size() && !listedSources[selection].empty();
            EnableWindow(GetDlgItem(window, 103), !damaged && selection >= 0);
            EnableWindow(GetDlgItem(window, 107), damaged);
            EnableWindow(GetDlgItem(window, 108), damaged);
        }
        switch (LOWORD(wp)) {
        case 101: {
            BROWSEINFOW b = {};
            b.hwndOwner = h;
            b.lpszTitle = L"选择中望3D 2027安装文件夹";
            b.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            auto pidl = SHBrowseForFolderW(&b);
            if (pidl) {
                wchar_t p[MAX_PATH];
                if (SHGetPathFromIDListW(pidl, p))
                    SetWindowTextW(rootEdit, p);
                CoTaskMemFree(pidl);
                runOperation([] {});
            }
            break;
        }
        case 102:
            try { actionGui(L"/install"); } catch (const std::exception& e) { error(e.what()); }
            break;
        case 103:
        case 105:
            try {
                useTarget();
                require(!listedTarget.empty() && listedTarget == target, "安装位置已变化，请先刷新列表。");
                int selection = (int)SendMessageW(listbox, LB_GETCURSEL, 0, 0);
                require(selection >= 0 && (size_t)selection < listedIds.size(), "请先选择插件。");
                if (LOWORD(wp) == 105 && !listedSources[selection].empty()) {
                    actionGui(L"/cancel-maintenance=" + wide(listedSources[selection]));
                    break;
                }
                require(!listedIds[selection].empty(),
                        "请先选择正常登记的插件。");
                actionGui((LOWORD(wp) == 105 ? L"/cancel=" : L"/uninstall=") + wide(listedIds[selection]));
            } catch (const std::exception& e) { error(e.what()); }
            break;
        case 107:
        case 108:
            try {
                useTarget();
                require(!listedTarget.empty() && listedTarget == target, "安装位置已变化，请先刷新列表。");
                int selection = (int)SendMessageW(listbox, LB_GETCURSEL, 0, 0);
                require(selection >= 0 && (size_t)selection < listedSources.size() && !listedSources[selection].empty(),
                        "请先选择标注为登记损坏的记录。");
                bool repair = LOWORD(wp) == 107;
                auto message = repair ? L"将先备份损坏登记，再从完整且匹配的安装版本恢复。程序和个人数据保留；无法确认版本时停止。中望3D运行中会等待重启。是否继续？" :
                    L"将先备份并隔离所选损坏登记，使其退出工具箱。程序和个人数据保留，之后可用原安装包重装。中望3D运行中会等待重启。是否继续？";
                if (MessageBoxW(h, message, L"处理损坏登记", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) == IDYES)
                    actionGui((repair ? L"/repair=" : L"/isolate=") + wide(listedSources[selection]));
            } catch (const std::exception& e) { error(e.what()); }
            break;
        case 106:
            try {
                useTarget(); auto file = userData(target, "org.zwtools.plugin-hub") / L"startup.log";
                require(fs::exists(file), "还没有启动日志，请先启动一次中望3D。");
                ShellExecuteW(window, L"open", L"notepad.exe", quote(file).c_str(), nullptr, SW_SHOWNORMAL);
            } catch (const std::exception& e) { error(e.what()); }
            break;
        case 104:
            runOperation([] {});
            break;
        }
        return 0;
    }
    if (message == WM_CLOSE) {
        DestroyWindow(h);
        return 0;
    }
    if (message == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, message, wp, lp);
}
static int gui(const std::string& uiProbe) {
    // System-aware scaling keeps standard Windows controls readable at 125-250%.
    SetProcessDPIAware();
    HDC screen = GetDC(nullptr); uiDpi = GetDeviceCaps(screen, LOGPIXELSX); ReleaseDC(nullptr, screen);
    uiFont = CreateFontW(-MulDiv(10, uiDpi, 72), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                         DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                         CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    WNDCLASSW cls = {};
    cls.hInstance = GetModuleHandleW(nullptr);
    cls.lpfnWndProc = procedure;
    cls.lpszClassName = L"ZwPluginHubManagerV1";
    cls.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    cls.hIcon = LoadIconW(cls.hInstance, MAKEINTRESOURCEW(101));
    cls.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassW(&cls);
    window = CreateWindowW(cls.lpszClassName, L"扩展工具管理器", WS_OVERLAPPEDWINDOW,
                           CW_USEDEFAULT, CW_USEDEFAULT, MulDiv(850, uiDpi, 96), MulDiv(490, uiDpi, 96), nullptr, nullptr, cls.hInstance,
                           nullptr);
    auto smallIcon = LoadImageW(cls.hInstance, MAKEINTRESOURCEW(101), IMAGE_ICON,
                               GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), LR_SHARED);
    require(cls.hIcon && smallIcon, "Application icon resource is missing");
    SendMessageW(window, WM_SETICON, ICON_BIG, (LPARAM)cls.hIcon);
    SendMessageW(window, WM_SETICON, ICON_SMALL, (LPARAM)smallIcon);
    auto control = [&](const wchar_t* kind, const wchar_t* title, DWORD style, int x, int y, int w,
                       int height, int id) {
        auto c = CreateWindowW(kind, title, WS_CHILD | WS_VISIBLE | WS_TABSTOP | style,
                               MulDiv(x, uiDpi, 96), MulDiv(y, uiDpi, 96), MulDiv(w, uiDpi, 96), MulDiv(height, uiDpi, 96), window,
                               (HMENU)(INT_PTR)id, cls.hInstance, nullptr);
        SendMessageW(c, WM_SETFONT, (WPARAM)uiFont, TRUE);
        return c;
    };
#ifndef HUB_MANAGER
    try {
        auto incoming = parse(resource(2000));
        incomingLabel = control(L"STATIC", (L"待安装：" + wide(incoming.at("name")) + L"  " +
                                wide(incoming.at("version"))).c_str(), 0, 20, 382, 790, 24, 0);
    } catch (const std::exception& e) { error(e.what()); }
#endif
    control(L"BUTTON", L"取消待处理", BS_PUSHBUTTON, 450, 308, 118, 32, 105);
    control(L"BUTTON", L"查看启动日志", BS_PUSHBUTTON, 580, 308, 128, 32, 106);
    control(L"BUTTON", L"修复损坏登记", BS_PUSHBUTTON, 20, 346, 145, 32, 107);
    control(L"BUTTON", L"隔离损坏登记", BS_PUSHBUTTON, 177, 346, 155, 32, 108);
    EnableWindow(GetDlgItem(window, 107), FALSE);
    EnableWindow(GetDlgItem(window, 108), FALSE);
    control(L"STATIC", L"中望3D 2027安装位置", 0, 20, 16, 220, 20, 0);
    rootEdit = control(L"EDIT", target.c_str(), WS_BORDER | ES_AUTOHSCROLL, 20, 42, 540, 28, 0);
    control(L"BUTTON", L"选择…", BS_PUSHBUTTON, 570, 42, 88, 28, 101);
    listbox = control(L"LISTBOX", L"", WS_BORDER | LBS_NOTIFY | WS_VSCROLL, 20, 86, 638, 205, 0);
#ifndef HUB_MANAGER
    control(L"BUTTON", L"安装这个插件", BS_PUSHBUTTON, 20, 308, 138, 32, 102);
#endif
    control(L"BUTTON", L"刷新列表", BS_PUSHBUTTON, 174, 308, 100, 32, 104);
    control(L"BUTTON", L"卸载所选插件", BS_PUSHBUTTON, 290, 308, 138, 32, 103);
    purgeCheck =
        control(L"BUTTON", L"同时清理当前账户的设置和日志", BS_AUTOCHECKBOX, 20, 350, 470, 24, 0);
    layoutManager(window);
    if (!target.empty())
        try {
            validateTarget(target);
            refresh();
        } catch (const std::exception& e) {
            error(e.what());
        }
    if (!uiProbe.empty()) {
        require(refreshSucceeded && listedTarget == target, "Manager list did not finish refreshing");
        require(window && rootEdit && listbox && purgeCheck, "UI creation failed");
        require(SendMessageW(window, WM_GETICON, ICON_BIG, 0) && SendMessageW(window, WM_GETICON, ICON_SMALL, 0),
                "Manager window must have both application icon sizes");
        require(SendMessageW(purgeCheck, BM_GETCHECK, 0, 0) == BST_UNCHECKED,
                "Ordinary uninstall must preserve data by default");
        Bytes observed;
        int rows = (int)SendMessageW(listbox, LB_GETCOUNT, 0, 0);
        for (int i = 0; i < rows; ++i) {
            int size = (int)SendMessageW(listbox, LB_GETTEXTLEN, i, 0);
            std::wstring text(size + 1, L'\0');
            SendMessageW(listbox, LB_GETTEXT, i, (LPARAM)text.data()); text.resize(size);
            observed += utf8(text) + "\n";
            if (!listedSources[i].empty()) {
                SendMessageW(listbox, LB_SETCURSEL, i, 0);
                SendMessageW(window, WM_COMMAND, MAKEWPARAM(0, LBN_SELCHANGE), (LPARAM)listbox);
                require(IsWindowEnabled(GetDlgItem(window, 107)) && IsWindowEnabled(GetDlgItem(window, 108)) &&
                            !IsWindowEnabled(GetDlgItem(window, 103)), "Damaged row must expose maintenance controls only");
            }
        }
        SetWindowTextW(rootEdit, L"changed target");
        require(listedIds.empty() && listedTarget.empty() &&
                    listedSources.empty() && !IsWindowEnabled(GetDlgItem(window, 103)) &&
                    !IsWindowEnabled(GetDlgItem(window, 107)) && !IsWindowEnabled(GetDlgItem(window, 108)),
                "Changing target must invalidate selection and disable uninstall");
        atomicWrite(wide(uiProbe), "PASS manager controls, target selection invalidation, default data preservation\n" + observed);
        DestroyWindow(window);
        DeleteObject(uiFont);
        return 0;
    }
    ShowWindow(window, SW_SHOWNORMAL);
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        if (!IsDialogMessageW(window, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    DeleteObject(uiFont);
    return 0;
}
int WINAPI wWinMain(HINSTANCE, HINSTANCE, LPWSTR, int) {
    XmlCom apartment;
    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::string op, id, log, uiProbe;
    bool purge = false;
    DWORD startup = 0;
    for (int i = 1; i < argc; ++i) {
        std::wstring a = argv[i];
        if (a == L"/quiet")
            quiet = true;
        else if (a == L"/install")
            op = "install";
        else if (a == L"/apply")
            op = "apply";
        else if (a == L"/framework-wait")
            op = "framework";
        else if (a.rfind(L"/repair=", 0) == 0) { op = "repair"; id = utf8(a.substr(8)); }
        else if (a.rfind(L"/isolate=", 0) == 0) { op = "isolate"; id = utf8(a.substr(9)); }
        else if (a.rfind(L"/cancel-maintenance=", 0) == 0) { op = "cancel-maintenance"; id = utf8(a.substr(20)); }
        else if (a.rfind(L"/cancel=", 0) == 0) {
            op = "cancel"; id = utf8(a.substr(8));
        }
        else if (a == L"/purge")
            purge = true;
        else if (a.rfind(L"/target=", 0) == 0)
            target = fs::absolute(a.substr(8)).lexically_normal();
        else if (a.rfind(L"/initiator=", 0) == 0)
            initiatingUser = utf8(a.substr(11));
        else if (a.rfind(L"/uninstall=", 0) == 0) {
            op = "remove";
            id = utf8(a.substr(11));
        } else if (a.rfind(L"/startup-parent=", 0) == 0)
            startup = std::stoul(a.substr(16));
        else if (a.rfind(L"/log=", 0) == 0)
            log = utf8(a.substr(5));
        else if (a.rfind(L"/ui-probe=", 0) == 0)
            uiProbe = utf8(a.substr(10));
    }
    LocalFree(argv);
    startupContext = startup;
    int code = 0;
    // /install, /cancel, /uninstall and maintenance commands must finish their
    // transaction and release Lock before showing an elevated result dialog.
    deferStatus = !op.empty();
    try {
        if (target.empty()) {
            auto found = detect();
            if (found.size() == 1)
                target = found.front();
        }
        if (op.empty()) {
            code = gui(uiProbe);
        } else {
            validateTarget(target);
            if (op == "framework")
                while (!hostProcesses(target).empty()) Sleep(500);
            Lock lock;
            Transaction(target, startupContext).restore();
            if (op == "install")
                installEmbedded();
            else if (op == "remove")
                removeId(id, purge);
            else if (op == "cancel") cancelId(id);
            else if (op == "repair" || op == "isolate") maintainRecord(id, op);
            else if (op == "cancel-maintenance") cancelMaintenance(id);
            else {
                if (op == "framework") applyFramework();
                else if (fs::exists(store(target) / L"framework-next" / L"metadata.ini")) {
                    startFrameworkWorker();
                    throw std::runtime_error("工具箱升级等待宿主关闭，请关闭中望3D后重新启动。");
                }
                applyPending(startup);
                if (cleanupSkipped) result("插件已卸载；当前账户与清理请求的原账户不同，原账户数据已保留。");
            }
        }
    } catch (const std::exception& e) {
        error(e.what());
        code = 1;
    }
    if (!log.empty())
        try {
            atomicWrite(wide(log), status.empty() ? (code ? "FAIL\n" : "PASS\n") : status + "\n");
        } catch (...) {
            code = 2;
        }
    deferStatus = false;
    if (!op.empty()) showStatus();  // All Lock instances above have gone out of scope.
    return code;
}
