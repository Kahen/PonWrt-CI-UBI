# PonWrt-CI-UBI

为 [pbs05/ponwrt](https://github.com/pbs05/ponwrt) 上游发布配置中的全部 PON 设备编译固件。
每周跟随上游 master，沿用原 XG-040G-MD CI 的常用软件包和中文界面。
仓库保存 CI、配置片段、包导入脚本与文件覆盖层，编译时拉取 PonWrt 源码。

## 支持机型

当前覆盖 AN7581 的 12 个 profile 和 AN7583 的 2 个 profile，共 14 个机型/布局配置。
每次构建从选定源码的 configs/an7581.config、configs/an7583.config 自动读取机型，
并检查源码设备定义和中文 README，防止漏掉上游已列出的设备。
构建范围与 PonWrt 的 PON 发布配置一致；不是 Airoha 目录下所有开发板。

| 芯片 | 设备/变体 | 下载文件中的 profile |
| --- | --- | --- |
| AN7581 | FiberHome HG5382A | `fiberhome_hg5382a` |
| AN7581 | FiberHome HG5585F CT | `fiberhome_hg5585f-ct` |
| AN7581 | FiberHome HG5585F CT USB-SFP | `fiberhome_hg5585f-ct-usb-sfp` |
| AN7581 | FiberHome HG5585F CU | `fiberhome_hg5585f-cu` |
| AN7581 | FiberHome HG5585F CU USB-SFP | `fiberhome_hg5585f-cu-usb-sfp` |
| AN7581 | Gemtek XG2010G | `gemtek_xg2010g` |
| AN7581 | Nokia XG-040G-MD UBI | `nokia_xg-040g-md-ubi` |
| AN7581 | Nokia XG-040G-MD UBI USB-SFP | `nokia_xg-040g-md-ubi-usb-sfp` |
| AN7581 | Nokia XG-040G-TF UBI | `nokia_xg-040g-tf-ubi` |
| AN7581 | UnionMan UNG00A | `unionman_ung00a` |
| AN7581 | ZNXT ZN504XG-D | `znxt_zn504xg-d` |
| AN7581 | ZNXT ZN515XG-D | `znxt_zn515xg-d` |
| AN7583 | Nokia XG-040G-MF 原布局 | `nokia_xg-040g-mf` |
| AN7583 | Nokia XG-040G-MF all-in-UBI | `nokia_xg-040g-mf-ubi` |

USB-SFP 与内置 PON 版本分别构建；MF 原布局与 UBI 布局分别构建。
XG-040G-MD 固件不能用于 ZN504XG-D，必须选择对应 profile 的镜像。
最新实际构建范围以每次 Release 的 `device-catalog.json` 为准。

## 构建与下载

- 每周日 **04:17，北京时间**自动构建并发布正式 Release；GitHub 调度可能延迟。
  即使本周上游没有新提交，也会构建一次。
- 修改编译相关文件并 push 到 main 会触发构建；仅修改 README 不触发。
- 手动运行：Actions → **Build PonWrt supported PON devices** → Run workflow。
  `source_ref` 默认 master，也可填上游提交或 tag；`publish_release` 可关闭发布。
- 两个芯片任务并行，每组使用独立的设备 rootfs；每个 profile 生成自己的固件。
  两组使用同一个源码提交和同一份固定 feeds，不会混用不同版本。
- **两组全部成功且所有机型通过校验后才发布 Release。**
  任一机型缺镜像、错板名、哈希不符或缺关键软件包都会阻止发布。
  单组成功时，仍可在该次 Actions 下载对应的 `PonWrt-firmware-an7581` /
  `PonWrt-firmware-an7583` Artifact；诊断文件另存为 `PonWrt-diagnostics-*`。
- 构建通过后发布正式 Release，并设为最新版本。通过编译与静态校验不代表所有实机都已测试。

在仓库 [Releases](https://github.com/Kahen/PonWrt-CI-UBI/releases) 下载对应完整型号、变体和布局的文件。
已有的全机型预发布版本可用 Actions → **Promote existing firmware release** 转为正式版，
留空 tag 选择最近发布的非草稿版本；只修改发布状态，不重建固件或替换附件。
使用 `profiles.json`、Release 机型表和文件名共同核对，不要只看芯片型号。

| 文件 | 用途 |
| --- | --- |
| `*-squashfs-sysupgrade.itb` / `*-squashfs-sysupgrade.bin` | 对应机型和已匹配布局的系统升级镜像 |
| `*-initramfs-recovery.itb` / 名称含 `initramfs` 的镜像 | RAM 启动、恢复或迁移流程使用，不是普通升级包 |
| 上游原生 `factory-*`、`preloader.bin`、`bl31-uboot.fip`（若该 profile 生成） | 初装/引导链文件，按该机型上游流程使用 |
| `*.manifest` | 从该 sysupgrade 的真实 rootfs 提取的软件包清单 |
| `*-sysupgrade-metadata.json` | 升级镜像板名、目标与 supported_devices |
| `an7581/3-profiles.json`、`*-build-summary.json` | 对应芯片的机型与镜像信息 |
| `an7581/3-build.config` | 实际 make defconfig 后生效的配置 |
| `*-source-commits.tsv`、`*-feeds-resolution.json` | 本次源码、feeds 与第三方包版本记录 |
| `device-catalog.json` | 本次选择的全部 profile 与源码提交 |
| `SHA256SUMS-an7581`、`SHA256SUMS-an7583` | 对应芯片的固件及记录文件校验和 |

本仓库不额外制作 XG-040G-MD factory 转换固件。保留上游各 profile 自带的产物；
MF 原布局的原生 factory 分拆文件不等同于 MD 的 UBI 迁移包。

## 软件包与硬件配置

共用原 CI 的 OpenClash、Lucky、GecoosAC（集客 AC）、Samba4、UPnP、WOL Ultra、
Footstrap、自动重启插件、中文 LuCI，以及 PON 页面、PON 驱动与调试工具。
PON 配置入口：**网络 → PON**。

系统概览通过 autocore 的温度脚本、luci.getTempInfo 和只读 ACL 显示实时温度。
CI 为 Airoha 补齐脚本安装与页面接入，并逐个检查最终镜像中的整条链路。
没有可用读数时显示“不可用”，不显示虚假的 0°C；温度会随概览页面轮询刷新。

- `config/common.config`：通用诊断、USB、文件系统与恢复所需驱动。
- `config/general-packages.config`：原 CI 的应用和 LuCI 选择。
- `config/pon-packages.config`：PON 栈、网络模块与关键运行依赖。
- 各机型上游默认硬件包按 profile 安装；无线、EEPROM、PHY 等依赖不会从 MD 复制到所有设备。
  AN7581 / AN7583 分别选择相应 NPU 固件。
- `config/required-packages.txt` 中的关键包与对应芯片 NPU 固件必须出现在每个升级镜像中。
  校验从 FIT 或 tar 镜像中读取 squashfs 的 apk/opkg 数据库，而非只检查总包清单。
  隐藏的 fitblk 在多机型配置中允许以 m 编译，仍必须安装进上游要求它的机型镜像。
- 其他已请求的可选符号若被上游删除或依赖不满足，会写入
  `*-requested-packages-dropped.txt`；可选包的存在不代表已验证全部运行功能。
- 第三方包延续原来源和更新方式，实际提交记录在每次构建产物中。
  保留的 attendedsysupgrade 插件不是本 CI 的升级发布入口。

每次先固定 PonWrt 源码 commit，再解析 feeds：保留上游已固定的版本；
未固定的 GitHub feed 选择不晚于源码提交时间的最新提交，并锁定到本次构建。
由于当前 `video` feed 的 Qt/GStreamer Kconfig 循环依赖会影响无显示设备的 PON 固件配置解析，
此 CI 在解析阶段排除该非必需多媒体 feed；保留 packages、LuCI、路由及 PON feeds，
并在 `feeds-resolution.json` 中记录 `excluded_feeds`。
这能减少 feed 超前的问题，但不能保证未来所有上游版本一定编译成功。

`config/xg040g-md-ubi.config`、`menuconfig.config`、`validation/resolved.config` 和
`config/feeds.conf` 保留作最初 MD 成功版本的记录，不参与当前多机型配置合并。

## 刷机前确认

按 [PonWrt 中文说明](https://github.com/pbs05/ponwrt/blob/master/README_zh.md)
中的对应机型流程核对引导链、分区和校准数据，再选镜像。
UBI 固件不会自动把原有非 UBI 分区迁移成 all-in-UBI。

| 机型 | 需要保留的本机原始数据 |
| --- | --- |
| FiberHome | `factory`；上游要求通过 fiberhome-factory 工具转换 |
| Gemtek | `dsd` |
| Nokia | `bosa`、`ri` |
| UnionMan / ZNXT | `reservearea`；按上游流程还原到 factory UBI 卷 |

保存设备当前信息和本机原始备份，尤其是布局转换前：

```sh
ubus call system board
cat /proc/mtd
ubinfo -a
```

确认板名、布局、引导链与镜像匹配后，先运行 `sysupgrade -T <镜像>`。
检查失败时不要强制刷入。切换固件前保存网络、PPPoE 和 VLAN 设置；
此仓库不包含用户认证凭据或校准数据。PON 驱动与页面存在也不保证运营商 OLT 注册成功。

MD all-in-UBI 上游布局使用 128 KiB BL2 区域、UBI 从 0x20000 开始；
如果当前设备仍是旧 Bootloader 512 KiB + env 512 KiB + ubi 布局，
必须先按上游迁移流程核对，不能仅凭文件名直接升级。

## 本地构建

安装依赖见 `.github/workflows/build.yml`。CI 仓库与 PonWrt 源码并排放置，
在 PonWrt 源码目录执行以下命令；`an7581` 可替换为 `an7583`：

```sh
python3 ../PonWrt-CI-UBI/scripts/devices.py discover . ../device-catalog.json
python3 ../PonWrt-CI-UBI/scripts/resolve-feeds.py .
./scripts/feeds update -a
./scripts/feeds install -a
bash ../PonWrt-CI-UBI/scripts/customize.sh
bash ../PonWrt-CI-UBI/scripts/configure.sh an7581 ../device-catalog.json
make download -j"$(nproc)"
make -j"$(nproc)" V=s
bash ../PonWrt-CI-UBI/scripts/collect.sh . ../output/an7581 an7581 ../device-catalog.json
```

`configure.sh` 每次重新生成 `.config`。如需调整应用，在 `config/` 片段中维护；
可用 `make menuconfig` 检查，再评估 `./scripts/diffconfig.sh` 的输出。
GitHub Actions 同时构建两种芯片，本地分别构建时需要独立源码目录或清理目标构建目录。
本地 feeds 解析可用 `GH_TOKEN` 提高 GitHub API 限额。

## 来源

- 固件与机型定义：[pbs05/ponwrt](https://github.com/pbs05/ponwrt)。
- PON 包：[pbs05/openwrt-pon-drivers](https://github.com/pbs05/openwrt-pon-drivers)、
  [pbs05/openwrt-pon-userspace](https://github.com/pbs05/openwrt-pon-userspace)。
- 原应用配置：[Kahen/ImmortalWrt-CI-XG-040G-MD-UBI](https://github.com/Kahen/ImmortalWrt-CI-XG-040G-MD-UBI)，
  迁移基准提交 `bce6b04f39fd2b2238c76c9bef6ba789f11ad10a`。
- 第三方包：vernesong/OpenClash、sirpdboy/luci-app-lucky、VIKINGYFY/packages、
  rchen14b/luci-app-airoha-npu（固定提交 `14521b8414da1e98517a295d8ec267087c7dde8e`）、VizzleTF/luci-theme-footstrap。
