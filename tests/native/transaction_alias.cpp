#include "transaction.h"
#include <iostream>
int wmain(int count, wchar_t** args) {
    if (count != 2) return 2;
    fs::path root = fs::absolute(args[1]);
    fs::create_directories(root);
    const std::string upper = "apilibs/icons/~ZpHub_DemoOPEN.png";
    const std::string mixed = "apilibs/icons/~ZpHub_DemoOpen.png";
    auto file = within(root, mixed);
    atomicWrite(file, "original");
    Transaction tx(root);
    tx.put(upper, "first"); tx.put(mixed, "updated");
    require(tx.changes.size() == 1, "Windows aliases must have one change");
    tx.commit(); require(read(file) == "updated", "Alias commit differs");
    // Legacy journal: two aliases with the same verified original are recoverable.
    auto journal = store(root) / L"transaction";
    atomicWrite(journal / L"0.bin", "original");
    atomicWrite(journal / L"1.bin", "original");
    atomicWrite(journal / L"journal.txt", upper + "|old|0.bin|" + sha("original") + "\n" +
                mixed + "|old|1.bin|" + sha("original") + "\n");
    Transaction(root).restore(); require(read(file) == "original" && !fs::exists(journal), "Legacy alias recovery failed");
    Transaction failure(root);
    failure.put(mixed, "changed");
    const std::string lockedRel = "apilibs/icons/~ZpHub_ZwPluginHubManage.png";
    auto lockedPath = within(root, lockedRel); atomicWrite(lockedPath, "locked original");
    failure.put(lockedRel, "locked change");
    Handle locked(CreateFileW(lockedPath.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
    require(locked.value != INVALID_HANDLE_VALUE, "Cannot hold regression lock");
    bool rejected = false;
    try { failure.commit(); } catch (const std::exception&) { rejected = true; }
    require(rejected && read(file) == "original" && !fs::exists(journal), "Occupied write failed to restore original state");
    std::cout << "PASS alias uniqueness, legacy recovery and occupied-write rollback\n";
    return 0;
}
