#pragma once
#include "common.h"
using namespace hub;

static bool transactionPath(const std::string& rel) {
    return safeRelative(rel) &&
           (rel == "apilibs/ZwPluginHub.dll" || rel.rfind("apilibs/ZwPluginHub/", 0) == 0 ||
            rel.rfind("apilibs/Settings/Default/", 0) == 0 ||
            rel.rfind("apilibs/icons/~ZpHub_", 0) == 0);
}
struct Transaction {
    struct PathLess {
        bool operator()(const std::string& a, const std::string& b) const {
            auto wa = wide(a), wb = wide(b);
            return CompareStringOrdinal(wa.c_str(), (int)wa.size(), wb.c_str(),
                                        (int)wb.size(), TRUE) == CSTR_LESS_THAN;
        }
    };
    fs::path root, dir;
    DWORD startupPid;
    std::map<std::string, std::optional<Bytes>, PathLess> changes;
    explicit Transaction(const fs::path& t, DWORD pid = 0)
        : root(t), dir(store(t) / L"transaction"), startupPid(pid) {}
    void put(const std::string& rel, const Bytes& b) {
        require(transactionPath(rel), "Transaction path rejected");
        within(root, rel);
        changes[rel] = b;
    }
    void erase(const std::string& rel) {
        require(transactionPath(rel), "Transaction path rejected");
        within(root, rel);
        changes[rel] = std::nullopt;
    }
    void restore(bool internalRollback = false) {
        auto journal = dir / L"journal.txt";
        if (!fs::exists(journal)) {
            if (fs::exists(dir)) {
                require(noLinks(dir), "Recovery path is linked");
                for (auto& e : fs::recursive_directory_iterator(dir))
                    require(noLinks(e.path()), "Linked recovery content");
                fs::remove_all(dir);
            }
            return;
        }
        require(noLinks(dir), "Recovery path is linked");
        std::vector<std::pair<fs::path, std::optional<Bytes>>> recovery;
        std::map<std::string, std::optional<Bytes>, PathLess> seen;
        bool deferredOnly = true;
        for (auto line : split(read(journal), '\n')) {
            if (!line.empty() && line.back() == '\r')
                line.pop_back();
            if (line.empty())
                continue;
            auto f = split(line, '|');
            require(f.size() == 4 && transactionPath(f[0]),
                    "Bad recovery record");
            auto p = within(root, f[0]);
            std::optional<Bytes> original;
            deferredOnly =
                deferredOnly && (f[0].rfind("apilibs/ZwPluginHub/pending/", 0) == 0 ||
                                 f[0].rfind("apilibs/ZwPluginHub/maintenance/", 0) == 0 ||
                                 (f[1] == "new" && (f[0] == "apilibs/ZwPluginHub.dll" ||
                                                    f[0] == "apilibs/ZwPluginHub/HubManager.exe")));
            if (f[1] == "old") {
                auto backup = within(dir, f[2]);
                auto b = read(backup);
                require(sha(b) == f[3], "Recovery backup corrupted");
                original = b;
            } else {
                require(f[1] == "new" && f[2] == "-" && f[3] == "-", "Bad recovery state");
            }
            auto prior = seen.emplace(f[0], original);
            // Older journals may contain case aliases of the same Windows file.
            // Only identical verified originals can safely collapse to one restore.
            require(prior.second || prior.first->second == original,
                    "Conflicting recovery aliases");
            if (prior.second) recovery.push_back({p, original});
        }
        require(internalRollback || deferredOnly || hostProcesses(root).empty() ||
                    startupSafe(root, startupPid),
                "Close the host before recovering an unfinished installation");
        // Validate the entire recovery set before restoring its first file.
        for (auto& [p, b] : recovery) {
            if (b) {
                if (!fs::exists(p) || read(p) != *b)
                    atomicWrite(p, *b);
            } else if (fs::exists(p))
                require(DeleteFileW(p.c_str()), "Cannot roll back new file");
        }
        // Only the fixed, verified transaction folder is removed.
        for (auto& e : fs::recursive_directory_iterator(dir))
            require(noLinks(e.path()), "Linked recovery content");
        fs::remove_all(dir);
    }
    void commit() {
        require(!fs::exists(dir / L"journal.txt"), "An unfinished transaction needs recovery");
        require(noLinks(dir), "Linked transaction directory");
        fs::create_directories(dir);
        Bytes journal;
        size_t i = 0;
        for (auto& [rel, b] : changes) {
            auto p = within(root, rel);
            if (fs::exists(p)) {
                auto original = read(p);
                auto name = std::to_string(i) + ".bin";
                atomicWrite(dir / wide(name), original);
                journal += rel + "|old|" + name + "|" + sha(original) + "\n";
            } else
                journal += rel + "|new|-|-\n";
            ++i;
        }
        atomicWrite(dir / L"journal.txt", journal);
        try {
            for (auto& [rel, b] : changes) {
                auto p = within(root, rel);
                if (b)
                    atomicWrite(p, *b);
                else if (fs::exists(p))
                    require(DeleteFileW(p.c_str()), "File occupied: " + rel);
            }
            require(MoveFileExW((dir / L"journal.txt").c_str(), (dir / L"committed.txt").c_str(),
                                MOVEFILE_WRITE_THROUGH),
                    "Commit marker failed");
        } catch (...) {
            restore(true);
            throw;
        }
        // Rename the journal after all changes are durable, so startup cannot undo a committed
        // operation.
        fs::remove_all(dir);
    }
};
