#pragma once
#include <msxml6.h>
#include <oleauto.h>

/* MSXML 6 is supplied by Windows. Parse XML before touching a shared resource.
   Only nodes with this plugin's stable identifiers are replaced or removed. */
template <class T> struct XmlPtr {
    T* p = NULL;
    ~XmlPtr() {
        if (p)
            p->Release();
    }
    T** out() {
        return &p;
    }
    T* operator->() const {
        return p;
    }
};
struct XmlCom {
    HRESULT hr = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    ~XmlCom() {
        if (SUCCEEDED(hr))
            CoUninitialize();
    }
    bool ok() const {
        return SUCCEEDED(hr) || hr == RPC_E_CHANGED_MODE;
    }
};
struct XmlBstr {
    BSTR p;
    explicit XmlBstr(const std::wstring& s) : p(SysAllocStringLen(s.data(), (UINT)s.size())) {}
    ~XmlBstr() {
        SysFreeString(p);
    }
};
static bool XmlDocument(const std::wstring& xml, XmlPtr<IXMLDOMDocument2>& d) {
    const CLSID cls = {
        0x88d96a05, 0xf192, 0x11d4, {0xa6, 0x5f, 0x00, 0x40, 0x96, 0x32, 0x51, 0xe5}};
    if (FAILED(CoCreateInstance(cls, NULL, CLSCTX_INPROC_SERVER, __uuidof(IXMLDOMDocument2),
                                (void**)d.out())))
        return false;
    d->put_async(VARIANT_FALSE);
    d->put_validateOnParse(VARIANT_FALSE);
    d->put_resolveExternals(VARIANT_FALSE);
    d->put_preserveWhiteSpace(VARIANT_TRUE);
    VARIANT forbid;
    VariantInit(&forbid);
    forbid.vt = VT_BOOL;
    forbid.boolVal = VARIANT_TRUE;
    XmlBstr property(L"ProhibitDTD");
    if (FAILED(d->setProperty(property.p, forbid)))
        return false;
    XmlBstr text(xml);
    VARIANT_BOOL loaded = VARIANT_FALSE;
    return SUCCEEDED(d->loadXML(text.p, &loaded)) && loaded == VARIANT_TRUE;
}
static bool XmlSelect(IXMLDOMNode* d, const wchar_t* path, XmlPtr<IXMLDOMNodeList>& list) {
    XmlBstr query(path);
    return SUCCEEDED(d->selectNodes(query.p, list.out())) && list.p;
}
static bool XmlRemove(IXMLDOMNode* d, const wchar_t* path) {
    XmlPtr<IXMLDOMNodeList> list;
    if (!XmlSelect(d, path, list))
        return false;
    long n = 0;
    if (FAILED(list->get_length(&n)))
        return false;
    for (long i = n; i-- > 0;) {
        XmlPtr<IXMLDOMNode> node, parent, removed;
        if (FAILED(list->get_item(i, node.out())) || !node.p ||
            FAILED(node->get_parentNode(parent.out())) || !parent.p ||
            FAILED(parent->removeChild(node.p, removed.out())))
            return false;
    }
    return true;
}
static bool XmlAppendSelected(IXMLDOMDocument2* dest, IXMLDOMDocument2* source,
                              const wchar_t* parentPath, const wchar_t* childPath) {
    XmlPtr<IXMLDOMNode> parent;
    XmlBstr query(parentPath);
    if (FAILED(dest->selectSingleNode(query.p, parent.out())) || !parent.p)
        return false;
    XmlPtr<IXMLDOMNodeList> list;
    if (!XmlSelect(source, childPath, list))
        return false;
    long n = 0;
    if (FAILED(list->get_length(&n)))
        return false;
    for (long i = 0; i < n; ++i) {
        XmlPtr<IXMLDOMNode> node, clone, appended;
        if (FAILED(list->get_item(i, node.out())) || !node.p ||
            FAILED(node->cloneNode(VARIANT_TRUE, clone.out())) || !clone.p ||
            FAILED(parent->appendChild(clone.p, appended.out())))
            return false;
    }
    return true;
}
static bool MergeOwnedXml(const std::wstring& existing, const std::wstring& payload,
                          bool removeOnly, std::wstring& output) {
    XmlCom com;
    if (!com.ok())
        return false;
    XmlPtr<IXMLDOMDocument2> dst, src;
    if (!XmlDocument(payload, src) || !XmlDocument(existing.empty() ? payload : existing, dst))
        return false;
    XmlPtr<IXMLDOMElement> sr, dr;
    if (FAILED(src->get_documentElement(sr.out())) || FAILED(dst->get_documentElement(dr.out())) ||
        !sr.p || !dr.p)
        return false;
    BSTR sn = NULL, dn = NULL;
    sr->get_nodeName(&sn);
    dr->get_nodeName(&dn);
    std::wstring name = sn ? sn : L"";
    bool same = sn && dn && wcscmp(sn, dn) == 0;
    SysFreeString(sn);
    SysFreeString(dn);
    if (!same)
        return false;
    const wchar_t* owned = NULL;
    const wchar_t* parent = NULL;
    if (name == L"RibbonPages") {
        parent = L"/RibbonPages";
        owned = L"/RibbonPages/RibbonPage[@name='ZwPluginHubPage']";
    } else if (name == L"Actions") {
        parent = L"/Actions";
        owned = L"/Actions/Action[starts-with(@name,'ID_ZpHub_')]";
    } else if (name == L"Strategy") {
        // Do not merge an environment's strategy into another environment.
        XmlBstr attr(L"environment");
        VARIANT a, b;
        VariantInit(&a);
        VariantInit(&b);
        HRESULT ar = sr->getAttribute(attr.p, &a), br = dr->getAttribute(attr.p, &b);
        bool match = SUCCEEDED(ar) && SUCCEEDED(br) && a.vt == VT_BSTR && b.vt == VT_BSTR &&
                     wcscmp(a.bstrVal, b.bstrVal) == 0;
        VariantClear(&a);
        VariantClear(&b);
        if (!match)
            return false;
        parent = L"/Strategy/DefaultCustomizations";
        owned = L"/Strategy/DefaultCustomizations/Insert[@name='ZwPluginHubPage']";
        XmlPtr<IXMLDOMNode> pc;
        XmlBstr pq(parent);
        if (FAILED(dst->selectSingleNode(pq.p, pc.out())))
            return false;
        if (!pc.p && !removeOnly) {
            XmlPtr<IXMLDOMElement> created;
            XmlPtr<IXMLDOMNode> appended;
            XmlBstr tag(L"DefaultCustomizations");
            if (FAILED(dst->createElement(tag.p, created.out())) || !created.p ||
                FAILED(dr->appendChild(created.p, appended.out())))
                return false;
        }
    } else
        return false;
    if (!XmlRemove(dst.p, owned))
        return false;
    if (!removeOnly && !XmlAppendSelected(dst.p, src.p, parent, owned))
        return false;
    BSTR text = NULL;
    if (FAILED(dst->get_xml(&text)) || !text)
        return false;
    output.assign(text, SysStringLen(text));
    SysFreeString(text);
    return true;
}
