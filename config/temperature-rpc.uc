	// PonWrt-CI temperature integration.
	getTempInfo: {
		call: function() {
			const fd = popen('/sbin/tempinfo 2>/dev/null', 'r');
			if (!fd)
				return { tempinfo: '' };
			const value = trim(fd.read('all') ?? '');
			const status = fd.close();
			return { tempinfo: (status === 0 && value !== 'No temperature info') ? value : '' };
		}
	},

