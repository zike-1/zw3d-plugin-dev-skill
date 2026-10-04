#pragma once

// Fixture data only. This does not claim to reproduce the real SDK ABI.
struct szwPluginData {
    char path[2048];
};

extern "C" int ZwPluginDataInit(const char* path, szwPluginData* data);
extern "C" int ZwPluginLoad(szwPluginData data);
