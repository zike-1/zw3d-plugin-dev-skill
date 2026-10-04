#pragma once
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <shellapi.h>
#include <sddl.h>
#include <stdexcept>
#include <string>
#include <tlhelp32.h>
#include <vector>

namespace hub {
namespace fs = std::filesystem;
using Bytes = std::string;
using Fields = std::map<std::string, std::string>;
struct Handle {
    HANDLE value;
    explicit Handle(HANDLE v) : value(v) {}
    ~Handle() {
        if (value && value != INVALID_HANDLE_VALUE)
            CloseHandle(value);
    }
    Handle(const Handle&) = delete;
};
inline void require(bool ok, const std::string& why) {
    if (!ok)
        throw std::runtime_error(why);
}
inline std::wstring wide(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), (int)s.size(), nullptr, 0);
    require(n > 0 || s.empty(), "Invalid UTF-8");
    std::wstring r(n, 0);
    if (n)
        MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), (int)s.size(), r.data(), n);
    return r;
}
inline std::string utf8(const std::wstring& s) {
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    std::string r(n, 0);
    if (n)
        WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), r.data(), n, nullptr, nullptr);
    return r;
}
inline std::string lower(std::string s) {
    for (auto& c : s)
        if (c >= 'A' && c <= 'Z')
            c += 32;
    return s;
}
inline fs::path modulePath(HMODULE module = nullptr) {
    std::wstring s(32768, 0);
    DWORD n = GetModuleFileNameW(module, s.data(), (DWORD)s.size());
    require(n && n < s.size(), "Module path unavailable");
    s.resize(n);
    return s;
}
inline Bytes read(const fs::path& p) {
    Handle h(
        CreateFileW(p.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr));
    require(h.value != INVALID_HANDLE_VALUE, "Cannot read: " + utf8(p.wstring()));
    LARGE_INTEGER size;
    require(GetFileSizeEx(h.value, &size) && size.QuadPart >= 0 &&
                size.QuadPart <= 64 * 1024 * 1024,
            "File too large");
    Bytes b((size_t)size.QuadPart, 0);
    DWORD got = 0;
    require(b.empty() ||
                (ReadFile(h.value, b.data(), (DWORD)b.size(), &got, nullptr) && got == b.size()),
            "Read failed");
    return b;
}
inline void atomicWrite(const fs::path& p, const Bytes& b) {
    fs::create_directories(p.parent_path());
    static LONG serial = 0;
    fs::path temp = p;
    temp += L".tmp." + std::to_wstring(GetCurrentProcessId()) + L"." +
            std::to_wstring(InterlockedIncrement(&serial));
    bool ok = false;
    {
        Handle h(CreateFileW(temp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                             FILE_ATTRIBUTE_NORMAL, nullptr));
        require(h.value != INVALID_HANDLE_VALUE, "Cannot stage file");
        DWORD wrote = 0;
        ok = (b.empty() || (WriteFile(h.value, b.data(), (DWORD)b.size(), &wrote, nullptr) &&
                            wrote == b.size())) &&
             FlushFileBuffers(h.value);
    }
    if (ok)
        ok = MoveFileExW(temp.c_str(), p.c_str(),
                         MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != FALSE;
    if (!ok) {
        DeleteFileW(temp.c_str());
        throw std::runtime_error("File busy or write denied: " + utf8(p.wstring()));
    }
}
inline std::string sha(const Bytes& b) {
    BCRYPT_ALG_HANDLE alg = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    DWORD n = 0, got = 0;
    require(BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0,
            "SHA256 provider unavailable");
    bool ok = BCryptGetProperty(alg, BCRYPT_OBJECT_LENGTH, (PUCHAR)&n, sizeof(n), &got, 0) >= 0;
    std::vector<unsigned char> mem(n), out(32);
    if (ok)
        ok = BCryptCreateHash(alg, &hash, mem.data(), n, nullptr, 0, 0) >= 0;
    if (ok)
        ok = BCryptHashData(hash, (PUCHAR)b.data(), (ULONG)b.size(), 0) >= 0 &&
             BCryptFinishHash(hash, out.data(), 32, 0) >= 0;
    if (hash)
        BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(alg, 0);
    require(ok, "SHA256 failed");
    std::string s;
    const char* hex = "0123456789abcdef";
    for (auto c : out) {
        s += hex[c >> 4];
        s += hex[c & 15];
    }
    return s;
}
inline std::vector<std::string> split(const std::string& s, char delimiter) {
    std::vector<std::string> out;
    size_t p = 0;
    while (p <= s.size()) {
        size_t e = s.find(delimiter, p);
        if (e == std::string::npos)
            e = s.size();
        out.push_back(s.substr(p, e - p));
        p = e + 1;
    }
    return out;
}
inline Fields parse(const Bytes& b) {
    Fields f;
    require(b.find('\0') == std::string::npos, "NUL in descriptor");
    wide(b);
    for (auto line : split(b, '\n')) {
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        if (line.empty())
            continue;
        size_t p = line.find('=');
        require(p != std::string::npos && p > 0, "Bad descriptor line");
        require(f.emplace(line.substr(0, p), line.substr(p + 1)).second,
                "Duplicate descriptor key");
    }
    return f;
}
inline Bytes encode(const Fields& f) {
    Bytes b;
    for (auto& [k, v] : f) {
        require(k.find_first_of("=\r\n") == std::string::npos &&
                    v.find_first_of("\r\n") == std::string::npos,
                "Invalid descriptor value");
        b += k + "=" + v + "\n";
    }
    return b;
}
inline bool symbol(const std::string& s) {
    return !s.empty() && s.size() < 80 &&
           std::all_of(
               s.begin(), s.end(),
               [](char c) {
                   return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                          (c >= '0' && c <= '9') || c == '_';
               });
}
inline bool safeId(const std::string& s) {
    return s.size() > 3 && s.size() < 100 && s.find('.') != std::string::npos && s.front() != '.' &&
           s.back() != '.' && s.find("..") == std::string::npos &&
           std::all_of(
               s.begin(), s.end(),
               [](char c) {
                   return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '-';
               });
}
inline bool safeRelative(const std::string& s) {
    if (s.empty() || s.size() > 180 || s.front() == '/' || s.find('\0') != std::string::npos ||
        s.find_first_of("\\:*?\"<>|\r\n") != std::string::npos)
        return false;
    for (auto& part : split(s, '/')) {
        if (part.empty() || part == "." || part == ".." || part.back() == '.' || part.back() == ' ')
            return false;
        std::string base = lower(split(part, '.')[0]);
        if (base == "con" || base == "nul" || base == "prn" || base == "aux" || base == "clock$" ||
            (base.size() == 4 && (base.substr(0, 3) == "com" || base.substr(0, 3) == "lpt") &&
             base[3] >= '0' && base[3] <= '9'))
            return false;
    }
    return true;
}
inline bool noLinks(const fs::path& p) {
    fs::path part;
    for (auto& c : p) {
        part /= c;
        DWORD a = GetFileAttributesW(part.c_str());
        if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_REPARSE_POINT))
            return false;
    }
    return true;
}
inline fs::path within(const fs::path& root, const std::string& relative) {
    require(safeRelative(relative), "Unsafe path: " + relative);
    fs::path p = root / fs::path(wide(relative));
    require(noLinks(p), "Linked paths unsupported");
    return p;
}
inline fs::path store(const fs::path& target) {
    return target / L"apilibs" / L"ZwPluginHub";
}
inline fs::path userData(const fs::path& target, const std::string& id) {
    wchar_t p[32768];
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", p, 32768);
    require(n && n < 32768, "LOCALAPPDATA unavailable");
    return fs::path(p) / L"ZwPluginHub" /
           wide(sha(lower(utf8(target.lexically_normal().wstring()))).substr(0, 16)) / wide(id);
}
inline std::string currentUserSid() {
    Handle token(nullptr);
    require(OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.value), "User token unavailable");
    DWORD size = 0;
    GetTokenInformation(token.value, TokenUser, nullptr, 0, &size);
    std::vector<BYTE> bytes(size);
    require(size && GetTokenInformation(token.value, TokenUser, bytes.data(), size, &size), "User identity unavailable");
    wchar_t* sid = nullptr;
    require(ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(bytes.data())->User.Sid, &sid), "User SID unavailable");
    auto result = utf8(sid); LocalFree(sid); return result;
}
inline void validDescriptor(const Fields& f) {
    auto get = [&](const std::string& key) -> std::string {
        auto i = f.find(key);
        require(i != f.end(), "Missing descriptor: " + key);
        return i->second;
    };
    require(get("schema") == "1" && safeId(get("id")) && symbol(get("prefix")),
            "Unsupported identity");
    auto v = get("version");
    auto parts = split(v, '.');
    require(parts.size() == 3 && std::all_of(parts.begin(), parts.end(),
                                             [](const std::string& p) {
                                                 return !p.empty() && p.size() <= 6 &&
                                                        (p == "0" || p.front() != '0') &&
                                                        std::all_of(p.begin(), p.end(), [](char c) {
                                                            return c >= '0' && c <= '9';
                                                        });
                                             }),
            "Version must be numeric major.minor.patch");
    require((get("type") == "dll" || get("type") == "exe") && safeRelative(get("entry")),
            "Invalid entry");
    require(!get("name").empty() && get("name").size() < 256, "Invalid display name");
    int count = std::stoi(get("commands"));
    require(count >= 1 && count <= 32, "Command count exceeds v1 limit");
    std::set<std::string> ids;
    for (int i = 0; i < count; ++i) {
        auto base = "cmd." + std::to_string(i) + ".";
        auto id = get(base + "id");
        require(symbol(id) && id.rfind(get("prefix"), 0) == 0 && ids.insert(id).second,
                "Invalid command ID");
        require(!get(base + "label").empty(), "Missing command label");
        auto env = split(get(base + "environments"), ',');
        require(env.size() == 4 && std::set<std::string>(env.begin(), env.end()) ==
                                       std::set<std::string>{"top", "part", "assembly", "drawing"},
                "v1 requires all four environments");
    }
}
struct RegistryIssue { std::string file, error; };
inline std::vector<Fields> installed(const fs::path& target,
                                      std::vector<RegistryIssue>* issues = nullptr) {
    std::vector<Fields> out;
    auto dir = store(target) / L"state";
    if (!fs::exists(dir))
        return out;
    require(noLinks(dir), "Linked state directory");
    for (auto& entry : fs::directory_iterator(dir)) {
        if (entry.path().extension() != L".ini")
            continue;
        try {
            require(noLinks(entry.path()), "Linked record");
            auto f = parse(read(entry.path()));
            validDescriptor(f);
            require(entry.path().stem() == wide(f.at("id")), "Record identity mismatch");
            out.push_back(f);
        } catch (const std::exception& e) {
            if (!issues) throw;
            issues->push_back({utf8(entry.path().filename().wstring()), e.what()});
        }
    }
    return out;
}
inline std::vector<fs::path> hostProcesses(const fs::path& target) {
    std::vector<fs::path> out;
    Handle snap(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    PROCESSENTRY32W e = {sizeof(e)};
    for (BOOL ok = Process32FirstW(snap.value, &e); ok; ok = Process32NextW(snap.value, &e)) {
        if (_wcsicmp(e.szExeFile, L"zw3d.exe"))
            continue;
        Handle p(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, e.th32ProcessID));
        wchar_t path[32768];
        DWORD n = 32768;
        if (p.value && QueryFullProcessImageNameW(p.value, 0, path, &n) &&
            _wcsicmp(fs::path(std::wstring(path, n)).parent_path().c_str(), target.c_str()) == 0)
            out.push_back(fs::path(std::wstring(path, n)));
    }
    return out;
}
inline bool startupSafe(const fs::path& target, DWORD pid) {
    if (hostProcesses(target).size() != 1)
        return false;
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    wchar_t p[32768];
    DWORD n = 32768;
    if (!process.value || !QueryFullProcessImageNameW(process.value, 0, p, &n) ||
        _wcsicmp(fs::path(std::wstring(p, n)).c_str(), (target / L"zw3d.exe").c_str()))
        return false;
    Handle snap(CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid));
    if (snap.value == INVALID_HANDLE_VALUE)
        return false;
    MODULEENTRY32W m = {sizeof(m)};
    auto base = lower(utf8((store(target) / L"plugins").wstring()));
    for (BOOL ok = Module32FirstW(snap.value, &m); ok; ok = Module32NextW(snap.value, &m))
        if (lower(utf8(m.szExePath)).rfind(base + "\\", 0) == 0)
            return false;
    return true;
}
inline void validateTarget(const fs::path& target) {
    require(target.is_absolute() && target.wstring().size() > 3 && target.wstring()[1] == L':' &&
                noLinks(target),
            "Choose a local unlinked installation folder");
    require(fs::exists(target / L"zw3d.exe") && fs::exists(target / L"ZW3D.dll"),
            "Not a ZW3D installation");
    DWORD dummy = 0, n = GetFileVersionInfoSizeW((target / L"zw3d.exe").c_str(), &dummy);
    require(n > 0, "Host version unavailable");
    std::vector<char> b(n);
    VS_FIXEDFILEINFO* info = nullptr;
    UINT size = 0;
    require(GetFileVersionInfoW((target / L"zw3d.exe").c_str(), 0, n, b.data()) &&
                VerQueryValueW(b.data(), L"\\", (void**)&info, &size) && info &&
                HIWORD(info->dwProductVersionMS) == 32,
            "Only verified ZW3D 2027 is supported");
}
inline std::string escape(std::string s) {
    std::string out;
    for (char c : s)
        switch (c) {
        case '&':
            out += "&amp;";
            break;
        case '<':
            out += "&lt;";
            break;
        case '>':
            out += "&gt;";
            break;
        case '"':
            out += "&quot;";
            break;
        case '\'':
            out += "&apos;";
            break;
        default:
            out += c;
        }
    return out;
}
inline std::string action(const std::string& id) {
    return "ID_ZpHub_" + id;
}
inline std::wstring quote(const fs::path& p) {
    return L"\"" + p.wstring() + L"\"";
}
inline bool elevated() {
    BOOL yes = FALSE;
    SID_IDENTIFIER_AUTHORITY nt = SECURITY_NT_AUTHORITY;
    PSID administrators = nullptr;
    if (AllocateAndInitializeSid(&nt, 2, SECURITY_BUILTIN_DOMAIN_RID, DOMAIN_ALIAS_RID_ADMINS, 0, 0,
                                 0, 0, 0, 0, &administrators)) {
        CheckTokenMembership(nullptr, administrators, &yes);
        FreeSid(administrators);
    }
    return yes != FALSE;
}
} // namespace hub
