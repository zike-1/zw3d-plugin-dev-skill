#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <string>

inline void FixtureEvent(const char* text) {
    wchar_t path[32768]{};
    const DWORD count = GetEnvironmentVariableW(L"ZW_HUB_FIXTURE_EVENTS", path, 32768);
    if (!count || count >= 32768)
        return;
    HANDLE file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
        return;
    const std::string line = std::string(text) + "\n";
    DWORD written = 0;
    WriteFile(file, line.data(), static_cast<DWORD>(line.size()), &written, nullptr);
    FlushFileBuffers(file);
    CloseHandle(file);
}
