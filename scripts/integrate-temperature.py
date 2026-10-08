#!/usr/bin/env python3
"""Connect autocore's Airoha temperature helper to the existing LuCI status page."""
import json
import pathlib
import re
import sys

CI_DIR = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = pathlib.Path("package/emortal/autocore/Makefile")
RPC = pathlib.Path("feeds/luci/modules/luci-base/root/usr/share/rpcd/ucode/luci")
PAGE = pathlib.Path("feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/include/10_system.js")
ACL = pathlib.Path("feeds/luci/modules/luci-mod-status/root/usr/share/rpcd/acl.d/luci-mod-status-index.json")
ZH_HANS = pathlib.Path("feeds/luci/modules/luci-base/po/zh_Hans/base.po")
MARKER = "// PonWrt-CI temperature integration."


def replace_once(text, old, new, description):
    if text.count(old) != 1:
        raise ValueError(f"Upstream {description} changed; review temperature integration")
    return text.replace(old, new, 1)


def integrate(source):
    # Prepare all changes first; incompatible upstream files must fail the build.
    makefile = (source / MAKEFILE).read_text()
    rule = re.search(r"\$\(filter ([^,]+), \$\(TARGETID\)\)", makefile)
    if not rule or "./files/tempinfo $(1)/sbin/" not in makefile:
        raise ValueError("Upstream autocore tempinfo installation rule changed")
    if "airoha%" not in rule[1].split():
        makefile = makefile[:rule.start(1)] + rule[1] + " airoha%" + makefile[rule.end(1):]
        makefile = re.sub(r"^(PKG_RELEASE:=\S+)$", r"\1.1", makefile, count=1, flags=re.MULTILINE)

    rpc = (source / RPC).read_text()
    if MARKER not in rpc:
        if re.search(r"\bgetTempInfo\s*:", rpc):
            raise ValueError("Upstream now defines getTempInfo; review its response format")
        fragment = (CI_DIR / "config/temperature-rpc.uc").read_text()
        rpc = replace_once(rpc, "const methods = {\n", "const methods = {\n" + fragment, "LuCI RPC methods")

    page = (source / PAGE).read_text()
    if MARKER not in page:
        if "getTempInfo" in page:
            raise ValueError("Upstream now calls getTempInfo; review its page integration")
        declaration = """
// PonWrt-CI temperature integration.
var callGetTempInfo = rpc.declare({
    object: 'luci',
    method: 'getTempInfo',
    expect: { tempinfo: '' }
});

"""
        page = replace_once(page, "return baseclass.extend({", declaration + "return baseclass.extend({", "status include")
        page = replace_once(page, "uci.load('system')", "uci.load('system'),\n\t\t\tL.resolveDefault(callGetTempInfo(), '')", "status load")
        page = replace_once(page, "_('Kernel Version'),   boardinfo.kernel,",
                            "_('Kernel Version'),   boardinfo.kernel,\n\t\t\t_('Temperature'),      data[5] || _('Unavailable'),",
                            "status fields")

    acl = json.loads((source / ACL).read_text())
    methods = acl["luci-mod-status-index"]["read"]["ubus"]["luci"]
    if "getTempInfo" not in methods:
        methods.append("getTempInfo")
    translations = (source / ZH_HANS).read_text()
    for label, translated in [("Temperature", "温度"), ("Unavailable", "不可用")]:
        if not re.search(r'^msgid "' + label + r'"$', translations, re.MULTILINE):
            translations = translations.rstrip() + f'\n\nmsgid "{label}"\nmsgstr "{translated}"\n'
    for relative, content in [(MAKEFILE, makefile), (RPC, rpc), (PAGE, page),
                              (ACL, json.dumps(acl, indent="\t") + "\n"), (ZH_HANS, translations)]:
        (source / relative).write_text(content)
    print("Integrated Airoha tempinfo, luci.getTempInfo, status temperature and read-only ACL.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: integrate-temperature.py PONWRT_SOURCE")
    integrate(pathlib.Path(sys.argv[1]).resolve())
