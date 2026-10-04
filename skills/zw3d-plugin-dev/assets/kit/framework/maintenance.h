#pragma once
// Included after the normal installer operations: repair uses the same lock and journal.
static std::string maintenanceRel(const std::string& source) {
    return relStore("maintenance/" + sha(source) + ".ini");
}
static bool stateSource(const std::string& source) {
    auto parts = split(source, '/');
    require(safeRelative(source), "不安全的登记路径，操作已停止。");
    bool state = parts.size() == 2 && parts[0] == "state" &&
                 fs::path(wide(parts[1])).extension() == L".ini";
    bool pending = parts.size() == 3 && parts[0] == "pending" && parts[2] == "operation.ini";
    require(state || pending, "只能处理工具箱中的活动登记或待处理登记。");
    return state;
}
static Bytes damagedRecord(const std::string& source) {
    bool state = stateSource(source);
    auto path = within(store(target), source);
    auto bytes = read(path);
    bool valid = false;
    try {
        auto f = parse(bytes); validDescriptor(f);
        if (state) valid = path.stem() == wide(f.at("id"));
        else valid = path.parent_path().filename() == wide(f.at("id")) &&
                     f.count("operation") && (f.at("operation") == "install" ||
                     f.at("operation") == "remove" || f.at("operation") == "purge");
    } catch (const std::exception&) {}
    require(!valid, "登记目前有效，无需修复或隔离；请刷新列表。");
    return bytes;
}
static Fields repairCandidate(const std::string& source, const Bytes& damaged) {
    require(stateSource(source), "待处理请求的原意无法可靠重建，请隔离后重新发起安装或卸载。");
    auto id = utf8(fs::path(wide(source)).stem().wstring());
    require(safeId(id), "登记文件名无法确认插件身份，请选择隔离损坏登记。");
    std::string expected;
    try { auto f = parse(damaged); if (f.count("version")) expected = f.at("version"); }
    catch (const std::exception&) {}
    auto versions = within(store(target), "plugins/" + id);
    require(fs::is_directory(versions), "没有可验证的安装文件，请隔离后用原安装包重装。");
    std::vector<Fields> candidates;
    size_t versionFolders = 0;
    for (auto& e : fs::directory_iterator(versions)) {
        ++versionFolders;
        try {
            require(e.is_directory() && noLinks(e.path()), "Linked or invalid version");
            auto f = parse(read(within(e.path(), "descriptor.ini"))); validDescriptor(f);
            require(f.at("id") == id && e.path().filename() == wide(f.at("version")), "Version identity differs");
            if (!expected.empty() && f.at("version") != expected) continue;
            auto items = fileIndex(read(within(e.path(), "files.txt")));
            std::set<std::string> names;
            for (auto& item : items) {
                auto bytes = read(within(e.path(), item.path));
                require(bytes.size() == item.size && sha(bytes) == item.hash, "Installed payload changed");
                names.insert(item.path);
            }
            require(names.count(f.at("entry")), "Entry not indexed");
            for (int i = 0; i < std::stoi(f.at("commands")); ++i) {
                auto key = "cmd." + std::to_string(i) + ".icon";
                require(!f.count(key) || names.count(f.at(key)), "Icon not indexed");
            }
            compatible(f);
            candidates.push_back(f);
        } catch (const std::exception&) { /* An unverified version is never a recovery source. */ }
    }
    require(!expected.empty() || versionFolders == 1,
            "存在多个历史版本，原登记无法确认版本；请隔离后用需要的版本重装。");
    require(candidates.size() == 1, candidates.empty() ?
            "找不到完整且匹配的安装版本，请隔离后用原安装包重装。" :
            "有多个完整版本，无法确认原活动版本；请隔离后用需要的版本重装。");
    auto f = candidates.front();
    require(lower(f.at("prefix")).rfind("hub", 0) != 0 &&
                lower(f.at("prefix")).rfind("zwpluginhub", 0) != 0, "Reserved framework prefix");
    std::vector<RegistryIssue> issues;
    int externalCount = f.at("type") == "exe" ? std::stoi(f.at("commands")) : 0;
    for (const auto& other : registrations(true, &issues)) {
        if (other.at("id") == f.at("id")) {
            require(other.at("prefix") == f.at("prefix") && other.at("type") == f.at("type") &&
                        other.at("entry") == f.at("entry"), "待处理请求与恢复版本的身份不一致，请先取消请求。");
            require(frameworkVersion(other) >= frameworkVersion(f), "恢复版本高于待处理版本，请先取消请求。");
            continue;
        }
        if (other.at("type") == "exe") externalCount += std::stoi(other.at("commands"));
        require(lower(other.at("prefix")) != lower(f.at("prefix")), "恢复的前缀与其他插件冲突。");
        for (int i = 0; i < std::stoi(f.at("commands")); ++i)
            for (int j = 0; j < std::stoi(other.at("commands")); ++j)
                require(lower(f.at("cmd." + std::to_string(i) + ".id")) !=
                        lower(other.at("cmd." + std::to_string(j) + ".id")), "恢复的命令与其他插件冲突。");
    }
    require(externalCount <= 128, "恢复后EXE命令数超过工具箱容量。");
    return f;
}
static void maintainNow(const std::string& source, const std::string& mode,
                        const std::string& expectedHash, const std::string& request = {}) {
    require(mode == "repair" || mode == "isolate", "Invalid maintenance action");
    bool state = stateSource(source);
    auto damaged = damagedRecord(source);
    require(sha(damaged) == expectedHash, "登记自请求后已变化，未修改任何文件；请取消请求并刷新。");
    std::optional<Fields> restored;
    if (mode == "repair") restored = repairCandidate(source, damaged);
    if (mode == "isolate" && state) {
        auto id = utf8(fs::path(wide(source)).stem().wstring());
        require(!fs::exists(within(store(target), "pending/" + id + "/operation.ini")),
                "该插件还有待处理请求，请先取消该请求，再隔离损坏登记。");
    }
    FILETIME time; GetSystemTimeAsFileTime(&time);
    auto serial = std::to_string((static_cast<unsigned long long>(time.dwHighDateTime) << 32) | time.dwLowDateTime)
                  + "-" + std::to_string(GetCurrentProcessId());
    auto backup = relStore("recovery/" + serial + "/");
    require(!fs::exists(within(target, backup + "receipt.ini")), "Recovery backup already exists");
    Transaction tx(target, startupContext);
    if (state) {
        tx.put(backup + "original/" + source, damaged);
        if (restored) tx.put(relStore(source), encode(*restored));
        else tx.erase(relStore(source));
    } else {
        // Quarantine the entire request, preserving even payload files with damaged metadata.
        auto folder = within(store(target), "pending/" + split(source, '/')[1]);
        size_t count = 0, size = 0;
        for (auto& e : fs::recursive_directory_iterator(folder)) {
            require(noLinks(e.path()), "待处理目录含链接，操作已停止。");
            if (e.is_directory()) continue;
            require(e.is_regular_file(), "Unknown pending content");
            auto relative = utf8(e.path().lexically_relative(store(target)).generic_wstring());
            auto bytes = read(e.path()); size += bytes.size();
            require(++count <= 258 && size <= 256 * 1024 * 1024, "待处理备份过大，操作已停止。");
            tx.put(backup + "original/" + relative, bytes); tx.erase(relStore(relative));
        }
    }
    Fields receipt{{"source", source}, {"mode", mode}, {"original.sha256", expectedHash}};
    if (restored) { receipt["id"] = restored->at("id"); receipt["version"] = restored->at("version"); }
    tx.put(backup + "receipt.ini", encode(receipt));
    std::vector<RegistryIssue> issues;
    auto active = installed(target, &issues);
    if (restored) active.push_back(*restored);
    menus(tx, active);
    if (!request.empty()) tx.erase(request);
    tx.commit();
    result((mode == "repair" ? "登记已恢复，个人数据保持原样。" :
            "损坏登记已隔离，程序和个人数据保留；需要时用原安装包重装。") +
           std::string("备份位置：") + utf8(within(target, backup + "receipt.ini").parent_path().wstring()));
}
static void maintainRecord(const std::string& source, const std::string& mode) {
    require(mode == "repair" || mode == "isolate", "Invalid maintenance action");
    auto damaged = damagedRecord(source);
    if (mode == "repair") repairCandidate(source, damaged); // Fail before queuing an impossible repair.
    if (mode == "isolate" && stateSource(source))
        require(!fs::exists(within(store(target), "pending/" + utf8(fs::path(wide(source)).stem().wstring()) + "/operation.ini")),
                "该插件还有待处理请求，请先取消该请求，再隔离损坏登记。");
    if (hostProcesses(target).empty()) maintainNow(source, mode, sha(damaged));
    else {
        Transaction tx(target);
        tx.put(maintenanceRel(source), encode({{"source", source}, {"mode", mode}, {"hash", sha(damaged)}}));
        tx.commit();
        result("已登记，等待重启后处理损坏登记。程序和个人数据暂未修改，可在管理器取消。");
    }
}
static void cancelMaintenance(const std::string& source) {
    stateSource(source);
    Transaction tx(target); tx.erase(maintenanceRel(source)); tx.commit();
    result("待修复／隔离请求已取消，原登记、程序和个人数据保持不变。");
}
static void applyMaintenance() {
    auto dir = within(store(target), "maintenance");
    if (!fs::exists(dir)) return;
    std::vector<fs::path> entries;
    for (auto& e : fs::directory_iterator(dir)) {
        require(e.is_regular_file() && noLinks(e.path()) && e.path().extension() == L".ini", "Invalid maintenance request");
        entries.push_back(e.path());
    }
    for (auto& p : entries) {
        auto f = parse(read(p));
        require(f.size() == 3 && f.count("source") && f.count("mode") && f.count("hash"), "Invalid maintenance metadata");
        require(p == within(target, maintenanceRel(f.at("source"))), "Maintenance identity differs");
        maintainNow(f.at("source"), f.at("mode"), f.at("hash"), maintenanceRel(f.at("source")));
    }
}
