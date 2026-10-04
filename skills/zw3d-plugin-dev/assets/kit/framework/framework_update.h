#pragma once

// Included by setup.cpp after the installer's target, resource and Lock helpers.
// Protocol 1 is backwards compatible: never replace a compatible newer release.
static void verifyFramework(const Fields& f, const Bytes& hubBytes, const Bytes& managerBytes) {
    require(f.at("protocol") == "1" && f.at("hub") == sha(hubBytes) &&
                f.at("manager") == sha(managerBytes), "Framework metadata/integrity mismatch");
    auto v = split(f.at("version"), '.');
    require(v.size() == 3, "Invalid framework version");
    for (const auto& n : v)
        require(!n.empty() && n.size() <= 6 &&
                    std::all_of(n.begin(), n.end(), [](char c) { return c >= '0' && c <= '9'; }),
                "Invalid framework version");
}
static std::vector<int> frameworkVersion(const Fields& f) {
    std::vector<int> v;
    for (const auto& n : split(f.at("version"), '.')) v.push_back(std::stoi(n));
    return v;
}
static bool frameworkNeedsUpdate() {
    auto meta = parse(resource(902));
    verifyFramework(meta, resource(900), resource(901));
    auto hub = target / L"apilibs" / L"ZwPluginHub.dll";
    auto manager = store(target) / L"HubManager.exe";
    auto record = store(target) / L"framework.ini";
    if (!fs::exists(hub) && !fs::exists(manager)) return true;
    require(fs::exists(hub) && fs::exists(manager), "Incomplete framework installation");
    if (fs::exists(record)) {
        auto current = parse(read(record));
        verifyFramework(current, read(hub), read(manager));
        if (frameworkVersion(current) == frameworkVersion(meta))
            require(current.at("hub") == meta.at("hub") && current.at("manager") == meta.at("manager"),
                    "同一框架版本内容不同，请使用统一发行文件或增加框架版本号。");
        return frameworkVersion(current) < frameworkVersion(meta);
    }
    // Only the two verified local candidates can enter the versioned protocol.
    require(sha(read(hub)) == "e8992c0c4ee8e85712d9440b9bec323156cd312c2efd37e0614e6c6aeb61b515" &&
                (sha(read(manager)) == "1e5844519c209b1098ae7dddf688b2d8fc2239c6a561553ddf9d7334d756986f" ||
                 sha(read(manager)) == "e8d49eaddfb89077b074ca6c57cd158d5c97d374b68bb242530e9be9d7df107f"),
            "Unknown legacy framework; restore its verified release before migration");
    return true;
}
static void bootstrap(Transaction& tx) {
    if (!frameworkNeedsUpdate()) return;
    require(hostProcesses(target).empty(), "框架升级等待中望3D关闭。");
    tx.put("apilibs/ZwPluginHub.dll", resource(900));
    tx.put(relStore("HubManager.exe"), resource(901));
    tx.put(relStore("framework.ini"), resource(902));
}
static void stageFramework(Transaction& tx) {
    auto base = relStore("framework-next/");
    auto meta = parse(resource(902));
    verifyFramework(meta, resource(900), resource(901));
    auto pending = store(target) / L"framework-next";
    if (fs::exists(pending / L"metadata.ini")) {
        auto previous = parse(read(pending / L"metadata.ini"));
        verifyFramework(previous, read(pending / L"hub.bin"), read(pending / L"manager.bin"));
        if (frameworkVersion(previous) >= frameworkVersion(meta)) {
            if (frameworkVersion(previous) == frameworkVersion(meta))
                require(previous.at("hub") == meta.at("hub") && previous.at("manager") == meta.at("manager"),
                        "同一待更新框架版本内容不同。");
            return; // A compatible higher queued release already satisfies this installer.
        }
    }
    tx.put(base + "hub.bin", resource(900));
    tx.put(base + "manager.bin", resource(901));
    auto updater = read(modulePath());
    auto name = "Updater-" + sha(updater).substr(0, 16) + ".exe";
    meta["updater"] = name;
    meta["updater.sha256"] = sha(updater);
    tx.put(base + "metadata.ini", encode(meta));
    auto existing = within(target, base + name);
    if (!fs::exists(existing)) tx.put(base + name, updater);
    else require(read(existing) == updater, "Pending updater was modified");
}
static void applyFramework() {
    auto base = store(target) / L"framework-next";
    if (!fs::exists(base / L"metadata.ini")) return;
    require(hostProcesses(target).empty(), "工具箱升级尚未生效，请关闭中望3D后重新启动。");
    auto meta = parse(read(base / L"metadata.ini"));
    auto hub = read(base / L"hub.bin"), manager = read(base / L"manager.bin");
    verifyFramework(meta, hub, manager);
    bool replace = true;
    auto record = store(target) / L"framework.ini";
    if (fs::exists(record)) {
        auto current = parse(read(record));
        verifyFramework(current, read(target / L"apilibs" / L"ZwPluginHub.dll"),
                        read(store(target) / L"HubManager.exe"));
        if (frameworkVersion(current) >= frameworkVersion(meta)) {
            if (frameworkVersion(current) == frameworkVersion(meta))
                require(current.at("hub") == meta.at("hub") && current.at("manager") == meta.at("manager"),
                        "同一待更新框架版本内容不同。");
            replace = false;
        }
    } else {
        require(!fs::exists(target / L"apilibs" / L"ZwPluginHub.dll") &&
                    !fs::exists(store(target) / L"HubManager.exe"),
                "Framework changed after staging; automatic replacement stopped");
    }
    Transaction tx(target);
    if (replace) {
        tx.put("apilibs/ZwPluginHub.dll", hub);
        tx.put(relStore("HubManager.exe"), manager);
        tx.put(relStore("framework.ini"), encode(meta));
    }
    tx.erase(relStore("framework-next/metadata.ini"));
    tx.erase(relStore("framework-next/hub.bin"));
    tx.erase(relStore("framework-next/manager.bin"));
    tx.commit();
    // Updater.exe is retained until a subsequent release; it cannot delete itself.
}
static void startFrameworkWorker() {
    auto meta = parse(read(store(target) / L"framework-next" / L"metadata.ini"));
    require(safeRelative(meta.at("updater")) && meta.at("updater").rfind("Updater-", 0) == 0,
            "Invalid framework updater identity");
    auto file = within(store(target) / L"framework-next", meta.at("updater"));
    require(sha(read(file)) == meta.at("updater.sha256"), "Framework updater was modified");
    std::wstring command = quote(file) + L" /quiet /framework-wait /target=" + quote(target) +
                           L" /log=" + quote(store(target) / L"framework-update.log");
    STARTUPINFOW si = {sizeof(si)};
    si.dwFlags = STARTF_USESHOWWINDOW; si.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION pi = {};
    require(CreateProcessW(file.c_str(), command.data(), nullptr, nullptr, FALSE,
                          CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi),
            "升级已暂存，但后台程序未能启动。关闭中望3D后再次运行安装包。");
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
}
