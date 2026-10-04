#include "startup_event.h"
#include <iostream>

int wmain(int count, wchar_t** arguments) {
    if (count != 2)
        return 2;
    HMODULE module = LoadLibraryW(arguments[1]);
    if (!module)
        return 3;
    const auto init = reinterpret_cast<int (*)()>(GetProcAddress(module, "ZwPluginHubInit"));
    const auto exit = reinterpret_cast<int (*)()>(GetProcAddress(module, "ZwPluginHubExit"));
    const auto drain = reinterpret_cast<void (*)()>(GetProcAddress(module, "FixtureDrainQueue"));
    const auto force = reinterpret_cast<void (*)()>(GetProcAddress(module, "FixtureForceBusinessStart"));
    const auto loads = reinterpret_cast<int (*)()>(GetProcAddress(module, "FixtureBusinessLoads"));
    const auto queued = reinterpret_cast<int (*)()>(GetProcAddress(module, "FixtureStartQueued"));
    const auto alive = reinterpret_cast<int (*)()>(GetProcAddress(module, "FixtureManagerAlive"));
    const auto wait = reinterpret_cast<void (*)()>(GetProcAddress(module, "FixtureFinishManager"));
    const auto manager = reinterpret_cast<int (*)()>(GetProcAddress(module, "FixtureManagerRegistered"));
    const auto dataDirectory = reinterpret_cast<int (*)(const char*, wchar_t*, int)>(GetProcAddress(module, "ZwPluginHubDataDirectory"));
    if (!init || !exit || !drain || !force || !loads || !queued || !alive || !wait || !manager || !dataDirectory)
        return 4;
    const int result = init();
    const int queueCount = queued(), managerAvailable = manager(), helperAlive = alive();
    drain();
    force();  // A queued SDK probe must not bypass the production gate.
    const int beforeHelperExit = loads();
    wait();
    force();  // Completing a timed-out helper does not unblock this session.
    const int finalLoads = loads();
    wchar_t dataPath[32768]{};
    const int dataResult = dataDirectory("org.zwtools.art-fixture", dataPath, 32768);
    std::cout << "{\"init\":" << result << ",\"queued\":" << queueCount
              << ",\"managerRegistered\":" << managerAvailable << ",\"helperAlive\":" << helperAlive
              << ",\"beforeHelperExit\":" << beforeHelperExit << ",\"finalLoads\":" << finalLoads
              << ",\"dataDirectoryResult\":" << dataResult << "}\n";
    exit();
    FreeLibrary(module);
    return 0;
}
