include $(TOPDIR)/rules.mk

PKG_NAME:=hg5582a-support
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only

include $(INCLUDE_DIR)/package.mk

define Package/hg5582a-support
  SECTION:=base
  CATEGORY:=Base system
  TITLE:=HG5582A Toshiba ECC8 PON defaults and upgrade checks
  DEPENDS:=+airoha-ponctl +ubi-utils
endef

define Build/Compile
endef

define Package/hg5582a-support/install
	$(INSTALL_DIR) $(1)/usr/sbin $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./files/hg5582a-check-upgrade $(1)/usr/sbin/
	$(INSTALL_BIN) ./files/39-hg5582a-pon $(1)/etc/uci-defaults/
endef

$(eval $(call BuildPackage,hg5582a-support))
