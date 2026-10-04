#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <stdexcept>
#include <functional>
namespace {
namespace fs = std::filesystem;
fs::path folder;
HWND editor;
constexpr int EditorId = 1000, SaveId = 1001;
bool dirty = false, reading = false;
std::string utf8(const std::wstring& s) {
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    if (!s.empty() && !n) throw std::runtime_error("文本编码错误");
    std::string out(n, '\0'); WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), (int)s.size(), out.data(), n, nullptr, nullptr); return out;
}
std::wstring wide(const std::string& s) {
    if (s.find('\0') != std::string::npos) throw std::runtime_error("便签包含无效字符，原文件已保留");
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), (int)s.size(), nullptr, 0);
    if (!s.empty() && !n) throw std::runtime_error("便签不是有效UTF-8文本");
    std::wstring out(n, L'\0'); MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), (int)s.size(), out.data(), n); return out;
}
std::string read(const fs::path& file) {
    if (!fs::exists(file)) return {};
    if (fs::file_size(file) > 1024 * 1024) throw std::runtime_error("便签超过1MB，请保留原文件并检查");
    std::ifstream in(file, std::ios::binary); if (!in) throw std::runtime_error("无法读取便签；原文件未修改");
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}
void save(const std::wstring& text) {
    auto bytes = std::string("ZWN1\n") + utf8(text);
    if (bytes.size() > 1024 * 1024) throw std::runtime_error("便签超过1MB，保存已停止");
    fs::create_directories(folder);
    auto tmp = folder / (L"settings." + std::to_wstring(GetCurrentProcessId()) + L".tmp");
    std::ofstream out(tmp, std::ios::binary); out.write(bytes.data(), (std::streamsize)bytes.size()); out.flush();
    if (!out) throw std::runtime_error("写入失败；原便签保持不变");
    out.close();
    if (!MoveFileExW(tmp.c_str(), (folder / L"settings.txt").c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("保存未完成；原便签保持不变");
}
std::wstring load() {
    auto file = folder / L"settings.txt";
    if (!fs::exists(file)) {
        auto legacy = folder / L"note.txt"; if (!fs::exists(legacy)) return {};
        auto text = wide(read(legacy)); save(text); return text; // Preserve the original backup.
    }
    auto bytes = read(file);
    if (bytes.rfind("ZWN1\n", 0) != 0) throw std::runtime_error("未知便签格式；原文件已保留，请勿覆盖");
    return wide(bytes.substr(5));
}
void error(const std::exception& e) { MessageBoxW(nullptr, wide(e.what()).c_str(), L"示例便签", MB_OK | MB_ICONERROR); }
bool saveEditor() {
    try {
        int n = GetWindowTextLengthW(editor); std::wstring text(n + 1, L'\0');
        GetWindowTextW(editor, text.data(), n + 1); text.resize(n); save(text); dirty = false; return true;
    } catch (const std::exception& e) { error(e); return false; }
}
void layout(HWND w) {
    RECT r; GetClientRect(w, &r); MoveWindow(editor, 16, 16, r.right - 32, r.bottom - 78, TRUE);
    MoveWindow(GetDlgItem(w, SaveId), 16, r.bottom - 48, 120, 32, TRUE);
}
LRESULT CALLBACK procedure(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    if (m == WM_SIZE) { if (editor) layout(w); return 0; }
    if (m == WM_COMMAND) {
        if (LOWORD(wp) == SaveId && HIWORD(wp) == BN_CLICKED &&
            (HWND)lp == GetDlgItem(w, SaveId) && saveEditor())
            MessageBoxW(w, L"便签已保存。普通卸载会保留它。", L"示例便签", MB_OK);
        if (LOWORD(wp) == IDCANCEL && lp == 0) SendMessageW(w, WM_CLOSE, 0, 0);
        if ((HWND)lp == editor && HIWORD(wp) == EN_CHANGE && !reading) dirty = true;
        return 0;
    }
    if (m == WM_CLOSE) {
        if (dirty) {
            int choice = MessageBoxW(w, L"保存本次修改吗？", L"示例便签", MB_YESNOCANCEL | MB_ICONQUESTION);
            if (choice == IDCANCEL || (choice == IDYES && !saveEditor())) return 0;
        }
        DestroyWindow(w); return 0;
    }
    if (m == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(w, m, wp, lp);
}
HWND createEditor(HINSTANCE instance, const std::wstring& initial) {
    WNDCLASSW c{}; c.hInstance = instance; c.lpfnWndProc = procedure; c.lpszClassName = L"ArtNotesWindow";
    c.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(101));
    c.hCursor = LoadCursorW(nullptr, IDC_ARROW); c.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassW(&c);
    HWND w = CreateWindowW(c.lpszClassName, L"示例便签 — 设置自动保留", WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 560, 410, nullptr, nullptr, instance, nullptr);
    auto small = LoadImageW(instance, MAKEINTRESOURCEW(101), IMAGE_ICON, GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), LR_SHARED);
    if (!w || !c.hIcon || !small) throw std::runtime_error("便签窗口或应用图标无法创建");
    SendMessageW(w, WM_SETICON, ICON_BIG, (LPARAM)c.hIcon); SendMessageW(w, WM_SETICON, ICON_SMALL, (LPARAM)small);
    editor = CreateWindowW(L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_BORDER | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN | WS_VSCROLL, 0, 0, 0, 0, w, (HMENU)EditorId, instance, nullptr);
    SendMessageW(editor, EM_SETLIMITTEXT, 200000, 0);
    HWND button = CreateWindowW(L"BUTTON", L"保存便签", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 0, 0, 120, 32, w, (HMENU)SaveId, instance, nullptr);
    SendMessageW(editor, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
    SendMessageW(button, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
    reading = true; SetWindowTextW(editor, initial.c_str()); reading = false; dirty = false;
    layout(w); return w;
}
void processMessage(HWND w, MSG& msg) {
    if (msg.message == WM_KEYDOWN && msg.wParam == VK_ESCAPE &&
        (msg.hwnd == w || IsChild(w, msg.hwnd))) { SendMessageW(w, WM_CLOSE, 0, 0); return; }
    if (!IsDialogMessageW(w, &msg)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
}
}
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    try {
        int count; auto argv = CommandLineToArgvW(GetCommandLineW(), &count); if (!argv) return 2;
        std::wstring arg = count == 2 ? argv[1] : L""; LocalFree(argv);
        if (count == 2 && arg.rfind(L"/probe=", 0) == 0) {
            fs::path log(arg.substr(7)); if (!log.is_absolute()) return 2;
            std::ofstream out(log, std::ios::binary | std::ios::app); out << "exe|ArtNotes|ok\n"; return out ? 0 : 3;
        }
        wchar_t data[32768]; auto n = GetEnvironmentVariableW(L"ZW_PLUGIN_DATA_DIR", data, 32768);
        if (!n || n >= 32768 || !fs::path(data).is_absolute()) throw std::runtime_error("请从中望3D的小插件工具箱启动便签");
        folder = data;
        if (count == 2 && arg.rfind(L"/self-test=", 0) == 0) {
            if (fs::exists(folder / L"settings.txt") || fs::exists(folder / L"note.txt")) return 4;
            fs::create_directories(folder); std::ofstream legacy(folder / L"note.txt", std::ios::binary);
            legacy << utf8(L"中文旧便签"); legacy.close();
            if (load() != L"中文旧便签" || !fs::exists(folder / L"note.txt")) return 5;
            save(L"更新后仍保留\r\n第二行"); if (load() != L"更新后仍保留\r\n第二行") return 6;
            std::ofstream log(fs::path(arg.substr(11)), std::ios::binary); log << "PASS migration, UTF-8 and save/read\n"; return log ? 0 : 7;
        }
        if (count != 1) return 2;
        struct Instance {
            HANDLE handle;
            ~Instance() { if (handle) { ReleaseMutex(handle); CloseHandle(handle); } }
        } instanceLock{CreateMutexW(nullptr, TRUE,
                (L"Local\\ArtNotes." + std::to_wstring(std::hash<std::wstring>{}(folder.lexically_normal().wstring()))).c_str())};
        DWORD mutexResult = GetLastError();
        if (!instanceLock.handle) throw std::runtime_error("便签无法取得编辑锁，请稍后再试");
        if (mutexResult == ERROR_ALREADY_EXISTS) {
            MessageBoxW(nullptr, L"这个账户的便签已经打开，请使用已有窗口。", L"示例便签", MB_OK);
            return 0;
        }
        auto initial = load();
        HWND w = createEditor(instance, initial); ShowWindow(w, SW_SHOWNORMAL);
        MSG msg; while (GetMessageW(&msg, nullptr, 0, 0) > 0) processMessage(w, msg);
        return 0;
    } catch (const std::exception& e) { error(e); return 1; }
}
