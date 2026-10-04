#include <windows.h>
#include <iostream>
#include <vector>
#include <string>
static int choice = IDCANCEL;
static std::vector<std::wstring> messages;
static int fixtureMessage(HWND, LPCWSTR text, LPCWSTR, UINT type) {
    messages.push_back(text);
    return (type & MB_YESNOCANCEL) == MB_YESNOCANCEL ? choice : IDOK;
}
#define MessageBoxW fixtureMessage
#define wWinMain NotesProductionMain
#undef NOMINMAX
#include "../../examples/art-notes/src/NotesEditor.cpp"
#undef wWinMain
#undef MessageBoxW
static void check(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
    std::cout << "PASS " << why << "\n";
}
static void escape(HWND w) {
    MSG msg{}; msg.hwnd = editor; msg.message = WM_KEYDOWN; msg.wParam = VK_ESCAPE;
    processMessage(w, msg);
}
static void typeText(const wchar_t* text) {
    SendMessageW(editor, EM_SETSEL, 0, -1);
    for (auto p = text; *p; ++p) SendMessageW(editor, WM_CHAR, *p, 1);
}
int wmain(int count, wchar_t** args) {
    try {
        if (count != 2) return 2;
        folder = fs::absolute(args[1]);
        if (fs::exists(folder)) return 3;
        save(L"original"); auto original = read(folder / L"settings.txt");
        HWND w = createEditor(GetModuleHandleW(nullptr), load());
        check(SendMessageW(w, WM_GETICON, ICON_SMALL, 0) && SendMessageW(w, WM_GETICON, ICON_BIG, 0), "window has small and large application icons");
        typeText(L"draft"); check(dirty, "edit marks draft dirty");
        auto before = messages.size(); choice = IDCANCEL; escape(w);
        check(messages.size() == before + 1 && messages.back() == L"保存本次修改吗？", "Esc asks about unsaved changes instead of triggering Save");
        check(IsWindow(w) && dirty && read(folder / L"settings.txt") == original, "Cancel keeps draft open and disk unchanged");
        SendMessageW(w, WM_COMMAND, MAKEWPARAM(SaveId, BN_CLICKED), 0);
        check(read(folder / L"settings.txt") == original, "unrelated command with Save ID cannot save");
        SendMessageW(w, WM_COMMAND, MAKEWPARAM(SaveId, BN_CLICKED), (LPARAM)GetDlgItem(w, SaveId));
        check(!dirty && load() == L"draft", "explicit Save button persists draft");
        auto saved = read(folder / L"settings.txt"); before = messages.size(); escape(w);
        check(!IsWindow(w) && messages.size() == before && read(folder / L"settings.txt") == saved, "Esc on clean editor closes without writing or prompting");
        w = createEditor(GetModuleHandleW(nullptr), load()); typeText(L"discard me"); choice = IDNO; escape(w);
        check(!IsWindow(w) && read(folder / L"settings.txt") == saved, "Esc then No discards draft and preserves saved text");
        w = createEditor(GetModuleHandleW(nullptr), load()); typeText(L"save on request"); choice = IDYES; escape(w);
        check(!IsWindow(w) && load() == L"save on request", "Esc only saves after explicit Yes");
        w = createEditor(GetModuleHandleW(nullptr), load()); typeText(L"cancel command draft");
        saved = read(folder / L"settings.txt"); choice = IDCANCEL;
        SendMessageW(w, WM_COMMAND, MAKEWPARAM(IDCANCEL, 0), 0);
        check(IsWindow(w) && dirty && read(folder / L"settings.txt") == saved, "Windows IDCANCEL command cannot alias Save");
        choice = IDNO; SendMessageW(w, WM_CLOSE, 0, 0);
        std::cout << "PASS production editor keyboard and icon checks; prompt choices simulated\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
}
