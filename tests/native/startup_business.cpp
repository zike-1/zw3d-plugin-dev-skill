#include "startup_event.h"

extern "C" __declspec(dllexport) int ArtFixtureInit() {
    FixtureEvent("BUSINESS_INIT");
    return 0;
}
extern "C" __declspec(dllexport) int ArtFixtureExit() {
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH)
        FixtureEvent("BUSINESS_DLL_MAPPED");
    return TRUE;
}
